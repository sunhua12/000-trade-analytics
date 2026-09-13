import json
from pathlib import Path

import pytest

import ingest
from trade_analytics.ingestion.exceptions import ComtradeRequestError
from trade_analytics.ingestion.queries import ComtradeQuery, QueryType
from trade_analytics.ingestion.storage import StoredIngestion


def successful_result(output_dir: Path, query: ComtradeQuery) -> StoredIngestion:
    target = output_dir / f"period={query.period}" / f"query_type={query.query_type.value}"
    return StoredIngestion(
        data_path=target / "data.ndjson",
        manifest_path=target / "manifest.json",
        row_count=2,
        checksum="sha256:abc123",
    )


def test_cli_uses_default_period_and_commodity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[ComtradeQuery] = []

    def runner(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
        captured.append(query)
        return successful_result(output_dir, query)

    exit_code = ingest.main(
        ["--query-type", "partner_detail", "--output-dir", str(tmp_path)],
        runner=runner,
    )

    assert exit_code == 0
    assert captured == [
        ComtradeQuery(
            period="202401",
            cmd_code="8542",
            query_type=QueryType.PARTNER_DETAIL,
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "success",
        "period": "202401",
        "query_type": "partner_detail",
        "row_count": 2,
        "data_path": str(tmp_path / "period=202401" / "query_type=partner_detail" / "data.ndjson"),
        "manifest_path": str(
            tmp_path / "period=202401" / "query_type=partner_detail" / "manifest.json"
        ),
        "checksum": "sha256:abc123",
    }


def test_cli_passes_explicit_world_query(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[ComtradeQuery] = []

    def runner(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
        captured.append(query)
        return successful_result(output_dir, query)

    exit_code = ingest.main(
        [
            "--period",
            "202402",
            "--cmd-code",
            "854231",
            "--query-type",
            "world_total",
            "--output-dir",
            str(tmp_path),
        ],
        runner=runner,
    )

    assert exit_code == 0
    assert captured[0].period == "202402"
    assert captured[0].cmd_code == "854231"
    assert captured[0].query_type is QueryType.WORLD_TOTAL
    assert "world_total" in capsys.readouterr().out


def test_cli_returns_one_for_invalid_period(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = ingest.main(["--period", "202413", "--query-type", "partner_detail"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "valid YYYYMM" in captured.err


def test_cli_returns_one_without_leaking_request_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "fake-secret-header"

    def failing_runner(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
        del query, output_dir
        raise ComtradeRequestError("UN Comtrade request failed with HTTP 503")

    exit_code = ingest.main(["--query-type", "partner_detail"], runner=failing_runner)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "HTTP 503" in captured.err
    assert secret not in captured.err


def test_cli_rejects_unknown_query_type() -> None:
    with pytest.raises(SystemExit) as error:
        ingest.main(["--query-type", "unknown"])

    assert error.value.code == 2


def test_cli_passes_revision_and_reports_already_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def runner(query: ComtradeQuery, output_dir: Path) -> StoredIngestion:
        assert query.revision == 2
        result = successful_result(output_dir, query)
        from dataclasses import replace

        return replace(result, status="already_exists")

    assert (
        ingest.main(
            ["--query-type", "partner_detail", "--revision", "2", "--output-dir", str(tmp_path)],
            runner=runner,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "already_exists"


@pytest.mark.parametrize("revision", ["0", "-1"])
def test_cli_rejects_invalid_revision(revision: str) -> None:
    assert ingest.main(["--query-type", "partner_detail", "--revision", revision]) == 1

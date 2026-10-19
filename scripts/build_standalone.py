"""Create one offline index.html with verified data, styles, scripts and map geometry."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_analytics.export.schemas import (  # noqa: E402
    MonthlyDocument,
    PartnerDocument,
    SnapshotManifest,
)
from trade_analytics.export.service import sha256, validate_snapshot  # noqa: E402


def build(output: Path, website: Path | None = None) -> None:
    frontend = ROOT / "frontend"
    source_dir = website if website is not None else frontend / "src"
    data_dir = website / "data" if website is not None else frontend / "public/data"
    asset_dir = website / "assets" if website is not None else frontend / "assets"
    files = {
        f"./data/{name}.json": (data_dir / f"{name}.json").read_bytes()
        for name in ("manifest", "monthly", "partners")
    }
    files["./assets/world.json"] = (asset_dir / "world.json").read_bytes()
    manifest_data = json.loads(files["./data/manifest.json"])
    multi_market = manifest_data["schema_version"] == "2.0.0"
    if multi_market:
        from types import SimpleNamespace

        from trade_analytics.export.v2 import DocumentV2, validate_v2

        manifest = SimpleNamespace(**manifest_data)
        manifest.files = SimpleNamespace(
            **{
                key: SimpleNamespace(**manifest_data["files"][f"{key}.json"])
                for key in ("monthly", "partners")
            }
        )
        manifest.start_month = __import__("datetime").date.fromisoformat(manifest.start_month)
        manifest.end_exclusive = __import__("datetime").date.fromisoformat(manifest.end_exclusive)
    else:
        manifest = SnapshotManifest.model_validate_json(files["./data/manifest.json"])
    raw = {}
    for name, model, metadata in (
        ("monthly", MonthlyDocument, manifest.files.monthly),
        ("partners", PartnerDocument, manifest.files.partners),
    ):
        payload = files[f"./data/{name}.json"]
        document = (DocumentV2 if multi_market else model).model_validate_json(payload)
        if (
            sha256(payload) != metadata.sha256
            or len(payload) != metadata.bytes
            or len(document.rows) != metadata.row_count
            or document.snapshot_id != manifest.snapshot_id
        ):
            raise ValueError("snapshot integrity check failed")
        if multi_market:
            from trade_analytics.export.v2 import MonthlyRowV2, PartnerRowV2

            row_model = MonthlyRowV2 if name == "monthly" else PartnerRowV2
            raw[name] = [
                row_model.model_validate_json(json.dumps(row)).model_dump() for row in document.rows
            ]
        else:
            raw[name] = [row.model_dump() for row in document.rows]
    (validate_v2 if multi_market else validate_snapshot)(
        raw, manifest.start_month, manifest.end_exclusive
    )
    embedded = json.dumps(
        {key: value.decode("utf-8") for key, value in files.items()}, ensure_ascii=False
    ).replace("<", "\\u003c")
    scripts = []
    for name in ("analytics", "charts", "app"):
        source = (source_dir / f"{name}.mjs").read_text()
        source = re.sub(r"^import .*?;\s*$", "", source, flags=re.MULTILINE)
        source = re.sub(r"\bexport (?=(?:function|const|let|class)\b)", "", source)
        scripts.append(source)
    # Shadow fetch locally: even file:// previews read the exact embedded bytes.
    # Browser WebCrypto still verifies the original data checksums.
    boot = """const offlineFiles = JSON.parse(document.getElementById('offline-files').textContent);
const fetch = async path => {
  if (!(path in offlineFiles)) throw new Error('此單檔預覽沒有指定資源。');
  const bytes = new TextEncoder().encode(offlineFiles[path]);
  return {ok:true,arrayBuffer:async()=>bytes.buffer};
};
"""
    bundle = ("(() => {\n" + boot + "\n".join(scripts) + "\n})();").replace(
        "</script", "<\\/script"
    )
    html = (source_dir / "index.html").read_text()
    html = html.replace(
        '<link rel="stylesheet" href="./style.css">',
        "<style>" + (source_dir / "style.css").read_text() + "</style>",
    )
    favicon = quote((source_dir / "favicon.svg").read_text(), safe="")
    html = html.replace('href="./favicon.svg"', f'href="data:image/svg+xml,{favicon}"')
    html = html.replace('<script type="module" src="./app.mjs"></script>', "")
    manifest_url = "data:application/json;charset=utf-8," + quote(
        files["./data/manifest.json"].decode(), safe=""
    )
    html = html.replace(
        'href="./data/manifest.json" target="_blank"',
        f'href="{manifest_url}" download="manifest.json"',
    )
    html = html.replace(
        "</body>",
        '<script type="application/json" id="offline-files">'
        + embedded
        + "</script><script>"
        + bundle
        + "</script></body>",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(
        json.dumps(
            {
                "status": "built",
                "path": str(output.resolve()),
                "snapshot_id": manifest.snapshot_id,
                "bytes": output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "index.html")
    parser.add_argument("--website-dir", type=Path)
    args = parser.parse_args()
    build(args.output, args.website_dir)

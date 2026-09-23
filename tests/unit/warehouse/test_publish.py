from typing import Any

import pytest

from trade_analytics.warehouse.publish import Publisher


def test_ambiguous_transport_error_is_not_reported_as_rollback():
    class LostResponsePublisher(Publisher):
        recorded: dict[str, Any] | None = None

        def query(self, sql, parameters=None):
            if "BEGIN TRANSACTION" in sql:
                self.jobs.append({"result": "unknown", "job_id": "ambiguous-job"})
                raise TimeoutError("The server may already have committed")
            self.recorded = parameters
            return []

    runner = LostResponsePublisher(None, "project", "models", "raw", "release")
    with pytest.raises(TimeoutError):
        runner.publish("batch", "202301")
    assert runner.recorded["outcome"] == "unknown"


def test_fault_injection_is_rejected_for_real_release_dataset():
    runner = Publisher(None, "project", "models", "raw", "release")
    with pytest.raises(ValueError, match="fixture"):
        runner.publish("batch", "202301", rollback_probe=True)
    assert not runner.jobs


def test_upstream_failure_persists_rules_and_partition_before_raising():
    class BrokenSourcePublisher(Publisher):
        recorded: dict[str, Any] | None = None

        def query(self, sql, parameters=None):
            return []

        def freeze(self, run_id, scope):
            raise RuntimeError("source unavailable")

        def _save_audit(self, run_id, result, candidate_hash):
            self.recorded = result
            return result

    runner = BrokenSourcePublisher(None, "project", "models", "raw", "release")
    with pytest.raises(RuntimeError, match="source unavailable"):
        runner.audit("batch", "202301")
    assert runner.recorded["period"] == "202301"
    assert runner.recorded["status"] == "FAIL"
    assert runner.recorded["rule_version"] == "reconciliation-v1"
    assert runner.recorded["pass_max"] == "0.005"

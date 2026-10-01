"""Fail closed unless a saved application plan only updates Lambda image_uri."""

import json
import sys
from pathlib import Path


def has_unknown(value: object) -> bool:
    if isinstance(value, dict):
        return any(has_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(has_unknown(item) for item in value)
    return value is True


def check(plan: dict, image_uri: str) -> dict:
    changes = []
    for resource in plan.get("resource_changes", []):
        change = resource["change"]
        if change["actions"] in (["no-op"], ["read"]):
            continue
        if resource["address"] != "aws_lambda_function.ingestion":
            raise ValueError(f"unexpected resource change: {resource['address']}")
        if change["actions"] != ["update"]:
            raise ValueError("deployment must not create, replace or delete Lambda")
        before, after = change["before"], change["after"]
        if after.get("image_uri") != image_uri:
            raise ValueError("plan image does not match requested digest")
        computed = {
            "last_modified",
            "qualified_arn",
            "qualified_invoke_arn",
            "version",
            "source_code_hash",
            "signing_job_arn",
            "signing_profile_version_arn",
        }
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        if changed - computed - {"image_uri"}:
            raise ValueError(f"unexpected Lambda configuration change: {sorted(changed)}")
        unknown = change.get("after_unknown", {})
        if any(has_unknown(value) for key, value in unknown.items() if key not in computed):
            raise ValueError("unexpected unknown configuration in deployment plan")
        changes.append({"address": resource["address"], "actions": change["actions"]})
    return {"image_uri": image_uri, "changes": changes}


if __name__ == "__main__":
    print(json.dumps(check(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2]), indent=2))

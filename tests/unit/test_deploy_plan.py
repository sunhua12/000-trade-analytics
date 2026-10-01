"""Deployment guard rejects infrastructure mutations before saved-plan apply."""

from copy import deepcopy

import pytest

from scripts.check_deploy_plan import check

IMAGE = "repository@sha256:" + "a" * 64


def plan() -> dict:
    return {
        "resource_changes": [
            {
                "address": "aws_lambda_function.ingestion",
                "change": {
                    "actions": ["update"],
                    "before": {"image_uri": "old", "timeout": 180},
                    "after": {"image_uri": IMAGE, "timeout": 180},
                    "after_unknown": {},
                },
            }
        ]
    }


def test_image_only_update_is_accepted() -> None:
    assert len(check(plan(), IMAGE)["changes"]) == 1


def test_known_nested_configuration_is_not_mistaken_for_unknown() -> None:
    value = plan()
    value["resource_changes"][0]["change"]["after_unknown"] = {
        "architectures": [False],
        "environment": [{"variables": {"RAW_BUCKET": False}}],
    }
    assert len(check(value, IMAGE)["changes"]) == 1


def test_unknown_nested_configuration_is_rejected() -> None:
    value = plan()
    value["resource_changes"][0]["change"]["after_unknown"] = {
        "environment": [{"variables": {"RAW_BUCKET": True}}]
    }
    with pytest.raises(ValueError, match="unknown"):
        check(value, IMAGE)


@pytest.mark.parametrize("mutation", ["role", "delete", "timeout", "digest", "unknown"])
def test_unsafe_plan_is_rejected(mutation: str) -> None:
    value = deepcopy(plan())
    resource = value["resource_changes"][0]
    change = resource["change"]
    if mutation == "role":
        resource["address"] = "aws_iam_role.lambda"
    elif mutation == "delete":
        change["actions"] = ["delete", "create"]
    elif mutation == "timeout":
        change["after"]["timeout"] = 900
    elif mutation == "digest":
        change["after"]["image_uri"] = "other"
    else:
        change["after_unknown"]["role"] = True
    with pytest.raises(ValueError):
        check(value, IMAGE)

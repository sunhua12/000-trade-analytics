"""Cloud smoke cleanup must preserve unrelated data in a versioned bucket."""

from unittest.mock import Mock

from scripts.smoke_etl_cloud import cleanup_s3


def test_cleanup_deletes_only_owned_versions_and_delete_markers():
    s3 = Mock()
    s3.get_paginator.return_value.paginate.return_value = [
        {
            "Versions": [
                {"Key": "_smoke/etl/run/data", "VersionId": "owned-version"},
                {"Key": "_smoke/etl/run/unrelated", "VersionId": "keep"},
            ],
            "DeleteMarkers": [{"Key": "_smoke/etl/run/data", "VersionId": "owned-marker"}],
        }
    ]
    s3.delete_objects.return_value = {}
    cleanup_s3(s3, "fixture-bucket", "_smoke/etl/run/", {"_smoke/etl/run/data"})
    s3.delete_objects.assert_called_once_with(
        Bucket="fixture-bucket",
        Delete={
            "Objects": [
                {"Key": "_smoke/etl/run/data", "VersionId": "owned-version"},
                {"Key": "_smoke/etl/run/data", "VersionId": "owned-marker"},
            ]
        },
    )

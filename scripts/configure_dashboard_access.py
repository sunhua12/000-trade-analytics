"""Idempotently grant the dashboard runtime read access to the published dataset."""

import argparse

from google.cloud import bigquery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="trade-analytics-508604")
    args = parser.parse_args()
    runtime = f"trade-dashboard-runtime@{args.project}.iam.gserviceaccount.com"
    client = bigquery.Client(project=args.project)
    dataset = client.get_dataset(f"{args.project}.trade_analytics_published")
    entry = bigquery.AccessEntry("READER", "userByEmail", runtime)
    if entry not in dataset.access_entries:
        dataset.access_entries = [*dataset.access_entries, entry]
        client.update_dataset(dataset, ["access_entries"])
    print(f"{runtime}: published Dataset READER configured")


if __name__ == "__main__":
    main()

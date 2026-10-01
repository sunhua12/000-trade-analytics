from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="hello_world_dag",
    start_date=datetime(2024, 1, 1),
    schedule=None,  # 手動觸發，不啟用定期排程
    catchup=False,
    tags=["test"],
) as dag:
    task_hello = BashOperator(
        task_id="print_hello",
        bash_command='echo "Hello Airflow from simple DAG"',
    )

    task_done = BashOperator(
        task_id="print_done",
        bash_command='echo "Pipeline finished"',
    )

    task_hello >> task_done

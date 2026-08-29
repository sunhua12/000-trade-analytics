FROM public.ecr.aws/lambda/python:3.11

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src

RUN python -m pip install . --target ${LAMBDA_TASK_ROOT}

CMD ["trade_analytics.lambda_handler.handler"]

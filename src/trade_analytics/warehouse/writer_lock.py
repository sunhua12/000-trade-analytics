"""Serialize supported local/Airflow writer entrypoints across the whole batch."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WriterBusyError(RuntimeError):
    """A cooperating writer currently owns the pipeline lock."""


@contextmanager
def writer_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WriterBusyError(
                "another pipeline writer is active; retry after it finishes"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

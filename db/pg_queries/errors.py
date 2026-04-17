class StaleReadError(Exception):
    """Raised when an optimistic-concurrency write finds a version mismatch.

    The caller expected version N, but the row already advanced past N.
    Map to HTTP 409 in api/main.py with {current_version, last_writer_source}.
    """

    def __init__(self, current_version: int, last_writer: str | None = None):
        self.current_version = current_version
        self.last_writer = last_writer
        super().__init__(
            f"Stale read: current version is {current_version}"
            + (f" (last writer: {last_writer})" if last_writer else "")
        )

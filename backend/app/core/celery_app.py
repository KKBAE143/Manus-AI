# Celery has been replaced with ThreadPoolExecutor (thread_runner.py) for local dev.
# This stub exists only to avoid import errors from any remaining references.

class _NoOpCelery:
    """Stub: background tasks run via thread_runner.py, not Celery."""

    def task(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    def send_task(self, *args, **kwargs):
        raise RuntimeError("Celery is disabled. Use thread_runner.submit_pipeline_job() instead.")


celery_app = _NoOpCelery()

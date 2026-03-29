from app.core.thread_runner import submit_pipeline_job, submit_rerun_chunk_job


def start_document_pipeline(document_id: str, job_id: str) -> bool:
    return submit_pipeline_job(document_id, job_id)


def rerun_chunk_background(document_id: str, chunk_id: str, stage_key: str = "extract") -> None:
    submit_rerun_chunk_job(document_id, chunk_id, stage_key)

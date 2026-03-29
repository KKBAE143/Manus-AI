from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.document import SplitMode


class DocumentCreateResponse(BaseModel):
    id: str
    filename: str
    status: str
    page_count: int
    message: str


class DocumentConfigCreate(BaseModel):
    book_title: str = "Untitled Manuscript"
    split_mode: SplitMode = SplitMode.pages
    pages_per_docx: int = Field(default=200, ge=25, le=1000)
    start_page: int = Field(default=1, ge=1)
    end_page: int = Field(default=10000, ge=1)
    keep_page_markers: bool = True
    generate_appendix_reference: bool = True


class DocumentConfigResponse(BaseModel):
    book_title: str
    split_mode: str
    pages_per_docx: int
    start_page: int
    end_page: int
    keep_page_markers: bool
    generate_appendix_reference: bool

    class Config:
        from_attributes = True


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    current_stage: int
    stage_key: str
    stage_name: str
    progress_percent: float
    progress_message: Optional[str] = None
    error_log: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExportPartResponse(BaseModel):
    id: str
    part_number: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    page_count: Optional[int] = None
    filename: str
    status: str
    download_url: str


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str
    page_count: Optional[int] = 0
    created_at: datetime
    updated_at: datetime
    manifest_available: bool = False
    merged_docx_available: bool = False
    latest_job: Optional[JobStatusResponse] = None
    part_count: int = 0


class DocumentDetailResponse(DocumentResponse):
    local_storage_path: str
    storage_root: Optional[str] = None
    manifest_path: Optional[str] = None
    merged_docx_path: Optional[str] = None
    config: Optional[DocumentConfigResponse] = None
    parts: List[ExportPartResponse] = []
    manifest_summary: Optional[Dict[str, Any]] = None


class MergeRequest(BaseModel):
    part_ids: Optional[List[str]] = None


class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int
    offset: int
    limit: int


class ChunkRerunRequest(BaseModel):
    chunk_ids: List[str]
    stage_key: str = "extract"


class MergeResponse(BaseModel):
    status: str
    download_url: str
    filename: str


class MergeJobAccepted(BaseModel):
    merge_job_id: str
    status: str
    message: str


class MergeJobStatusResponse(BaseModel):
    merge_job_id: str
    document_id: str
    status: str
    progress_percent: float
    progress_message: Optional[str] = None
    error_log: Optional[str] = None
    download_url: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

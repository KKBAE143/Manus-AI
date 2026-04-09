import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class SplitMode(str, enum.Enum):
    pages = "pages"
    chapters = "chapters"
    hybrid = "hybrid"


class DocumentStatus(str, enum.Enum):
    uploaded = "UPLOADED"
    inspected = "INSPECTED"
    planned = "PLANNED"
    queued = "QUEUED"
    processing = "PROCESSING"
    parts_ready = "PARTS_READY"
    merge_ready = "MERGE_READY"
    merged = "MERGED"
    archived = "ARCHIVED"
    ready = "READY"
    failed = "FAILED"


class JobStatus(str, enum.Enum):
    pending = "PENDING"
    in_progress = "IN_PROGRESS"
    completed = "COMPLETED"
    failed = "FAILED"


class PartStatus(str, enum.Enum):
    pending = "PENDING"
    generated = "GENERATED"
    failed = "FAILED"


class ChunkStatus(str, enum.Enum):
    pending = "PENDING"
    queued = "QUEUED"
    processing = "PROCESSING"
    completed = "COMPLETED"
    failed = "FAILED"
    cancelled = "CANCELLED"


class ArtifactType(str, enum.Enum):
    source_pdf = "SOURCE_PDF"
    chunk_text = "CHUNK_TEXT"
    cleaned_text = "CLEANED_TEXT"
    transformed_text = "TRANSFORMED_TEXT"
    transformed_json = "TRANSFORMED_JSON"
    manifest = "MANIFEST"
    docx_part = "DOCX_PART"      # Legacy support
    merged_docx = "MERGED_DOCX"  # Legacy support
    typst_part = "TYPST_PART"
    merged_pdf = "MERGED_PDF"
    appendix = "APPENDIX"
    log = "LOG"


class MergeStatus(str, enum.Enum):
    pending = "PENDING"
    in_progress = "IN_PROGRESS"
    completed = "COMPLETED"
    failed = "FAILED"


class ChunkStageStatus(str, enum.Enum):
    pending = "PENDING"
    processing = "PROCESSING"
    completed = "COMPLETED"
    failed = "FAILED"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    user_id = Column(String, index=True, nullable=False, default="anonymous")
    filename = Column(String, nullable=False)
    local_storage_path = Column(String, nullable=False)
    storage_root = Column(String, nullable=True)
    page_count = Column(Integer, nullable=True)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.uploaded, nullable=False)
    manifest_path = Column(String, nullable=True)
    merged_docx_path = Column(String, nullable=True)
    error_log = Column(Text, nullable=True)
    finalize_in_progress = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    config = relationship("DocumentConfig", back_populates="document", uselist=False, cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="document", cascade="all, delete-orphan", order_by="Job.created_at.desc()")
    parts = relationship("ExportPart", back_populates="document", cascade="all, delete-orphan", order_by="ExportPart.part_number.asc()")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan", order_by="Chunk.chunk_index.asc()")
    artifacts = relationship("Artifact", back_populates="document", cascade="all, delete-orphan", order_by="Artifact.created_at.asc()")
    events = relationship("ProjectEventLog", back_populates="document", cascade="all, delete-orphan", order_by="ProjectEventLog.created_at.asc()")
    merge_jobs = relationship("MergeJob", back_populates="document", cascade="all, delete-orphan", order_by="MergeJob.created_at.desc()")
    manuscript_drafts = relationship("ManuscriptDraft", back_populates="document", cascade="all, delete-orphan", order_by="ManuscriptDraft.created_at.desc()")
    export_profile = relationship("ExportProfile", back_populates="document", uselist=False, cascade="all, delete-orphan")


class DocumentConfig(Base):
    __tablename__ = "document_configs"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    book_title = Column(String, nullable=False, default="Untitled Manuscript")
    split_mode = Column(Enum(SplitMode), default=SplitMode.pages, nullable=False)
    pages_per_docx = Column(Integer, default=200, nullable=False)
    start_page = Column(Integer, default=1, nullable=False)
    end_page = Column(Integer, default=10000, nullable=False)
    keep_page_markers = Column(Boolean, default=True, nullable=False)
    generate_appendix_reference = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="config")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(Integer, default=1, nullable=False)
    stage_key = Column(String, default="queued", nullable=False)
    stage_name = Column(String, default="Queued", nullable=False)
    progress_percent = Column(Float, default=0.0, nullable=False)
    progress_message = Column(String, nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False)
    celery_task_id = Column(String, nullable=True)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    document = relationship("Document", back_populates="jobs")
    export_parts = relationship("ExportPart", back_populates="job", cascade="all, delete-orphan", order_by="ExportPart.part_number.asc()")


class ExportPart(Base):
    __tablename__ = "export_parts"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    part_number = Column(Integer, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    local_docx_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    status = Column(Enum(PartStatus), default=PartStatus.generated, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="parts")
    job = relationship("Job", back_populates="export_parts")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_start = Column(Integer, nullable=False)
    page_end = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=False)
    status = Column(Enum(ChunkStatus), default=ChunkStatus.pending, nullable=False)
    current_stage = Column(String, default="planned", nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    progress_percent = Column(Float, default=0.0, nullable=False)
    error_log = Column(Text, nullable=True)
    raw_text_path = Column(String, nullable=True)
    cleaned_text_path = Column(String, nullable=True)
    transformed_text_path = Column(String, nullable=True)
    transformed_text = Column(Text, nullable=True)
    transform_stats = Column(JSON, nullable=True)
    output_part_path = Column(String, nullable=True)
    chapter_title = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="chunks")
    stage_runs = relationship("ChunkStageRun", back_populates="chunk", cascade="all, delete-orphan", order_by="ChunkStageRun.created_at.asc()")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String, ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    artifact_type = Column(Enum(ArtifactType), nullable=False)
    label = Column(String, nullable=False)
    path = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="artifacts")


class ProjectEventLog(Base):
    __tablename__ = "project_event_logs"
    __table_args__ = (
        Index("ix_project_event_logs_document_id_created_at", "document_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String, default="INFO", nullable=False)
    event_type = Column(String, default="system", nullable=False)
    message = Column(Text, nullable=False)
    stage_key = Column(String, nullable=True)
    chunk_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="events")


class MergeJob(Base):
    __tablename__ = "merge_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(MergeStatus), default=MergeStatus.pending, nullable=False)
    output_path = Column(String, nullable=True)
    part_count = Column(Integer, default=0, nullable=False)
    progress_percent = Column(Float, default=0.0, nullable=True)
    progress_message = Column(String, nullable=True)
    validation_report = Column(Text, nullable=True)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    document = relationship("Document", back_populates="merge_jobs")


class ChunkStageRun(Base):
    __tablename__ = "chunk_stage_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    chunk_id = Column(String, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_key = Column(String, nullable=False)
    stage_name = Column(String, nullable=False)
    status = Column(Enum(ChunkStageStatus), default=ChunkStageStatus.pending, nullable=False)
    message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    chunk = relationship("Chunk", back_populates="stage_runs")


class AssemblyMode(str, enum.Enum):
    raw_merge = "RAW_MERGE"
    structured = "STRUCTURED"
    publication_ready = "PUBLICATION_READY"


class ReviewStatus(str, enum.Enum):
    pending = "PENDING"
    reviewed = "REVIEWED"
    approved = "APPROVED"
    locked = "LOCKED"


class ApprovalStatus(str, enum.Enum):
    pending = "PENDING"
    reviewed = "REVIEWED"
    approved = "APPROVED"
    locked = "LOCKED"


class DraftStatus(str, enum.Enum):
    assembling = "ASSEMBLING"
    ready = "READY"
    failed = "FAILED"


class ManuscriptDraft(Base):
    __tablename__ = "manuscript_drafts"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    assembly_mode = Column(Enum(AssemblyMode), nullable=False, default=AssemblyMode.structured)
    status = Column(Enum(DraftStatus), nullable=False, default=DraftStatus.assembling)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="manuscript_drafts")
    sections = relationship("ManuscriptSection", back_populates="draft", cascade="all, delete-orphan", order_by="ManuscriptSection.section_order.asc()")


class ManuscriptSection(Base):
    __tablename__ = "manuscript_sections"
    __table_args__ = (
        Index("ix_manuscript_sections_draft_id_section_order", "draft_id", "section_order"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    draft_id = Column(String, ForeignKey("manuscript_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String, ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    part_id = Column(String, ForeignKey("export_parts.id", ondelete="SET NULL"), nullable=True, index=True)
    section_order = Column(Integer, nullable=False)
    section_type = Column(String, default="body", nullable=False)
    title = Column(String, nullable=True)
    review_status = Column(Enum(ReviewStatus), default=ReviewStatus.pending, nullable=False)
    approval_status = Column(Enum(ApprovalStatus), default=ApprovalStatus.pending, nullable=False)
    flag_note = Column(Text, nullable=True)
    lock_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    draft = relationship("ManuscriptDraft", back_populates="sections")
    versions = relationship("SectionVersion", back_populates="section", cascade="all, delete-orphan", order_by="SectionVersion.version_number.asc()")

    @property
    def current_version(self):
        if not self.versions:
            return None
        edited = [v for v in self.versions if v.is_edited]
        if edited:
            return max(edited, key=lambda v: v.version_number)
        return max(self.versions, key=lambda v: v.version_number)


class SectionVersion(Base):
    __tablename__ = "section_versions"

    id = Column(String, primary_key=True, default=generate_uuid)
    section_id = Column(String, ForeignKey("manuscript_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    is_edited = Column(Boolean, default=False, nullable=False)
    edit_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    section = relationship("ManuscriptSection", back_populates="versions")


class UserEditAction(Base):
    __tablename__ = "user_edit_actions"

    id = Column(String, primary_key=True, default=generate_uuid)
    section_id = Column(String, ForeignKey("manuscript_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String, ForeignKey("section_versions.id", ondelete="SET NULL"), nullable=True)
    action_type = Column(String, nullable=False)
    previous_content = Column(Text, nullable=True)
    new_content = Column(Text, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChapterBoundary(Base):
    __tablename__ = "chapter_boundaries"

    id = Column(String, primary_key=True, default=generate_uuid)
    draft_id = Column(String, ForeignKey("manuscript_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String, ForeignKey("manuscript_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False)
    chapter_title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppendixSection(Base):
    __tablename__ = "appendix_sections"

    id = Column(String, primary_key=True, default=generate_uuid)
    draft_id = Column(String, ForeignKey("manuscript_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String, ForeignKey("manuscript_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    appendix_label = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExportProfile(Base):
    __tablename__ = "export_profiles"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    page_size = Column(String, default="A4", nullable=False)
    margin_top_cm = Column(Float, default=2.54, nullable=False)
    margin_bottom_cm = Column(Float, default=2.54, nullable=False)
    margin_left_cm = Column(Float, default=2.54, nullable=False)
    margin_right_cm = Column(Float, default=2.54, nullable=False)
    heading_mapping = Column(JSON, nullable=True)
    book_title = Column(String, nullable=True)
    subtitle = Column(String, nullable=True)
    author = Column(String, nullable=True)
    edition = Column(String, nullable=True)
    institution = Column(String, nullable=True)
    isbn = Column(String, nullable=True)
    copyright_year = Column(Integer, nullable=True)
    copyright_text = Column(String, nullable=True)
    disclaimer = Column(String, nullable=True)
    dedication = Column(String, nullable=True)
    preface = Column(String, nullable=True)
    acknowledgements = Column(String, nullable=True)
    include_toc = Column(Boolean, default=True, nullable=False)
    toc_heading_levels = Column(Integer, default=2, nullable=False)
    page_number_start = Column(Integer, default=1, nullable=False)
    page_number_format = Column(String, default="arabic", nullable=False)
    front_matter_sections = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="export_profile")

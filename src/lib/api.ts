const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export class ApiError extends Error {
  status?: number;
  backendUnavailable: boolean;

  constructor(message: string, options?: { status?: number; backendUnavailable?: boolean }) {
    super(message);
    this.name = 'ApiError';
    this.status = options?.status;
    this.backendUnavailable = options?.backendUnavailable ?? false;
  }
}

export interface JobStatus {
  job_id: string;
  document_id: string;
  status: string;
  current_stage: number;
  stage_key: string;
  stage_name: string;
  progress_percent: number;
  progress_message?: string | null;
  error_log?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DocumentPart {
  id: string;
  part_number: number;
  page_start?: number | null;
  page_end?: number | null;
  page_count?: number | null;
  filename: string;
  status: string;
  download_url: string;
}

export interface ChunkInfo {
  id: string;
  chunk_index: number;
  page_start: number;
  page_end: number;
  page_count: number;
  status: string;
  current_stage: string;
  retry_count: number;
  progress_percent: number;
  error_log?: string | null;
  raw_text_path?: string | null;
  cleaned_text_path?: string | null;
  output_part_path?: string | null;
  chapter_title?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface EventLog {
  id: string;
  level: string;
  event_type: string;
  message: string;
  stage_key?: string | null;
  chunk_id?: string | null;
  created_at: string;
}

export interface ArtifactInfo {
  id: string;
  chunk_id?: string | null;
  type: string;
  label: string;
  path: string;
  size_bytes?: number | null;
  created_at: string;
}

export interface MergeValidation {
  ok: boolean;
  missing_chunks: number[];
  missing_parts: number[];
  part_count: number;
  chunk_count: number;
  status: string;
}

export interface MergeJobAccepted {
  merge_job_id: string;
  status: string;
  message: string;
}

export interface MergeJobStatus {
  merge_job_id: string;
  document_id: string;
  status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  progress_percent: number;
  progress_message?: string | null;
  error_log?: string | null;
  download_url?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  status: string;
  page_count: number;
  created_at: string;
  updated_at: string;
  manifest_available: boolean;
  merged_docx_available: boolean;
  latest_job?: JobStatus | null;
  part_count: number;
}

export interface DocumentListResult {
  items: DocumentSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface DocumentDetail extends DocumentSummary {
  local_storage_path: string;
  storage_root?: string | null;
  manifest_path?: string | null;
  merged_docx_path?: string | null;
  config?: {
    book_title: string;
    split_mode: string;
    pages_per_docx: number;
    start_page: number;
    end_page: number;
    keep_page_markers: boolean;
    generate_appendix_reference: boolean;
  } | null;
  parts: DocumentPart[];
  manifest_summary?: {
    input_pdf: string;
    start_page: number;
    end_page: number;
    pages_per_docx: number;
    total_records: number;
    kept_pages: number;
    dropped_pages: number;
  } | null;
}

export type ReviewStatus = 'PENDING' | 'REVIEWED' | 'APPROVED' | 'LOCKED';
export type ApprovalStatus = 'PENDING' | 'REVIEWED' | 'APPROVED' | 'LOCKED';

export interface ManuscriptSection {
  id: string;
  draft_id: string;
  chunk_id?: string | null;
  part_id?: string | null;
  section_order: number;
  section_type: string;
  title?: string | null;
  review_status: ReviewStatus;
  approval_status?: ApprovalStatus | null;
  flag_note?: string | null;
  lock_reason?: string | null;
  chunk_index?: number | null;
  chunk_stage?: string | null;
  chunk_status?: string | null;
  version_count: number;
  created_at: string;
  updated_at: string;
  current_content?: string | null;
  current_version_number?: number | null;
}

export interface ReviewQueueItem extends ManuscriptSection {
  document_id: string;
  document_filename: string;
}

export interface GlobalReviewQueue {
  items: ReviewQueueItem[];
  total: number;
  approved_count: number;
}

export interface DocumentReviewQueue {
  document_id: string;
  filename: string;
  draft_id?: string;
  sections: ManuscriptSection[];
  total: number;
  approved_count?: number;
}

export interface AssembleWarning {
  warning: true;
  pending_review_count: number;
  total_sections: number;
  message: string;
}

export interface DraftStatus {
  has_draft: boolean;
  draft_id?: string;
  status?: string;
  section_count?: number;
  pending?: number;
  reviewed?: number;
  approved?: number;
  locked?: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new ApiError(`Unable to reach API at ${API_BASE}.`, { backendUnavailable: true });
    }
    throw error;
  }

  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(text || `Request failed: ${response.status}`, { status: response.status });
  }
  return response.json() as Promise<T>;
}

export function isBackendUnavailableError(error: unknown): boolean {
  return error instanceof ApiError && error.backendUnavailable;
}

export const api = {
  baseUrl: API_BASE,
  listDocuments: (params?: { status?: string; q?: string; offset?: number; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.q) search.set('q', params.q);
    if (params?.offset !== undefined) search.set('offset', String(params.offset));
    if (params?.limit !== undefined) search.set('limit', String(params.limit));
    const query = search.toString();
    return request<DocumentListResult>(`/api/v1/documents/${query ? `?${query}` : ''}`);
  },
  getDocument: (id: string) => request<DocumentDetail>(`/api/v1/documents/${id}`),
  getJob: (jobId: string) => request<JobStatus>(`/api/v1/documents/jobs/${jobId}`),
  getManifest: (id: string) => request<Record<string, unknown>>(`/api/v1/documents/${id}/manifest`),
  uploadDocument: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    let response: Response;

    try {
      response = await fetch(`${API_BASE}/api/v1/documents/upload`, {
        method: 'POST',
        body: formData,
      });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new ApiError(`Unable to reach API at ${API_BASE}.`, { backendUnavailable: true });
      }
      throw error;
    }

    if (!response.ok) {
      throw new ApiError(await response.text(), { status: response.status });
    }
    return response.json() as Promise<{ id: string; filename: string; status: string; page_count: number; message: string }>;
  },
  processDocument: (id: string, payload: Record<string, unknown>) =>
    request<{ message: string; job_id: string; document_id: string }>(`/api/v1/documents/${id}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  mergeDocument: (id: string, partIds?: string[]) =>
    request<{ status: string; filename: string; download_url: string }>(`/api/v1/documents/${id}/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_ids: partIds ?? null }),
    }),
  mergeParts: (id: string, orderedPartIds: string[]) =>
    request<MergeJobAccepted>(`/api/v1/documents/${id}/merge-parts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_ids: orderedPartIds }),
    }),
  getMergeStatus: (id: string) =>
    request<MergeJobStatus>(`/api/v1/documents/${id}/merge-status`),
  deleteDocument: (id: string) =>
    request<{ status: string; message: string }>(`/api/v1/documents/${id}`, {
      method: 'DELETE',
    }),
  getChunks: (id: string) => request<ChunkInfo[]>(`/api/v1/documents/${id}/chunks`),
  previewChapters: (id: string) =>
    request<{ boundaries: Array<{ page: number; title: string; confidence: number }>; total: number }>(
      `/api/v1/documents/${id}/preview-chapters`,
      { method: 'POST' },
    ),
  getEvents: (id: string) => request<EventLog[]>(`/api/v1/documents/${id}/events`),
  getArtifacts: (id: string) => request<ArtifactInfo[]>(`/api/v1/documents/${id}/artifacts`),
  getMergeValidation: (id: string) => request<MergeValidation>(`/api/v1/documents/${id}/merge-validation`),
  getSystemHealth: () => request<Record<string, number>>('/api/v1/documents/system/health'),
  rerunChunk: (documentId: string, chunkId: string) =>
    request<{ status: string; chunk_id: string }>(`/api/v1/documents/${documentId}/chunks/${chunkId}/rerun`, {
      method: 'POST',
    }),
  rerunChunks: (documentId: string, chunkIds: string[], stageKey = 'extract') =>
    request<{ items: Array<{ status: string; chunk_id: string; error?: string }>; stage_key: string }>(`/api/v1/documents/${documentId}/chunks/rerun`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunk_ids: chunkIds, stage_key: stageKey }),
    }),
  archiveDocument: (id: string) =>
    request<{ status: string }>(`/api/v1/documents/${id}/archive`, {
      method: 'POST',
    }),
  cloneConfig: (id: string, sourceDocumentId: string) =>
    request<{ status: string }>(`/api/v1/documents/${id}/clone-config?source_document_id=${sourceDocumentId}`, {
      method: 'POST',
    }),
  cancelJob: (jobId: string) =>
    request<{ status: string }>(`/api/v1/documents/jobs/${jobId}/cancel`, {
      method: 'POST',
    }),
  getGlobalReviewQueue: () => request<GlobalReviewQueue>('/api/v1/review-queue'),
  getDocumentReviewQueue: (documentId: string) =>
    request<DocumentReviewQueue>(`/api/v1/documents/${documentId}/review-queue`),
  flagSection: (sectionId: string, note: string) =>
    request<ManuscriptSection>(`/api/v1/sections/${sectionId}/flag`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    }),
  approveSection: (sectionId: string) =>
    request<{ section_id: string; review_status: string }>(`/api/v1/sections/${sectionId}/approve`, {
      method: 'POST',
    }),
  lockSection: (sectionId: string) =>
    request<{ section_id: string; review_status: string }>(`/api/v1/sections/${sectionId}/lock`, {
      method: 'POST',
    }),
  unlockSection: (sectionId: string, reason: string) =>
    request<ManuscriptSection>(`/api/v1/sections/${sectionId}/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }),
  getSection: (sectionId: string) =>
    request<ManuscriptSection>(`/api/v1/sections/${sectionId}`),
  getDraftSections: (draftId: string) =>
    request<ManuscriptSection[]>(`/api/v1/drafts/${draftId}/sections`),
  getDraftStatus: (documentId: string) =>
    request<DraftStatus>(`/api/v1/documents/${documentId}/draft/status`),
  updateSection: (sectionId: string, content: string, editNote?: string) =>
    request<ManuscriptSection>(`/api/v1/sections/${sectionId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, edit_note: editNote }),
    }),
};

export function absoluteUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE}${path}`;
}

export type SectionStatus = 'pending' | 'reviewed' | 'approved' | 'locked';
export type BreakType = 'chapter' | 'page';
export type AssemblyModeInput = 'raw_merge' | 'structured' | 'publication_ready' | 'RAW_MERGE' | 'STRUCTURED' | 'PUBLICATION_READY';

function normalizeAssemblyMode(mode: AssemblyModeInput): 'RAW_MERGE' | 'STRUCTURED' | 'PUBLICATION_READY' {
  switch (mode) {
    case 'raw_merge':
    case 'RAW_MERGE':
      return 'RAW_MERGE';
    case 'publication_ready':
    case 'PUBLICATION_READY':
      return 'PUBLICATION_READY';
    case 'structured':
    case 'STRUCTURED':
    default:
      return 'STRUCTURED';
  }
}

export interface ManuscriptDraft {
  id: string;
  document_id: string;
  status: string;
  mode?: string | null;
  created_at: string;
  updated_at: string;
  section_count?: number;
}

export interface SectionVersion {
  id: string;
  section_id: string;
  version_number: number;
  content: string;
  created_at: string;
  is_original: boolean;
}

export interface ManuscriptSection {
  position: number;
  heading?: string | null;
  content: string;
  status: SectionStatus;
  is_appendix: boolean;
  break_before?: BreakType | null;
  source_chunk_text?: string | null;
  versions?: SectionVersion[];
}

export interface ExportProfile {
  id: string;
  document_id: string;
  page_size: string;
  margin_top_cm: number;
  margin_bottom_cm: number;
  margin_left_cm: number;
  margin_right_cm: number;
  heading_mapping?: Record<string, string> | null;
  book_title?: string | null;
  subtitle?: string | null;
  author?: string | null;
  edition?: string | null;
  institution?: string | null;
  isbn?: string | null;
  copyright_year?: number | null;
  copyright_text?: string | null;
  disclaimer?: string | null;
  dedication?: string | null;
  preface?: string | null;
  acknowledgements?: string | null;
  include_toc: boolean;
  toc_heading_levels: number;
  page_number_start: number;
  page_number_format: string;
  front_matter_sections?: Record<string, boolean> | null;
  created_at: string;
  updated_at: string;
}

export const draftApi = {
  getDraft: (documentId: string) =>
    request<ManuscriptDraft>(`/api/v1/documents/${documentId}/draft`),

  ensureDraft: async (documentId: string, mode: AssemblyModeInput = 'structured') => {
    const draftStatus = await api.getDraftStatus(documentId);
    if (!draftStatus.has_draft) {
      await draftApi.assembleDraft(documentId, mode);
    }
    return draftApi.getDraft(documentId);
  },

  getSections: (draftId: string) =>
    request<ManuscriptSection[]>(`/api/v1/drafts/${draftId}/sections`),

  updateSection: (sectionId: string, payload: { content?: string; status?: SectionStatus; is_appendix?: boolean; break_before?: BreakType | null }) =>
    request<ManuscriptSection>(`/api/v1/sections/${sectionId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  getSectionVersions: (sectionId: string) =>
    request<SectionVersion[]>(`/api/v1/sections/${sectionId}/versions`),

  moveSectionUp: (draftId: string, sectionId: string) =>
    request<ManuscriptSection[]>(`/api/v1/drafts/${draftId}/sections/${sectionId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction: 'up' }),
    }),

  moveSectionDown: (draftId: string, sectionId: string) =>
    request<ManuscriptSection[]>(`/api/v1/drafts/${draftId}/sections/${sectionId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction: 'down' }),
    }),

  assembleDraft: (documentId: string, mode: AssemblyModeInput) =>
    request<{ status: string; draft_id: string }>(`/api/v1/documents/${documentId}/assemble`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: normalizeAssemblyMode(mode) }),
    }),

  reorderSections: (documentId: string, sectionOrder: string[]) =>
    request<ManuscriptDraft>(`/api/v1/documents/${documentId}/assemble-sections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_order: sectionOrder }),
    }),

  getExportProfile: (documentId: string) =>
    request<ExportProfile>(`/api/v1/documents/${documentId}/export-profile`),

  updateExportProfile: (documentId: string, data: Partial<ExportProfile>) =>
    request<ExportProfile>(`/api/v1/documents/${documentId}/export-profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  getChunkTransformed: (documentId: string, chunkId: string) =>
    request<{
      chunk_id: string;
      cleaned_text: string | null;
      transformed_text: string | null;
      has_transform: boolean;
      transform_stats: {
        total_blocks?: number;
        flagged_blocks?: number;
        rewritten_blocks?: number;
        fallback_blocks?: number;
        table_blocks?: number;
        pass1_batches?: number;
        pass2_batches?: number;
        provider_calls?: number;
        skipped?: boolean;
        error?: string;
      } | null;
    }>(`/api/v1/documents/${documentId}/chunks/${chunkId}/transformed`),

  exportDocx: (documentId: string, sectionOrder?: string[]) => {
    const body: Record<string, unknown> = { format: 'docx' };
    if (sectionOrder) body.section_order = sectionOrder;
    return fetch(`${API_BASE}/api/v1/documents/${documentId}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  exportPdf: (documentId: string, sectionOrder?: string[]) => {
    const body: Record<string, unknown> = { format: 'pdf' };
    if (sectionOrder) body.section_order = sectionOrder;
    return fetch(`${API_BASE}/api/v1/documents/${documentId}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
};

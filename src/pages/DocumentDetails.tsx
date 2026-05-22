import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  Download,
  FileText,
  Flag,
  Loader2,
  Lock,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
  Zap,
} from 'lucide-react';

import Header from '../components/Header';
import { usePollingBackoff } from '../hooks/usePollingBackoff';
import DeleteProjectButton from '../components/DeleteProjectButton';
import {
  absoluteUrl,
  api,
  ArtifactInfo,
  ChunkInfo,
  DocumentDetail,
  EventLog,
  ManuscriptSection,
  MergeValidation,
  ReviewStatus,
} from '../lib/api';

const ACTIVE_DOCUMENT_STATUSES = new Set(['QUEUED', 'PROCESSING']);
const ACTIVE_JOB_STATUSES = new Set(['PENDING', 'IN_PROGRESS']);

function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const base = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold';
  switch (status) {
    case 'PENDING':
      return <span className={`${base} bg-amber-50 text-amber-700`}>Awaiting</span>;
    case 'REVIEWED':
      return <span className={`${base} bg-orange-50 text-orange-700`}><Flag size={9} /> Flagged</span>;
    case 'APPROVED':
      return <span className={`${base} bg-green-50 text-green-700`}><CheckCircle2 size={9} /> Approved</span>;
    case 'LOCKED':
      return <span className={`${base} bg-gray-100 text-gray-600`}><Lock size={9} /> Locked</span>;
    default:
      return null;
  }
}

const phaseMap = [
  { key: 'queued',          label: 'Queued',                   friendly: 'Waiting to start' },
  { key: 'inspect',         label: 'Reading PDF',               friendly: 'Analysing your PDF file' },
  { key: 'plan',            label: 'Planning',                  friendly: 'Planning the conversion' },
  { key: 'extract',         label: 'Extracting',                friendly: 'Extracting all pages' },
  { key: 'clean_pass_1',    label: 'Cleaning (Pass 1)',         friendly: 'First round of text cleanup' },
  { key: 'clean_pass_2',    label: 'Cleaning (Pass 2)',         friendly: 'Second round of text cleanup' },
  { key: 'final_normalize', label: 'Normalising',               friendly: 'Final formatting pass' },
  { key: 'ai_transform',    label: 'AI Enhancement',            friendly: 'AI is improving the text' },
  { key: 'part_generate',   label: 'Creating Typst files',       friendly: 'Generating Typst parts' },
  { key: 'appendix_extract',label: 'Appendix',                  friendly: 'Extracting appendix content' },
  { key: 'merge_prep',      label: 'Preparing merge',          friendly: 'Getting ready to combine parts' },
  { key: 'completed',       label: 'Done',                      friendly: 'Conversion complete!' },
];

function friendlyDocStatus(status: string) {
  const map: Record<string, { label: string; color: string }> = {
    PLANNED:    { label: 'Getting Ready',       color: 'bg-purple-50 text-purple-700' },
    QUEUED:     { label: 'Queued',              color: 'bg-amber-50 text-amber-700' },
    PROCESSING: { label: 'Converting…',         color: 'bg-blue-50 text-blue-700' },
    COMPLETED:  { label: 'Ready to Download',   color: 'bg-green-50 text-green-700' },
    READY:      { label: 'Ready',               color: 'bg-green-50 text-green-700' },
    MERGE_READY:{ label: 'Ready to Merge',      color: 'bg-teal-50 text-teal-700' },
    FAILED:     { label: 'Failed',              color: 'bg-red-50 text-red-700' },
  };
  return map[status.toUpperCase()] || { label: status, color: 'bg-gray-100 text-gray-600' };
}

function chunkStatusStyle(status: string) {
  const s = status.toUpperCase();
  if (s === 'COMPLETED') return 'bg-green-50 text-green-700 border-green-100';
  if (s === 'PROCESSING' || s === 'IN_PROGRESS') return 'bg-blue-50 text-blue-700 border-blue-100';
  if (s === 'FAILED') return 'bg-red-50 text-red-700 border-red-100';
  return 'bg-gray-50 text-gray-500 border-gray-100';
}

function formatDate(value?: string) {
  if (!value) return 'Unknown';
  return new Date(value).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

export default function DocumentDetails() {
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();

  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [chunks, setChunks] = useState<ChunkInfo[]>([]);
  const [events, setEvents] = useState<EventLog[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [mergeValidation, setMergeValidation] = useState<MergeValidation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'chunks' | 'artifacts' | 'logs' | 'config'>('chunks');
  const [previewLines, setPreviewLines] = useState<string[]>([]);
  const [previewTitle, setPreviewTitle] = useState('');
  const [previewQuery, setPreviewQuery] = useState('');
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  const [bulkStageKey, setBulkStageKey] = useState('extract');
  const [chunkSectionMap, setChunkSectionMap] = useState<Record<string, ManuscriptSection>>({});
  const [showAdvancedConfig, setShowAdvancedConfig] = useState(false);
  const previewRef = React.useRef<HTMLDivElement | null>(null);

  const searchParams = new URLSearchParams(location.search);
  const jobId = searchParams.get('jobId');

  const loadDocument = useCallback(async (documentId: string) => {
    const data = await api.getDocument(documentId);
    setDocument(data);
    setError(null);
    return data;
  }, []);

  const loadChunkTabData = useCallback(async (documentId: string) => {
    const [chunkData, mergeData, reviewData] = await Promise.all([
      api.getChunks(documentId),
      api.getMergeValidation(documentId),
      api.getDocumentReviewQueue(documentId).catch(() => null),
    ]);
    setChunks(chunkData);
    setMergeValidation(mergeData);
    const map: Record<string, ManuscriptSection> = {};
    if (reviewData?.sections) {
      for (const section of reviewData.sections) {
        if (section.chunk_id) map[section.chunk_id] = section;
      }
    }
    setChunkSectionMap(map);
  }, []);

  const loadArtifactsTabData = useCallback(async (documentId: string) => {
    const artifactData = await api.getArtifacts(documentId);
    setArtifacts(artifactData);
  }, []);

  const loadLogsTabData = useCallback(async (documentId: string) => {
    const eventData = await api.getEvents(documentId);
    setEvents(eventData);
  }, []);

  const loadTabData = useCallback(async (documentId: string, tab: 'chunks' | 'artifacts' | 'logs' | 'config') => {
    if (tab === 'chunks') { await loadChunkTabData(documentId); return; }
    if (tab === 'artifacts') { await loadArtifactsTabData(documentId); return; }
    if (tab === 'logs') { await loadLogsTabData(documentId); return; }
    if (!mergeValidation) {
      const mergeData = await api.getMergeValidation(documentId);
      setMergeValidation(mergeData);
    }
  }, [loadArtifactsTabData, loadChunkTabData, loadLogsTabData, mergeValidation]);

  useEffect(() => {
    if (!id) return;
    let active = true;
    const load = async () => {
      try {
        await loadDocument(id);
        await loadTabData(id, activeTab);
      } catch (loadError) {
        if (active) setError('Failed to load project details.');
      } finally {
        if (active) setLoading(false);
      }
    };
    load();
    return () => { active = false; };
  }, [activeTab, id, jobId, loadDocument, loadTabData]);

  const shouldPoll = useMemo(() => {
    const documentStatus = (document?.status || '').toUpperCase();
    const jobStatus = (document?.latest_job?.status || '').toUpperCase();
    return ACTIVE_DOCUMENT_STATUSES.has(documentStatus) || ACTIVE_JOB_STATUSES.has(jobStatus);
  }, [document]);

  // Auto-redirect to Final Assembly when pipeline finishes processing during this session
  const prevStatusRef = useRef<string | null>(null);
  useEffect(() => {
    if (!document || !document.latest_job) return;
    const currentStatus = document.latest_job.status.toUpperCase();

    // If the status transitioned from an active state to COMPLETED while viewing this page
    if (prevStatusRef.current && ACTIVE_JOB_STATUSES.has(prevStatusRef.current) && currentStatus === 'COMPLETED') {
      navigate(`/assembly/${document.id}`);
    }

    prevStatusRef.current = currentStatus;
  }, [document, navigate]);

  usePollingBackoff({
    enabled: !!(id && shouldPoll),
    onPoll: useCallback(async () => {
      if (!id) return;
      await loadDocument(id);
      await loadTabData(id, activeTab);
    }, [activeTab, id, loadDocument, loadTabData]),
    minInterval: 4000,
    maxInterval: 60000,
  });

  const phases = useMemo(() => {
    const current = document?.latest_job?.stage_key || 'queued';
    return phaseMap.map((phase, index) => {
      const currentIndex = phaseMap.findIndex((item) => item.key === current);
      return {
        ...phase,
        state: currentIndex > index ? 'done' : currentIndex === index ? 'active' : 'pending',
      };
    });
  }, [document]);

  const loadPartPreview = async (partId: string, title: string) => {
    try {
      const response = await fetch(`${api.baseUrl}/api/v1/documents/parts/${partId}/preview?q=${encodeURIComponent(previewQuery)}`);
      const data = await response.json();
      setPreviewTitle(title);
      setPreviewLines(data.lines || []);
      setTimeout(() => previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    } catch {
      setPreviewTitle(title);
      setPreviewLines(['Preview unavailable']);
    }
  };

  const loadArtifactPreview = async (artifactId: string, title: string) => {
    try {
      const response = await fetch(`${api.baseUrl}/api/v1/documents/artifacts/${artifactId}/preview?q=${encodeURIComponent(previewQuery)}`);
      const data = await response.json();
      setPreviewTitle(title);
      setPreviewLines(data.lines || []);
      setTimeout(() => previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
    } catch {
      setPreviewTitle(title);
      setPreviewLines(['Preview unavailable']);
    }
  };

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-[#888]">
          <Loader2 size={28} className="animate-spin text-[#6A8776]" />
          <p className="text-sm font-medium">Loading your project…</p>
        </div>
      </main>
    );
  }

  if (error || !document) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <AlertTriangle size={32} className="text-red-400" />
        <p className="text-sm text-red-600">{error || 'Project not found.'}</p>
        <button onClick={() => navigate('/documents')} className="px-4 py-2 rounded-xl bg-[#222] text-white text-sm font-medium">
          Back to Projects
        </button>
      </main>
    );
  }

  const docStatus = friendlyDocStatus(document.status);
  const progress = document.latest_job?.progress_percent ?? 0;
  const isActive = shouldPoll;
  const isDone = document.status.toUpperCase() === 'COMPLETED' || document.status.toUpperCase() === 'READY';

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={document.filename}
        subtitle={`${document.page_count} pages  •  ${document.part_count} parts  •  Updated ${formatDate(document.updated_at)}`}
      />

      <div className="flex-1 overflow-y-auto pb-6 px-4 md:px-0 md:pr-2 space-y-4">

        {/* ── Status hero card ─────────────────────────────────────────────── */}
        <div className="bg-white rounded-3xl p-6 shadow-sm">
          <div className="flex flex-col md:flex-row gap-5 justify-between">

            {/* Left: status + progress */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-3">
                <span className={`text-xs font-bold px-3 py-1 rounded-full ${docStatus.color}`}>
                  {docStatus.label}
                </span>
                {isActive && (
                  <span className="flex items-center gap-1.5 text-xs text-[#6A8776] font-medium">
                    <Loader2 size={12} className="animate-spin" /> Live
                  </span>
                )}
              </div>

              {document.latest_job?.progress_message && (
                <p className="text-sm text-[#555] mb-3 leading-relaxed">{document.latest_job.progress_message}</p>
              )}

              {document.latest_job && (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-[#888]">
                      {document.latest_job.stage_name}
                    </span>
                    <span className="text-xs font-semibold text-[#6A8776]">{Math.round(progress)}%</span>
                  </div>
                  <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#6A8776] rounded-full transition-all duration-700"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Right: action buttons */}
            <div className="flex flex-wrap gap-2 shrink-0 items-start">
              <button
                onClick={() => navigate('/')}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50 text-[#555]"
              >
                <ArrowLeft size={14} /> Back
              </button>
              {isDone && (
                <button
                  onClick={() => { localStorage.setItem('lastWorkspaceDocId', document.id); navigate(`/workspace/${document.id}`); }}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#6A8776] text-white text-sm font-semibold hover:bg-[#5a7666] shadow-sm"
                >
                  <BookOpen size={14} /> Open Workspace
                </button>
              )}
              {document.merged_docx_available && (
                <a
                  href={absoluteUrl(`/api/v1/documents/${document.id}/merged/download`)}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#1D2E24] text-white text-sm font-semibold hover:bg-[#2a3f32]"
                >
                  <Download size={14} /> Download PDF
                </a>
              )}
              <a
                href={absoluteUrl(`/api/v1/documents/${document.id}/source`)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50 text-[#555]"
              >
                <Download size={14} /> Source PDF
              </a>
              <button
                onClick={() => navigate(`/config/${document.id}`)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50 text-[#555]"
              >
                <Pencil size={14} /> Settings
              </button>
              <DeleteProjectButton
                documentId={document.id}
                label="Delete"
                onDeleted={() => navigate('/documents')}
                className="!px-3 !py-2 !text-sm !rounded-xl"
              />
            </div>
          </div>
        </div>

        {/* ── Main 2-col: Pipeline + Parts ─────────────────────────────────── */}
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.3fr] gap-4">

          {/* Pipeline progress tracker */}
          <div className="bg-white rounded-3xl p-6 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="font-bold text-[#222] text-base">Conversion Steps</h2>
                <p className="text-xs text-[#888] mt-0.5">Track each stage of the process</p>
              </div>
              <button
                onClick={() => window.location.reload()}
                className="flex items-center gap-1.5 text-xs text-[#6A8776] hover:text-[#5a7666] font-medium"
              >
                <RefreshCw size={13} /> Refresh
              </button>
            </div>

            <div className="relative">
              {phases.map((phase, i) => (
                <div key={phase.key} className="flex items-start gap-3 mb-3 last:mb-0">
                  {/* Track line + dot */}
                  <div className="flex flex-col items-center shrink-0 w-6">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                      phase.state === 'done'
                        ? 'bg-[#6A8776] text-white'
                        : phase.state === 'active'
                        ? 'bg-blue-500 text-white'
                        : 'bg-gray-100 text-gray-400'
                    }`}>
                      {phase.state === 'done'
                        ? <CheckCircle2 size={14} />
                        : phase.state === 'active'
                        ? <Loader2 size={13} className="animate-spin" />
                        : <Circle size={10} />
                      }
                    </div>
                    {i < phases.length - 1 && (
                      <div className={`w-0.5 flex-1 mt-1 min-h-[12px] ${phase.state === 'done' ? 'bg-[#6A8776]/30' : 'bg-gray-100'}`} />
                    )}
                  </div>

                  {/* Label */}
                  <div className="pb-3 flex-1 min-w-0">
                    <p className={`text-sm font-medium leading-snug ${
                      phase.state === 'done' ? 'text-[#6A8776]'
                      : phase.state === 'active' ? 'text-[#222]'
                      : 'text-[#bbb]'
                    }`}>
                      {phase.label}
                    </p>
                    {phase.state === 'active' && document.latest_job && (
                      <div className="mt-1.5">
                        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden w-32">
                          <div
                            className="h-full bg-blue-400 rounded-full transition-all"
                            style={{ width: `${Math.max(6, Math.round(document.latest_job.progress_percent))}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-[#888] mt-1">{phase.friendly}</p>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {document.manifest_summary && (
              <div className="mt-5 pt-5 border-t border-gray-100">
                <p className="text-xs font-bold text-[#888] uppercase tracking-wider mb-3">Summary</p>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {[
                    ['Pages kept', document.manifest_summary.kept_pages],
                    ['Pages skipped', document.manifest_summary.dropped_pages],
                    ['Page range', `${document.manifest_summary.start_page}–${document.manifest_summary.end_page}`],
                    ['Pages/section', document.manifest_summary.pages_per_docx],
                  ].map(([label, value]) => (
                    <div key={label as string} className="bg-[#F8FBF9] rounded-xl px-3 py-2">
                      <p className="text-[#aaa] mb-0.5">{label}</p>
                      <p className="font-semibold text-[#222]">{value}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Generated parts */}
          <div className="bg-white rounded-3xl p-6 shadow-sm flex flex-col">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="font-bold text-[#222] text-base">Generated Typst Files</h2>
                <p className="text-xs text-[#888] mt-0.5">
                  {document.parts.length > 0
                    ? `${document.parts.length} file${document.parts.length !== 1 ? 's' : ''} ready to download`
                    : 'Files will appear here when ready'}
                </p>
              </div>
              {document.parts.length > 0 && (
                <button
                  onClick={() => navigate(`/assembly/${document.id}`)}
                  className="text-xs font-semibold text-[#6A8776] hover:underline flex items-center gap-1"
                >
                  Open Assembly →
                </button>
              )}
            </div>

            {document.parts.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center py-10 text-center">
                <div className="w-14 h-14 rounded-2xl bg-[#E8F0EB] flex items-center justify-center mb-3">
                  <FileText size={22} className="text-[#6A8776]" />
                </div>
                <p className="text-sm font-medium text-[#888]">
                  {isActive ? 'Generating your Typst files…' : 'No files generated yet'}
                </p>
                {isActive && <Loader2 size={16} className="animate-spin text-[#6A8776] mt-3" />}
              </div>
            ) : (
              <div className="flex flex-col gap-2 overflow-y-auto">
                {document.parts.map((part) => (
                  <div
                    key={part.id}
                    className="flex items-center gap-3 p-3.5 rounded-2xl border border-gray-100 hover:border-[#6A8776]/30 hover:bg-[#F8FBF9] transition-colors"
                  >
                    <div className="w-9 h-9 rounded-xl bg-[#E8F0EB] flex items-center justify-center shrink-0">
                      <FileText size={16} className="text-[#6A8776]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-sm text-[#222] truncate">{part.filename}</p>
                      <p className="text-[11px] text-[#aaa]">
                        Part {part.part_number}  •  pages {part.page_start ?? '?'}–{part.page_end ?? '?'}  •  {part.page_count ?? 0} pages
                      </p>
                    </div>
                    <button
                      onClick={() => navigate(`/documents/${document.id}/preview?partId=${part.id}`)}
                      className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium text-[#6A8776] hover:bg-[#E8F0EB] transition-colors"
                    >
                      Preview
                    </button>
                    <a
                      href={absoluteUrl(part.download_url)}
                      className="shrink-0 px-3 py-1.5 rounded-lg bg-[#1D2E24] text-white text-xs font-medium flex items-center gap-1.5 hover:bg-[#2a3f32]"
                    >
                      <Download size={12} /> Download
                    </a>
                  </div>
                ))}
              </div>
            )}

            {document.manifest_available && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <a
                  href={absoluteUrl(`/api/v1/documents/${document.id}/manifest`)}
                  className="text-xs text-[#6A8776] font-medium hover:underline"
                >
                  View manifest JSON →
                </a>
              </div>
            )}
          </div>
        </div>

        {/* ── Tabs section ─────────────────────────────────────────────────── */}
        <div className="bg-white rounded-3xl shadow-sm overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-gray-100">
            {([
              ['chunks',    'Sections'],
              ['artifacts', 'Artifacts'],
              ['logs',      'Activity Log'],
              ['config',    'Settings'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key as typeof activeTab)}
                className={`px-5 py-3.5 text-sm font-semibold transition-colors border-b-2 ${
                  activeTab === key
                    ? 'border-[#6A8776] text-[#6A8776] bg-[#F8FBF9]'
                    : 'border-transparent text-[#888] hover:text-[#333] hover:bg-gray-50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="p-6">

            {/* ── Sections (Chunks) tab ─────────────────────────────────── */}
            {activeTab === 'chunks' && (
              <div className="space-y-3">
                {/* Merge status bar */}
                <div className={`flex items-center gap-2 text-xs font-medium px-3 py-2 rounded-xl ${
                  mergeValidation?.ok ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'
                }`}>
                  {mergeValidation?.ok
                    ? <><CheckCircle2 size={14} /> All sections ready — you can merge</>
                    : <><AlertTriangle size={14} /> Some sections are not yet complete</>
                  }
                </div>

                {/* Bulk rerun controls */}
                <div className="flex items-center gap-2 flex-wrap">
                  <select
                    className="px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm text-[#333] focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                    value={bulkStageKey}
                    onChange={(e) => setBulkStageKey(e.target.value)}
                  >
                    <option value="extract">Restart from Extraction</option>
                    <option value="clean_pass_1">Restart from Cleanup</option>
                    <option value="part_generate">Restart from Word Generation</option>
                  </select>
                  <button
                    onClick={async () => {
                      if (!document || selectedChunkIds.length === 0) return;
                      try {
                        await api.rerunChunks(document.id, selectedChunkIds, bulkStageKey);
                        await Promise.all([loadDocument(document.id), loadChunkTabData(document.id)]);
                      } catch {
                        window.alert('Could not restart the selected sections. Please try again.');
                      }
                    }}
                    disabled={selectedChunkIds.length === 0}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#222] text-white text-sm font-medium disabled:opacity-40 hover:bg-[#333] transition-colors"
                  >
                    <RotateCcw size={13} />
                    Restart {selectedChunkIds.length > 0 ? `${selectedChunkIds.length} selected` : 'selected'}
                  </button>
                </div>

                {/* Chunk list */}
                {chunks.map((chunk) => {
                  const section = chunkSectionMap[chunk.id];
                  const isChecked = selectedChunkIds.includes(chunk.id);
                  return (
                    <div
                      key={chunk.id}
                      className={`rounded-2xl border transition-colors ${
                        isChecked ? 'border-[#6A8776]/40 bg-[#F8FBF9]' : 'border-gray-100'
                      }`}
                    >
                      <div className="flex items-center gap-3 p-4">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            setSelectedChunkIds((curr) =>
                              e.target.checked
                                ? [...curr, chunk.id]
                                : curr.filter((cid) => cid !== chunk.id)
                            );
                          }}
                          className="rounded accent-[#6A8776] shrink-0"
                        />

                        <div className="w-9 h-9 rounded-xl bg-[#E8F0EB] flex items-center justify-center text-xs font-bold text-[#6A8776] shrink-0">
                          {chunk.chunk_index}
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap mb-0.5">
                            <span className="font-semibold text-sm text-[#222]">Section {chunk.chunk_index}</span>
                            {section && <ReviewStatusBadge status={section.review_status} />}
                          </div>
                          <p className="text-[11px] text-[#aaa]">
                            Pages {chunk.page_start}–{chunk.page_end}  •  {chunk.page_count} pages
                            {chunk.chapter_title && <span className="text-[#6A8776] ml-1">— {chunk.chapter_title}</span>}
                          </p>
                          {chunk.current_stage && (
                            <p className="text-[10px] text-[#bbb] mt-0.5">{chunk.current_stage}  •  {Math.round(chunk.progress_percent)}%</p>
                          )}
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          <span className={`text-[10px] font-bold px-2.5 py-1 rounded-full border ${chunkStatusStyle(chunk.status)}`}>
                            {chunk.status.replace(/_/g, ' ')}
                          </span>
                          {section && (
                            <button
                              onClick={() => navigate(`/workspace/${document.id}?sectionId=${section.id}`)}
                              className="px-2.5 py-1.5 rounded-lg bg-[#E8F0EB] hover:bg-[#dce9e0] text-xs font-medium text-[#355846]"
                            >
                              Review
                            </button>
                          )}
                          <button
                            onClick={async () => {
                              if (!document) return;
                              try {
                                await api.rerunChunk(document.id, chunk.id);
                                await Promise.all([loadDocument(document.id), loadChunkTabData(document.id)]);
                              } catch {
                                window.alert('Could not restart this section. Please try again.');
                              }
                            }}
                            className="p-1.5 rounded-lg hover:bg-gray-100 text-[#888] hover:text-[#333] transition-colors"
                            title="Restart this section"
                          >
                            <RotateCcw size={14} />
                          </button>
                        </div>
                      </div>

                      {chunk.error_log && (
                        <div className="mx-4 mb-3 px-3 py-2 bg-red-50 rounded-xl text-xs text-red-600 leading-relaxed">
                          {chunk.error_log}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* ── Artifacts tab ─────────────────────────────────────────── */}
            {activeTab === 'artifacts' && (
              <div className="space-y-2">
                {artifacts.length === 0 && (
                  <p className="text-sm text-[#888] py-4 text-center">No artifacts yet.</p>
                )}
                {artifacts.map((artifact) => (
                  <div key={artifact.id} className="flex items-center gap-3 p-4 rounded-2xl border border-gray-100 hover:border-[#6A8776]/30 hover:bg-[#F8FBF9] transition-colors">
                    <div className="w-9 h-9 rounded-xl bg-[#E8F0EB] flex items-center justify-center shrink-0">
                      <Sparkles size={16} className="text-[#6A8776]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-sm text-[#222] truncate">{artifact.label}</p>
                      <p className="text-[11px] text-[#aaa] truncate">{artifact.type}</p>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={() => loadArtifactPreview(artifact.id, artifact.label)}
                        className="px-3 py-1.5 rounded-lg bg-[#E8F0EB] text-xs font-medium text-[#355846] hover:bg-[#dce9e0]"
                      >
                        Preview
                      </button>
                      <a
                        href={absoluteUrl(`/api/v1/documents/artifacts/${artifact.id}/download`)}
                        className="px-3 py-1.5 rounded-lg bg-[#1D2E24] text-white text-xs font-medium flex items-center gap-1 hover:bg-[#2a3f32]"
                      >
                        <Download size={12} /> Download
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── Activity Log tab ─────────────────────────────────────── */}
            {activeTab === 'logs' && (
              <div className="space-y-2 max-h-[480px] overflow-y-auto">
                {events.length === 0 && (
                  <p className="text-sm text-[#888] py-4 text-center">No activity yet.</p>
                )}
                {events.map((event) => (
                  <div key={event.id} className="flex gap-3 p-3.5 rounded-2xl border border-gray-100">
                    <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                      event.level === 'ERROR' ? 'bg-red-400' : event.level === 'WARN' ? 'bg-amber-400' : 'bg-[#6A8776]'
                    }`} />
                    <div className="min-w-0">
                      <p className="text-sm text-[#222] leading-snug">{event.message}</p>
                      <p className="text-[10px] text-[#bbb] mt-1">{formatDate(event.created_at)}  •  {event.stage_key || 'system'}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── Settings (Config) tab ────────────────────────────────── */}
            {activeTab === 'config' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[
                    ['Book title', document.config?.book_title || '—'],
                    ['Split mode', document.config?.split_mode || '—'],
                    ['Pages per section', document.config?.pages_per_docx ?? '—'],
                    ['Keep page markers', document.config?.keep_page_markers ? 'Yes' : 'No'],
                    ['Extract appendix', document.config?.generate_appendix_reference ? 'Yes' : 'No'],
                  ].map(([label, value]) => (
                    <div key={label as string} className="bg-[#F8FBF9] rounded-2xl px-4 py-3">
                      <p className="text-[10px] text-[#aaa] uppercase tracking-wider mb-1">{label}</p>
                      <p className="text-sm font-semibold text-[#222]">{String(value)}</p>
                    </div>
                  ))}
                </div>

                {mergeValidation && (
                  <div className={`rounded-2xl px-4 py-3 ${mergeValidation.ok ? 'bg-green-50' : 'bg-amber-50'}`}>
                    <p className="text-xs font-bold mb-2 ${mergeValidation.ok ? 'text-green-700' : 'text-amber-700'}">
                      Merge readiness
                    </p>
                    <p className="text-xs text-[#555]">
                      {mergeValidation.ok
                        ? 'All sections are complete — ready to merge.'
                        : `Missing sections: ${mergeValidation.missing_chunks.join(', ') || 'none'}. Missing parts: ${mergeValidation.missing_parts.join(', ') || 'none'}.`}
                    </p>
                  </div>
                )}

                {document.latest_job && (
                  <div className="flex gap-2 pt-2">
                    <button
                      onClick={async () => {
                        try {
                          await api.cancelJob(document.latest_job!.job_id);
                          const data = await api.getDocument(document.id);
                          setDocument(data);
                        } catch {
                          window.alert('Failed to cancel job.');
                        }
                      }}
                      className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-red-200 text-red-600 text-sm font-medium hover:bg-red-50"
                    >
                      <X size={14} /> Cancel job
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await api.archiveDocument(document.id);
                          const data = await api.getDocument(document.id);
                          setDocument(data);
                        } catch {
                          window.alert('Failed to archive project.');
                        }
                      }}
                      className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50"
                    >
                      Archive Project
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── Preview & Search ─────────────────────────────────────────────── */}
        <div ref={previewRef} className="bg-white rounded-3xl shadow-sm overflow-hidden">
          <div className="flex items-center justify-between gap-4 px-6 py-4 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <Search size={16} className="text-[#6A8776]" />
              <h2 className="font-bold text-[#222] text-base">Preview</h2>
              {previewTitle && <span className="text-sm text-[#888]">— {previewTitle}</span>}
            </div>
            <div className="relative flex items-center">
              <Search size={14} className="absolute left-3 text-gray-400" />
              <input
                value={previewQuery}
                onChange={(e) => setPreviewQuery(e.target.value)}
                placeholder="Filter text…"
                className="pl-8 pr-4 py-2 rounded-xl border border-gray-200 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
              />
            </div>
          </div>
          <div className="p-6">
            {previewLines.length > 0 ? (
              <div className="max-h-[320px] overflow-y-auto rounded-2xl bg-[#F8F8F6] p-4 text-sm text-[#333] whitespace-pre-wrap font-mono leading-relaxed">
                {previewLines.join('\n')}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-center text-[#888]">
                <FileText size={28} className="text-[#ddd] mb-2" />
                <p className="text-sm">Select a file or artifact above to preview its content here.</p>
              </div>
            )}
          </div>
        </div>

      </div>
    </main>
  );
}

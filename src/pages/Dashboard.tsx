import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, CheckCircle, ChevronDown, Cpu, FileText,
  FolderKanban, Layers3, Plus, Upload,
} from 'lucide-react';

import Header from '../components/Header';
import BackendUnavailableNotice from '../components/BackendUnavailableNotice';
import DeleteProjectButton from '../components/DeleteProjectButton';
import { api, DocumentSummary, isBackendUnavailableError } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

const ACTIVE_STATUSES = new Set(['QUEUED', 'PROCESSING']);

const PROCESSING_MODES = [
  { label: 'Fine (25 pages/chunk)', value: 25 },
  { label: 'Standard (50 pages/chunk)', value: 50 },
  { label: 'Coarse (100 pages/chunk)', value: 100 },
  { label: 'Bulk (200 pages/chunk)', value: 200 },
];

function formatDate(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

interface ActiveJob {
  jobId: string;
  docId: string;
  progress: number;
  stageName: string;
  status: string;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();

  // ── document list + health ──────────────────────────────────────────────
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [systemHealth, setSystemHealth] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [healthLoaded, setHealthLoaded] = useState(false);

  // ── quick-start pipeline state ──────────────────────────────────────────
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedDoc, setUploadedDoc] = useState<{ id: string; filename: string; page_count: number } | null>(null);

  const [processingMode, setProcessingMode] = useState(PROCESSING_MODES[1]);
  const [startPage, setStartPage] = useState('');
  const [endPage, setEndPage] = useState('');
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const [startingJob, setStartingJob] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── derived ─────────────────────────────────────────────────────────────
  const hasActiveDocJobs = useMemo(
    () => documents.some((d) => ACTIVE_STATUSES.has((d.status || '').toUpperCase())),
    [documents],
  );

  const stats = useMemo(() => {
    const queued = documents.filter((d) => ['UPLOADED', 'QUEUED'].includes(d.status)).length;
    const processing = documents.filter((d) => d.status === 'PROCESSING').length;
    const ready = documents.filter((d) => ['READY', 'MERGE_READY'].includes(d.status)).length;
    return { queued, processing, ready, total: documents.length };
  }, [documents]);

  const storageMB = ((systemHealth.storage_bytes || 0) / 1024 / 1024).toFixed(1);

  const jobDone = activeJob?.status === 'COMPLETED';
  const jobFailed = activeJob?.status === 'FAILED';
  const jobActive = activeJob && !jobDone && !jobFailed;

  // readiness: 0=no file, 50=uploading, 100=upload done
  const readiness = uploadedDoc ? 100 : uploadingFile ? 50 : 0;

  // can only start once upload is confirmed on the server
  const canStart = !!uploadedDoc && !startingJob && !jobActive;

  const displayPercent = activeJob ? Math.round(activeJob.progress) : readiness;
  const statusLabel = jobFailed
    ? 'Processing Failed'
    : jobDone
    ? 'Completed ✓'
    : jobActive
    ? 'Processing…'
    : uploadingFile
    ? 'Uploading…'
    : uploadedDoc
    ? 'Ready to Process'
    : 'Awaiting File';

  const recent = documents.slice(0, 6);

  // ── data loading ─────────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [data, health] = await Promise.all([
          api.listDocuments(),
          healthLoaded ? Promise.resolve(systemHealth) : api.getSystemHealth(),
        ]);
        if (active) {
          setDocuments(data.items);
          if (!healthLoaded) { setSystemHealth(health); setHealthLoaded(true); }
          setBackendUnavailable(false);
        }
      } catch (error) {
        if (active && isBackendUnavailableError(error)) {
          setBackendUnavailable(true);
          setDocuments([]);
          setSystemHealth({});
          setHealthLoaded(false);
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    load();
    return () => { active = false; };
  }, [backendUnavailable, healthLoaded]);

  useEffect(() => {
    if (backendUnavailable || !hasActiveDocJobs) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      api.listDocuments()
        .then((data) => { setDocuments(data.items); setBackendUnavailable(false); })
        .catch((err) => { if (isBackendUnavailableError(err)) { setBackendUnavailable(true); setDocuments([]); } });
    }, 10000);
    return () => window.clearInterval(interval);
  }, [backendUnavailable, hasActiveDocJobs]);

  // poll the active pipeline job
  useEffect(() => {
    if (!activeJob || ['COMPLETED', 'FAILED'].includes(activeJob.status)) return;
    const interval = window.setInterval(async () => {
      try {
        const job = await api.getJob(activeJob.jobId);
        setActiveJob((prev) =>
          prev ? { ...prev, progress: job.progress_percent, stageName: job.stage_name, status: job.status } : null,
        );
        if (job.status === 'COMPLETED') refreshDocuments();
      } catch {}
    }, 3000);
    return () => window.clearInterval(interval);
  }, [activeJob?.jobId, activeJob?.status]);

  // ── helpers ───────────────────────────────────────────────────────────────
  const refreshDocuments = async () => {
    try {
      const data = await api.listDocuments();
      setDocuments(data.items);
      setBackendUnavailable(false);
    } catch (err) {
      if (isBackendUnavailableError(err)) { setBackendUnavailable(true); setDocuments([]); }
    }
  };

  const resetUpload = () => {
    setSelectedFilename(null);
    setUploadedDoc(null);
    setUploadError(null);
    setUploadingFile(false);
    setActiveJob(null);
    setStartError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Upload happens immediately on file selection — mirrors Upload.tsx
  const handleFile = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadedDoc(null);
      setActiveJob(null);
      setSelectedFilename(null);
      setUploadError('Only PDF files are supported.');
      return;
    }
    setSelectedFilename(file.name);
    setUploadedDoc(null);
    setUploadError(null);
    setActiveJob(null);
    setStartError(null);
    setUploadingFile(true);
    try {
      const result = await api.uploadDocument(file);
      setUploadedDoc({ id: result.id, filename: result.filename, page_count: result.page_count });
      refreshDocuments();
    } catch (err) {
      const msg = isBackendUnavailableError(err)
        ? 'Backend is not reachable. Make sure the API server is running.'
        : 'Upload failed. Please try again.';
      setUploadError(msg);
      setSelectedFilename(null);
    } finally {
      setUploadingFile(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  // processDocument only — file is already on the server
  const handleStartProcessing = async () => {
    if (!uploadedDoc) return;
    setStartingJob(true);
    setStartError(null);
    try {
      const payload: Record<string, unknown> = {
        pages_per_docx: processingMode.value,
        split_mode: 'pages',
        keep_page_markers: false,
      };
      if (startPage) payload.start_page = parseInt(startPage);
      if (endPage) payload.end_page = parseInt(endPage);
      const job = await api.processDocument(uploadedDoc.id, payload);
      setActiveJob({ jobId: job.job_id, docId: uploadedDoc.id, progress: 0, stageName: 'Starting…', status: 'QUEUED' });
      refreshDocuments();
      navigate(`/documents/${uploadedDoc.id}`);
    } catch (err) {
      setStartError('Could not start processing. Please try again.');
      console.error('Processing failed:', err);
    } finally {
      setStartingJob(false);
    }
  };

  const handleActionClick = () => {
    if (jobDone && activeJob) { navigate(`/documents/${activeJob.docId}`); return; }
    if (canStart) handleStartProcessing();
  };

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={`Hello, ${user?.displayName?.split(' ')[0] || 'there'}!`}
        subtitle="Ready to convert your manuscript PDF into a publication-quality DOCX."
      />

      <div className="flex-1 overflow-y-auto pb-6 px-6 md:px-0 md:pr-2 flex flex-col">
        {backendUnavailable && (
          <div className="mb-5"><BackendUnavailableNotice apiBaseUrl={api.baseUrl} /></div>
        )}

        {/* Stats strip */}
        <div className="flex flex-wrap gap-2 mb-5">
          {[
            { label: 'Projects', value: stats.total, icon: FolderKanban },
            { label: 'Processing', value: stats.processing, icon: Layers3 },
            { label: 'Ready', value: stats.ready, icon: FileText },
            { label: `${storageMB} MB`, value: null, icon: null },
          ].map((s, i) => (
            <div key={i} className="flex items-center gap-2 bg-white rounded-2xl px-4 py-2 shadow-sm text-sm">
              {s.icon && <s.icon size={14} className="text-[#6A8776]" />}
              {s.value !== null && <span className="font-bold text-[#222]">{s.value}</span>}
              <span className="text-[#888]">{s.label}</span>
            </div>
          ))}
        </div>

        {/* Processing mode selector */}
        <div className="mb-5">
          <p className="text-[10px] font-bold uppercase tracking-widest text-[#aaa] mb-1.5">Select Processing Mode</p>
          <div className="relative inline-block">
            <select
              value={processingMode.label}
              onChange={(e) => {
                const found = PROCESSING_MODES.find((m) => m.label === e.target.value);
                if (found) setProcessingMode(found);
              }}
              className="appearance-none bg-white border border-gray-200 rounded-2xl px-4 pr-9 py-2.5 text-sm font-medium text-[#222] shadow-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30 cursor-pointer min-w-[220px]"
            >
              {PROCESSING_MODES.map((m) => (
                <option key={m.label} value={m.label}>{m.label}</option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#888] pointer-events-none" />
          </div>
        </div>

        {/* Main 3-card layout */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">

          {/* Card 1 — Upload PDF */}
          <div
            className={`bg-white rounded-3xl p-6 shadow-sm flex flex-col min-h-[270px] transition-all duration-200 ${
              dragOver ? 'ring-2 ring-[#6A8776] bg-[#F8FBF9]' : ''
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
          >
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-xl bg-[#E8F0EB] flex items-center justify-center">
                <Upload size={15} className="text-[#6A8776]" />
              </div>
              <span className="text-[10px] font-bold text-[#6A8776] uppercase tracking-widest">Upload PDF</span>
            </div>

            {/* Error state */}
            {uploadError && (
              <div className="flex-1 flex flex-col justify-between">
                <div className="flex items-start gap-2 p-3 bg-red-50 rounded-xl border border-red-100 mb-3">
                  <AlertCircle size={15} className="text-red-500 mt-0.5 shrink-0" />
                  <p className="text-xs text-red-700 leading-snug">{uploadError}</p>
                </div>
                <button onClick={resetUpload} className="text-xs text-[#6A8776] hover:underline text-left">
                  Try again
                </button>
              </div>
            )}

            {/* Uploading state */}
            {!uploadError && uploadingFile && (
              <div className="flex-1 flex flex-col justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-4 h-4 border-2 border-[#6A8776] border-t-transparent rounded-full animate-spin shrink-0" />
                    <span className="font-semibold text-[#222] text-sm truncate">{selectedFilename}</span>
                  </div>
                  <p className="text-xs text-[#888] ml-6">Uploading to server…</p>
                </div>
              </div>
            )}

            {/* Success state */}
            {!uploadError && !uploadingFile && uploadedDoc && (
              <div className="flex-1 flex flex-col justify-between">
                <div>
                  <div className="flex items-start gap-2 mb-2">
                    <CheckCircle size={17} className="text-[#6A8776] mt-0.5 shrink-0" />
                    <span className="font-semibold text-[#222] text-sm leading-snug break-all">{uploadedDoc.filename}</span>
                  </div>
                  <p className="text-xs text-[#888] ml-6">{uploadedDoc.page_count} pages detected</p>
                </div>
                <button onClick={resetUpload} className="text-xs text-[#bbb] hover:text-[#888] underline mt-4 text-left">
                  Change file
                </button>
              </div>
            )}

            {/* Idle drop zone */}
            {!uploadError && !uploadingFile && !uploadedDoc && (
              <div
                className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-gray-200 rounded-2xl px-6 py-8 cursor-pointer hover:border-[#6A8776]/40 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={30} className="text-[#ddd] mb-3" />
                <p className="text-sm font-medium text-[#888] text-center">Drop PDF here</p>
                <p className="text-xs text-[#bbb] mt-1">
                  or <span className="text-[#6A8776] font-medium">Select PDF →</span>
                </p>
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }}
            />

            <p className="text-[10px] text-[#ccc] mt-4">For large manuscripts (2000–4000 pages)</p>
          </div>

          {/* Card 2 — Configure */}
          <div className="bg-white rounded-3xl p-6 shadow-sm flex flex-col min-h-[270px]">
            <div className="flex items-center gap-2 mb-5">
              <div className="w-8 h-8 rounded-xl bg-[#E8F0EB] flex items-center justify-center">
                <Cpu size={15} className="text-[#6A8776]" />
              </div>
              <span className="text-[10px] font-bold text-[#6A8776] uppercase tracking-widest">Configure</span>
            </div>

            <div className="space-y-4 flex-1">
              <div>
                <label className="block text-[10px] text-[#aaa] uppercase tracking-wider mb-1.5">Pages per Chunk</label>
                <input
                  type="number"
                  value={processingMode.value}
                  min={5}
                  max={500}
                  onChange={(e) => {
                    const v = parseInt(e.target.value) || 50;
                    setProcessingMode({ label: `Custom (${v} pages/chunk)`, value: v });
                  }}
                  className="w-full bg-[#F6F8F7] rounded-xl px-4 py-2.5 text-sm font-semibold text-[#222] focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30 border-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-[#aaa] uppercase tracking-wider mb-1.5">Start Page</label>
                  <input
                    type="number"
                    placeholder="1"
                    value={startPage}
                    min={1}
                    onChange={(e) => setStartPage(e.target.value)}
                    className="w-full bg-[#F6F8F7] rounded-xl px-4 py-2.5 text-sm text-[#222] focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30 border-none"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-[#aaa] uppercase tracking-wider mb-1.5">End Page</label>
                  <input
                    type="number"
                    placeholder="All"
                    value={endPage}
                    min={1}
                    onChange={(e) => setEndPage(e.target.value)}
                    className="w-full bg-[#F6F8F7] rounded-xl px-4 py-2.5 text-sm text-[#222] focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30 border-none"
                  />
                </div>
              </div>
            </div>

            <p className="text-[10px] text-[#bbb] mt-5">Mode: {processingMode.label}</p>
          </div>

          {/* Card 3 column — Status (dark) + Action stacked */}
          <div className="flex flex-col gap-4">
            {/* Dark status card */}
            <div className="bg-[#1D2E24] text-white rounded-3xl p-6 shadow-sm flex-1 flex flex-col justify-between">
              <div>
                <p className="text-[10px] text-[#7fa88a] uppercase tracking-widest font-bold mb-3">
                  {statusLabel}
                </p>
                <p className="text-5xl font-bold text-white leading-none mb-1">
                  {displayPercent}%
                </p>
              </div>
              <div>
                <div className="mb-2">
                  <div className="h-[3px] bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#6A8776] rounded-full transition-all duration-700"
                      style={{ width: `${displayPercent}%` }}
                    />
                  </div>
                </div>
                <p className="text-[11px] text-[#7fa88a]">
                  {activeJob ? activeJob.stageName : `Mode: ${processingMode.label}`}
                </p>
              </div>
            </div>

            {/* Action card — entire card is clickable */}
            <div
              role="button"
              tabIndex={0}
              onClick={handleActionClick}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleActionClick(); }}
              title={!uploadedDoc && !jobDone ? 'Upload a PDF first' : undefined}
              className={`bg-white rounded-3xl px-5 py-4 shadow-sm flex flex-col gap-1 transition-all duration-200 select-none ${
                canStart || jobDone
                  ? 'cursor-pointer hover:shadow-md hover:bg-[#F8FBF9] active:scale-[0.99]'
                  : 'opacity-50 cursor-not-allowed'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-[#222] text-sm">
                    {jobDone ? 'View Result' : 'Start Processing'}
                  </p>
                  <p className="text-[11px] text-[#888] mt-0.5 truncate">
                    {startingJob
                      ? 'Starting pipeline…'
                      : jobActive
                      ? activeJob?.stageName
                      : uploadingFile
                      ? 'Waiting for upload…'
                      : uploadedDoc
                      ? 'Click to start the pipeline'
                      : 'Upload a PDF to enable'}
                  </p>
                </div>
                <div className={`w-11 h-11 rounded-full flex items-center justify-center shrink-0 transition-colors ${
                  canStart || jobDone ? 'bg-[#222] text-white' : 'bg-gray-200 text-gray-400'
                }`}>
                  {startingJob || jobActive ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Plus size={20} />
                  )}
                </div>
              </div>
              {startError && (
                <p className="text-[11px] text-red-500 mt-1">{startError}</p>
              )}
            </div>
          </div>
        </div>

        {/* Recent Projects */}
        <div className="bg-white rounded-3xl p-6 shadow-sm mb-5">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-[#222]">Recent Projects</h2>
              <p className="text-xs text-[#888] mt-0.5">Latest uploads, active jobs, and merge-ready runs.</p>
            </div>
            <button
              onClick={() => navigate('/documents')}
              className="text-xs font-medium text-[#6A8776] hover:underline"
            >
              View all
            </button>
          </div>

          {loading ? (
            <p className="text-sm text-[#888]">Loading projects…</p>
          ) : recent.length === 0 ? (
            <p className="text-sm text-[#888]">No projects yet. Upload your first PDF above.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {recent.map((item) => (
                <div
                  key={item.id}
                  onClick={() => navigate(`/documents/${item.id}`)}
                  className="p-4 rounded-2xl border border-gray-100 hover:border-[#6A8776]/30 hover:bg-[#F8FBF9] transition-colors cursor-pointer"
                >
                  <div className="flex items-start justify-between gap-3 mb-1.5">
                    <span className="font-semibold text-sm text-[#222] truncate leading-snug">{item.filename}</span>
                    <span className="text-[10px] font-bold px-2.5 py-1 rounded-full bg-gray-100 text-[#555] shrink-0 uppercase tracking-wide">
                      {item.status.replace('_', ' ')}
                    </span>
                  </div>
                  <p className="text-[11px] text-[#aaa]">
                    {item.page_count || 0} pages • {item.part_count} parts • {formatDate(item.updated_at)}
                  </p>
                  {item.latest_job && (
                    <div className="mt-2.5">
                      <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#6A8776] rounded-full transition-all"
                          style={{ width: `${item.latest_job.progress_percent}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-[#6A8776] mt-1">
                        {item.latest_job.stage_name} • {Math.round(item.latest_job.progress_percent)}%
                      </p>
                    </div>
                  )}
                  <div className="mt-3" onClick={(e) => e.stopPropagation()}>
                    <DeleteProjectButton documentId={item.id} onDeleted={refreshDocuments} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-auto pt-2 pb-2">
          <p className="text-base font-bold text-[#222]">Pilli Karthik.</p>
          <p className="text-xs text-[#bbb] flex items-center gap-1 mt-0.5">
            Made with <span className="text-red-400">♥</span> in India
          </p>
        </div>
      </div>
    </main>
  );
}

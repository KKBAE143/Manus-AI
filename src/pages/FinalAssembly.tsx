import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  RefreshCw,
  ToggleLeft,
  ToggleRight,
  Settings,
} from 'lucide-react';
import Header from '../components/Header';
import { api, absoluteUrl, DocumentPart, ExportProfile, draftApi, ManuscriptSection, MergeJobStatus } from '../lib/api';

interface PartRow {
  part: DocumentPart;
  excluded: boolean;
}

type MergePhase = 'idle' | 'polling' | 'done' | 'error';

export default function FinalAssembly() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [filename, setFilename] = useState('');
  const [mergedDocxAvailable, setMergedDocxAvailable] = useState(false);
  const [rows, setRows] = useState<PartRow[]>([]);
  const [profile, setProfile] = useState<Partial<ExportProfile>>({});
  const [bookTitle, setBookTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [mergePhase, setMergePhase] = useState<MergePhase>('idle');
  const [mergeJobStatus, setMergeJobStatus] = useState<MergeJobStatus | null>(null);
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const pollStatus = useCallback(async () => {
    if (!id) return;
    try {
      const status = await api.getMergeStatus(id);
      setMergeJobStatus(status);

      if (status.status === 'COMPLETED') {
        stopPolling();
        setMergePhase('done');
        setMergedDocxAvailable(true);
        if (status.download_url) {
          setDownloadUrl(absoluteUrl(status.download_url));
        } else {
          setDownloadUrl(absoluteUrl(`/api/v1/documents/${id}/merged/download`));
        }
      } else if (status.status === 'FAILED') {
        stopPolling();
        setMergePhase('error');
        setMergeError(status.error_log || 'Merge failed. Please try again.');
      }
    } catch {
      // Don't stop polling on transient network errors
    }
  }, [id]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(pollStatus, 4000);
  }, [pollStatus]);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [docData, profileData] = await Promise.all([
        api.getDocument(id),
        draftApi.getExportProfile(id).catch(() => null),
      ]);
      setFilename(docData.filename);
      setMergedDocxAvailable(docData.merged_docx_available);

      const allParts = (docData.parts || []).sort((a, b) => a.part_number - b.part_number);

      let orderedParts = allParts;
      try {
        const draftStatus = await api.getDraftStatus(id);
        if (draftStatus.has_draft && draftStatus.draft_id) {
          const sections: ManuscriptSection[] = await api.getDraftSections(draftStatus.draft_id);
          const sortedSections = sections
            .filter((s) => s.part_id)
            .sort((a, b) => (a.section_order ?? 0) - (b.section_order ?? 0));
          const partOrder = sortedSections.map((s) => s.part_id as string);
          const partMap = new Map(allParts.map((p) => [p.id, p]));
          const seenIds = new Set(partOrder);
          const reordered = partOrder.filter((pid) => partMap.has(pid)).map((pid) => partMap.get(pid)!);
          const extra = allParts.filter((p) => !seenIds.has(p.id));
          if (reordered.length > 0) {
            orderedParts = [...reordered, ...extra];
          }
        }
      } catch {
        // No draft; keep default sort
      }

      setRows(orderedParts.map((part) => ({ part, excluded: false })));

      if (profileData) {
        setProfile(profileData);
        setBookTitle(profileData.book_title || '');
        setAuthor(profileData.author || '');
      }

      // Hydrate merge status on load
      try {
        const status = await api.getMergeStatus(id);
        setMergeJobStatus(status);
        if (status.status === 'COMPLETED') {
          setMergePhase('done');
          setMergedDocxAvailable(true);
          setDownloadUrl(
            status.download_url
              ? absoluteUrl(status.download_url)
              : absoluteUrl(`/api/v1/documents/${id}/merged/download`)
          );
        } else if (status.status === 'IN_PROGRESS' || status.status === 'PENDING') {
          setMergePhase('polling');
          startPolling();
        } else if (status.status === 'FAILED') {
          setMergePhase('error');
          setMergeError(status.error_log || 'Previous merge failed.');
        }
      } catch {
        // No merge job yet; that's fine
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load assembly data');
    } finally {
      setLoading(false);
    }
  }, [id, startPolling]);

  useEffect(() => {
    load();
    return () => stopPolling();
  }, [load]);

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    setRows((prev) => {
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      return next;
    });
  };

  const moveDown = (idx: number) => {
    setRows((prev) => {
      if (idx >= prev.length - 1) return prev;
      const next = [...prev];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return next;
    });
  };

  const toggleExclude = (idx: number) => {
    setRows((prev) =>
      prev.map((row, i) => (i === idx ? { ...row, excluded: !row.excluded } : row))
    );
  };

  const handleGenerate = async () => {
    if (!id) return;
    setMergePhase('polling');
    setMergeError(null);
    setDownloadUrl(null);
    setMergeJobStatus(null);

    try {
      if (bookTitle !== profile.book_title || author !== profile.author) {
        await draftApi.updateExportProfile(id, { book_title: bookTitle || undefined, author: author || undefined });
      }

      const orderedIds = rows.filter((r) => !r.excluded).map((r) => r.part.id);
      if (orderedIds.length === 0) {
        setMergeError('No parts selected — include at least one part.');
        setMergePhase('idle');
        return;
      }

      const result = await api.mergeParts(id, orderedIds);
      // Backend returns 202 with merge_job_id; start polling
      setMergeJobStatus({
        merge_job_id: result.merge_job_id,
        document_id: id,
        status: 'PENDING',
        progress_percent: 0,
        progress_message: 'Queued',
      });
      startPolling();
    } catch (err: unknown) {
      setMergePhase('error');
      setMergeError(err instanceof Error ? err.message : 'Failed to start merge');
    }
  };

  const handleRetry = () => {
    setMergePhase('idle');
    setMergeError(null);
    setMergeJobStatus(null);
    handleGenerate();
  };

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center text-sm text-[#888888] gap-2">
        <Loader2 size={16} className="animate-spin" /> Loading…
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{error}</p>
        <button
          onClick={() => navigate(-1)}
          className="px-4 py-2 rounded-xl bg-[#222222] text-white text-sm"
        >
          Go Back
        </button>
      </main>
    );
  }

  const activeCount = rows.filter((r) => !r.excluded).length;
  const progressPct = mergeJobStatus?.progress_percent ?? 0;
  const progressMsg = mergeJobStatus?.progress_message ?? '';
  const isPolling = mergePhase === 'polling';

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={filename || 'Final Assembly'}
        subtitle="Order parts and generate your final merged manuscript DOCX."
      />

      <div className="bg-white border-b border-gray-100 px-4 py-3 flex items-center gap-3 flex-wrap shrink-0">
        <button
          onClick={() => navigate(`/documents/${id}`)}
          className="flex items-center gap-1.5 text-sm text-[#888888] hover:text-[#222222]"
        >
          <ArrowLeft size={15} /> Document
        </button>
        <div className="h-5 w-px bg-gray-200" />
        <span className="text-sm text-[#888888]">
          {activeCount} of {rows.length} parts included
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => navigate(`/publishing/${id}`)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-sm font-medium"
          >
            <Settings size={14} /> Publishing Tools
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-3">
          <h2 className="font-semibold text-base mb-4">Part Order</h2>

          {rows.length === 0 && (
            <div className="text-sm text-[#888888] text-center py-16">
              No DOCX parts found for this document. Run the processing pipeline first.
            </div>
          )}

          {rows.map((row, idx) => (
            <div
              key={row.part.id}
              className={`border rounded-2xl p-4 flex items-center gap-3 transition-all ${
                row.excluded
                  ? 'border-gray-100 bg-gray-50 opacity-50'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div className="flex flex-col gap-1">
                <button
                  onClick={() => moveUp(idx)}
                  disabled={idx === 0}
                  className="p-1 rounded-lg hover:bg-gray-100 disabled:opacity-30 text-[#888888]"
                  title="Move up"
                >
                  <ArrowUp size={13} />
                </button>
                <button
                  onClick={() => moveDown(idx)}
                  disabled={idx === rows.length - 1}
                  className="p-1 rounded-lg hover:bg-gray-100 disabled:opacity-30 text-[#888888]"
                  title="Move down"
                >
                  <ArrowDown size={13} />
                </button>
              </div>

              <div className="w-8 h-8 rounded-xl bg-[#F4F2EC] flex items-center justify-center text-xs font-bold text-[#6A8776] shrink-0">
                {idx + 1}
              </div>

              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">
                  {row.part.filename}
                </div>
                <div className="text-xs text-[#888888] mt-0.5">
                  Part {row.part.part_number}
                  {row.part.page_start != null && row.part.page_end != null
                    ? ` · pages ${row.part.page_start}–${row.part.page_end}`
                    : ''}
                  {row.part.page_count != null ? ` · ${row.part.page_count} pages` : ''}
                </div>
              </div>

              <a
                href={absoluteUrl(row.part.download_url)}
                className="p-1.5 rounded-xl hover:bg-gray-100 text-[#888888]"
                title="Download part"
              >
                <Download size={14} />
              </a>

              <button
                onClick={() => toggleExclude(idx)}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors ${
                  row.excluded
                    ? 'bg-gray-100 text-[#888888] hover:bg-green-50 hover:text-green-700'
                    : 'bg-[#E8F0EB] text-[#355846] hover:bg-red-50 hover:text-red-600'
                }`}
              >
                {row.excluded ? (
                  <><ToggleLeft size={12} /> Include</>
                ) : (
                  <><ToggleRight size={12} /> Exclude</>
                )}
              </button>
            </div>
          ))}
        </div>

        <aside className="w-72 shrink-0 bg-white border-l border-gray-100 flex flex-col p-6 gap-5 overflow-y-auto">
          <div className="space-y-4">
            <h3 className="font-semibold text-sm">Manuscript Details</h3>

            <div className="space-y-1">
              <label className="text-xs font-medium text-[#555]">Book Title</label>
              <input
                type="text"
                value={bookTitle}
                onChange={(e) => setBookTitle(e.target.value)}
                placeholder="Untitled Manuscript"
                className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-[#555]">Author</label>
              <input
                type="text"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="Author name"
                className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
              />
            </div>
          </div>

          <div className="border-t border-gray-100 pt-5 space-y-3">
            <h3 className="font-semibold text-sm">Generate Final Manuscript</h3>
            <p className="text-xs text-[#888888]">
              Merges all included parts into one DOCX file in the order shown, preserving all formatting.
            </p>

            {mergePhase === 'idle' && (
              <button
                onClick={handleGenerate}
                disabled={activeCount === 0}
                className="w-full px-4 py-2 rounded-xl bg-[#222222] text-white text-sm font-medium hover:bg-[#333] disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <FileText size={14} /> Generate Manuscript (DOCX)
              </button>
            )}

            {isPolling && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-[#555]">
                  <Loader2 size={13} className="animate-spin text-[#6A8776]" />
                  <span className="truncate">{progressMsg || 'Merging parts…'}</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-[#6A8776] h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.max(4, progressPct)}%` }}
                  />
                </div>
                <div className="text-xs text-[#888888] text-right">{Math.round(progressPct)}%</div>
              </div>
            )}

            {mergePhase === 'done' && downloadUrl && (
              <div className="space-y-2">
                <div className="text-xs text-green-700 bg-green-50 rounded-xl px-3 py-2 flex items-center gap-1.5">
                  <CheckCircle2 size={12} /> Manuscript ready to download!
                </div>
                <a
                  href={downloadUrl}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-medium hover:bg-green-700"
                >
                  <Download size={14} /> Download DOCX
                </a>
                <button
                  onClick={handleRetry}
                  className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl bg-gray-100 text-[#555] text-xs hover:bg-gray-200"
                >
                  <RefreshCw size={12} /> Generate again
                </button>
              </div>
            )}

            {mergePhase === 'error' && (
              <div className="space-y-2">
                <div className="text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2 flex items-start gap-1.5">
                  <AlertCircle size={12} className="shrink-0 mt-0.5" />
                  <span>{mergeError}</span>
                </div>
                <button
                  onClick={handleRetry}
                  className="w-full px-4 py-2 rounded-xl bg-[#222222] text-white text-sm font-medium hover:bg-[#333] flex items-center justify-center gap-2"
                >
                  <RefreshCw size={14} /> Retry
                </button>
              </div>
            )}

            {mergePhase === 'idle' && !downloadUrl && mergedDocxAvailable && id && (
              <a
                href={absoluteUrl(`/api/v1/documents/${id}/merged/download`)}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl border border-[#6A8776] text-[#6A8776] text-sm font-medium hover:bg-[#F0F6F2]"
              >
                <Download size={14} /> Re-download Last Merged DOCX
              </a>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}

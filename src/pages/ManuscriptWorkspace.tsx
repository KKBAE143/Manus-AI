import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  Columns2,
  AlignLeft,
  Loader2,
  BookText,
  ChevronRight,
  X,
  RotateCcw,
  Eye,
  ClipboardCheck,
  Library,
  Wrench,
  Sparkles,
} from 'lucide-react';

import Header from '../components/Header';
import SectionCard from '../components/SectionCard';
import {
  api,
  draftApi,
  ManuscriptDraft,
  ManuscriptSection,
  SectionVersion,
} from '../lib/api';

const ASSEMBLE_MODES = [
  {
    key: 'raw_merge',
    label: 'Raw Merge',
    description: 'Concatenates all sections in order with minimal formatting. Best for quick review.',
  },
  {
    key: 'structured',
    label: 'Structured',
    description: 'Inserts chapter and page breaks where marked, with section headings styled.',
  },
  {
    key: 'publication_ready',
    label: 'Publication-Ready',
    description: 'Full typographic treatment: front matter, TOC, headers/footers, consistent spacing.',
  },
];

export interface ActionState {
  sectionId: string;
  type: 'flag' | 'unlock';
  inputValue: string;
}

export default function ManuscriptWorkspace() {
  const { id, documentId } = useParams<{ id?: string; documentId?: string }>();
  const docId = documentId || id || '';
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const focusSectionId = searchParams.get('sectionId');

  const [document, setDocument] = useState<{ filename: string; status: string } | null>(null);
  const [draft, setDraft] = useState<ManuscriptDraft | null>(null);
  const [sections, setSections] = useState<ManuscriptSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [splitMode, setSplitMode] = useState(false);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyVersions, setHistoryVersions] = useState<SectionVersion[]>([]);
  const [historySectionId, setHistorySectionId] = useState<string | null>(null);
  const [historyRestoring, setHistoryRestoring] = useState<string | null>(null);

  const [assembleOpen, setAssembleOpen] = useState(false);
  const [assembleMode, setAssembleMode] = useState<string>('structured');
  const [assembling, setAssembling] = useState(false);
  const [assembleError, setAssembleError] = useState<string | null>(null);
  const [assembleSuccess, setAssembleSuccess] = useState(false);

  const [actionState, setActionState] = useState<ActionState | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const [transformOpen, setTransformOpen] = useState(false);
  const [transformLoading, setTransformLoading] = useState(false);
  const [transformSection, setTransformSection] = useState<ManuscriptSection | null>(null);
  const [transformData, setTransformData] = useState<{
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
  } | null>(null);

  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const load = useCallback(async () => {
    if (!docId) return;
    localStorage.setItem('lastWorkspaceDocId', docId);
    try {
      const [docData, draftData] = await Promise.all([
        api.getDocument(docId),
        draftApi.ensureDraft(docId),
      ]);
      setDocument({ filename: docData.filename, status: docData.status });
      setDraft(draftData);
      const sectionData = await draftApi.getSections(draftData.id);
      setSections(sectionData);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load workspace');
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (focusSectionId && sections.length > 0) {
      const el = window.document.getElementById(`section-${focusSectionId}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }, [focusSectionId, sections]);

  const scrollToSection = (sectionId: string) => {
    const el = window.document.getElementById(`section-${sectionId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleSectionUpdate = (updated: ManuscriptSection) => {
    setSections((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
  };

  const handleMove = async (sectionId: string, direction: 'up' | 'down') => {
    if (!draft) return;
    try {
      const updated =
        direction === 'up'
          ? await draftApi.moveSectionUp(draft.id, sectionId)
          : await draftApi.moveSectionDown(draft.id, sectionId);
      if (Array.isArray(updated)) {
        setSections(updated);
      }
    } catch {
    }
  };

  const openHistory = async (sectionId: string) => {
    setHistorySectionId(sectionId);
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryVersions([]);
    try {
      const versions = await draftApi.getSectionVersions(sectionId);
      setHistoryVersions(versions);
    } catch {
      setHistoryVersions([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const closeHistory = () => {
    setHistoryOpen(false);
    setHistorySectionId(null);
    setHistoryVersions([]);
  };

  const restoreVersion = async (version: SectionVersion) => {
    if (!historySectionId) return;
    setHistoryRestoring(version.id);
    try {
      const updated = await draftApi.updateSection(historySectionId, { content: version.content });
      handleSectionUpdate(updated);
      closeHistory();
    } catch {
    } finally {
      setHistoryRestoring(null);
    }
  };

  const handleAssemble = async () => {
    if (!docId) return;
    setAssembling(true);
    setAssembleError(null);
    setAssembleSuccess(false);
    try {
      await draftApi.assembleDraft(docId, assembleMode);
      setAssembleSuccess(true);
      setTimeout(() => {
        setAssembleOpen(false);
        setAssembleSuccess(false);
      }, 1500);
    } catch (err: unknown) {
      setAssembleError(err instanceof Error ? err.message : 'Assembly failed');
    } finally {
      setAssembling(false);
    }
  };

  const performReviewAction = async (sectionId: string, type: 'approve' | 'lock') => {
    setActionLoading(true);
    try {
      if (type === 'approve') await api.approveSection(sectionId);
      else await api.lockSection(sectionId);
      await load();
    } catch {
      window.alert(`Failed to ${type} section.`);
    } finally {
      setActionLoading(false);
    }
  };

  const openTransform = async (section: ManuscriptSection) => {
    if (!section.chunk_id) return;
    setTransformSection(section);
    setTransformOpen(true);
    setTransformLoading(true);
    setTransformData(null);
    try {
      const data = await api.getChunkTransformed(docId, section.chunk_id);
      setTransformData(data);
    } catch {
      setTransformData(null);
    } finally {
      setTransformLoading(false);
    }
  };

  const closeTransform = () => {
    setTransformOpen(false);
    setTransformSection(null);
    setTransformData(null);
  };

  const performFlagOrUnlock = async (note: string) => {
    if (!actionState) return;
    if (!note.trim()) {
      window.alert(`Please enter a ${actionState.type === 'flag' ? 'flag note' : 'unlock reason'}.`);
      return;
    }
    setActionLoading(true);
    try {
      if (actionState.type === 'flag') {
        await api.flagSection(actionState.sectionId, note.trim());
      } else {
        await api.unlockSection(actionState.sectionId, note.trim());
      }
      setActionState(null);
      await load();
    } catch {
      window.alert(`Failed to ${actionState.type} section.`);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center text-sm text-[#888888] gap-2">
        <Loader2 size={16} className="animate-spin" /> Loading workspace…
      </main>
    );
  }

  if (error || !draft) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{error || 'Draft not found.'}</p>
        <button
          onClick={() => navigate(`/documents/${docId}`)}
          className="px-4 py-2 rounded-xl bg-[#222222] text-white text-sm"
        >
          Back to Document
        </button>
      </main>
    );
  }

  const approvedCount = sections.filter((s) => s.status === 'approved').length;

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={document?.filename || 'Manuscript Workspace'}
        subtitle="Inspect, edit, and approve manuscript sections before final export."
      />

      <div className="flex-1 flex overflow-hidden">
        <aside className="hidden lg:flex w-56 shrink-0 flex-col bg-white border-r border-gray-100 overflow-y-auto p-4 gap-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-[#888888] mb-2">Sections</div>
          {sections.map((section, idx) => (
            <button
              key={section.id}
              onClick={() => scrollToSection(section.id)}
              className="text-left px-3 py-2 rounded-xl text-sm hover:bg-[#E8F0EB] transition-colors group flex items-center gap-2"
            >
              <BookText size={13} className="shrink-0 text-[#6A8776]" />
              <span className="truncate text-[#222222]">
                {section.heading || section.title || `Section ${idx + 1}`}
              </span>
              <ChevronRight size={12} className="shrink-0 text-[#aaa] group-hover:text-[#6A8776] ml-auto" />
            </button>
          ))}
        </aside>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="bg-white border-b border-gray-100 px-4 py-3 flex items-center gap-3 flex-wrap shrink-0">
            <button
              onClick={() => navigate(`/documents/${docId}`)}
              className="flex items-center gap-1.5 text-sm text-[#888888] hover:text-[#222222] transition-colors"
            >
              <ArrowLeft size={15} /> Back
            </button>
            <div className="h-4 border-l border-gray-200" />
            <span className="text-sm text-[#888888]">
              {approvedCount} / {sections.length} approved
            </span>
            <div className="flex-1" />
            <button
              onClick={() => navigate('/review')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#E8F0EB] text-[#6A8776] hover:bg-[#d5e6da] transition-colors"
            >
              <ClipboardCheck size={13} /> Review Queue
            </button>
            <button
              onClick={() => setSplitMode((v) => !v)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors ${
                splitMode
                  ? 'bg-[#222222] text-white'
                  : 'bg-gray-100 text-[#444444] hover:bg-gray-200'
              }`}
            >
              {splitMode ? <AlignLeft size={13} /> : <Columns2 size={13} />}
              {splitMode ? 'Single' : 'Split View'}
            </button>
            <button
              onClick={() => navigate(`/workspace/${docId}/book-preview`)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-gray-100 hover:bg-gray-200 transition-colors"
            >
              <Eye size={13} /> Preview as Book
            </button>
            <button
              onClick={() => setAssembleOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#6A8776] text-white hover:bg-[#5a7366] transition-colors"
            >
              Assemble Draft
            </button>
            <button
              onClick={() => navigate(`/assembly/${docId}`)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-gray-100 hover:bg-gray-200 transition-colors"
            >
              <Library size={13} /> Assembly
            </button>
            <button
              onClick={() => navigate(`/publishing/${docId}`)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#222222] text-white hover:bg-[#333] transition-colors"
            >
              <Wrench size={13} /> Publishing
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
            {sections.map((section, idx) => (
              <div key={section.id} ref={(el) => { sectionRefs.current[section.id] = el; }}>
                <SectionCard
                  section={section}
                  isFirst={idx === 0}
                  isLast={idx === sections.length - 1}
                  splitMode={splitMode}
                  onUpdate={handleSectionUpdate}
                  onMove={(dir) => handleMove(section.id, dir)}
                  onOpenHistory={openHistory}
                  onReviewAction={(type) => performReviewAction(section.id, type)}
                  onFlagUnlockSubmit={performFlagOrUnlock}
                  actionState={actionState?.sectionId === section.id ? actionState : null}
                  setActionState={setActionState}
                  actionLoading={actionLoading}
                  onViewAiTransform={section.chunk_id ? () => openTransform(section) : undefined}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      {historyOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-end md:items-center justify-center p-4">
          <div className="bg-white rounded-3xl w-full max-w-md max-h-[80vh] flex flex-col shadow-xl">
            <div className="flex items-center justify-between p-5 border-b border-gray-100">
              <h2 className="font-bold text-base">Version History</h2>
              <button onClick={closeHistory} className="text-[#888888] hover:text-[#222222]">
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {historyLoading && (
                <div className="flex items-center justify-center py-8 text-[#888888] gap-2">
                  <Loader2 size={16} className="animate-spin" /> Loading history…
                </div>
              )}
              {!historyLoading && historyVersions.length === 0 && (
                <p className="text-sm text-center text-[#888888] py-8">No version history available.</p>
              )}
              {historyVersions.map((v) => (
                <div key={v.id} className="border border-gray-100 rounded-2xl p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-[#888888]">
                      Version {v.version_number}
                    </span>
                    <span className="text-xs text-[#aaa]">
                      {new Date(v.created_at).toLocaleString()}
                    </span>
                  </div>
                  <p className="text-sm text-[#222222] whitespace-pre-wrap line-clamp-4 mb-3">
                    {v.content}
                  </p>
                  <button
                    onClick={() => restoreVersion(v)}
                    disabled={!!historyRestoring}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
                  >
                    {historyRestoring === v.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <RotateCcw size={12} />
                    )}
                    Restore
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {transformOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl w-full max-w-6xl max-h-[90vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
              <div className="flex items-center gap-3">
                <Sparkles size={18} className="text-[#6A8776]" />
                <div>
                  <h2 className="font-bold text-base">AI Transform Comparison</h2>
                  <p className="text-xs text-[#888888] mt-0.5">
                    {transformSection?.heading || transformSection?.title || 'Section'}
                  </p>
                </div>
              </div>
              <button onClick={closeTransform} className="text-[#888888] hover:text-[#222222] transition-colors">
                <X size={20} />
              </button>
            </div>

            {transformLoading && (
              <div className="flex-1 flex items-center justify-center gap-2 text-[#888888] text-sm">
                <Loader2 size={16} className="animate-spin" /> Loading transform data…
              </div>
            )}

            {!transformLoading && !transformData && (
              <div className="flex-1 flex items-center justify-center text-sm text-red-500">
                Failed to load transform data for this section.
              </div>
            )}

            {!transformLoading && transformData && (
              <>
                {transformData.transform_stats && (
                  <div className="px-6 py-3 border-b border-gray-50 flex items-center gap-6 text-xs text-[#888888] shrink-0 flex-wrap">
                    <span>Total blocks: <strong className="text-[#222222]">{transformData.transform_stats.total_blocks ?? '—'}</strong></span>
                    <span>Rewritten: <strong className="text-green-700">{transformData.transform_stats.rewritten_blocks ?? '—'}</strong></span>
                    <span>Fallbacks: <strong className="text-amber-600">{transformData.transform_stats.fallback_blocks ?? '—'}</strong></span>
                    <span>Tables preserved: <strong className="text-blue-600">{transformData.transform_stats.table_blocks ?? '—'}</strong></span>
                    {!transformData.has_transform && (
                      <span className="ml-auto text-amber-600 font-medium">No AI transform available for this chunk</span>
                    )}
                  </div>
                )}
                <div className="flex-1 grid grid-cols-2 gap-0 overflow-hidden min-h-0">
                  <div className="flex flex-col border-r border-gray-100 overflow-hidden">
                    <div className="px-5 py-2 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-[#888888] uppercase tracking-wide shrink-0">
                      Cleaned Text (original)
                    </div>
                    <div className="flex-1 overflow-y-auto p-5">
                      <pre className="text-xs text-[#333] whitespace-pre-wrap font-mono leading-relaxed">
                        {transformData.cleaned_text || <span className="text-[#aaa] italic">No cleaned text available</span>}
                      </pre>
                    </div>
                  </div>
                  <div className="flex flex-col overflow-hidden">
                    <div className="px-5 py-2 bg-[#F0F6F2] border-b border-[#d5e6da] text-xs font-semibold text-[#6A8776] uppercase tracking-wide shrink-0 flex items-center gap-1.5">
                      <Sparkles size={11} /> AI Transformed Text
                    </div>
                    <div className="flex-1 overflow-y-auto p-5">
                      {transformData.has_transform ? (
                        <pre className="text-xs text-[#1a1a1a] whitespace-pre-wrap font-mono leading-relaxed">
                          {transformData.transformed_text}
                        </pre>
                      ) : (
                        <div className="flex flex-col items-center justify-center h-full gap-3 text-[#888888]">
                          <Sparkles size={28} className="opacity-30" />
                          <p className="text-sm text-center">No AI transform has been run on this chunk yet.<br/>
                            <span className="text-xs">Re-run the pipeline with AI transform enabled.</span>
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {assembleOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-end md:items-center justify-center p-4">
          <div className="bg-white rounded-3xl w-full max-w-md shadow-xl p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-base">Assemble Draft</h2>
              <button onClick={() => setAssembleOpen(false)} className="text-[#888888] hover:text-[#222222]">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-[#888888]">
              Choose how the draft sections should be assembled into the final manuscript.
            </p>
            <div className="space-y-3">
              {ASSEMBLE_MODES.map((mode) => (
                <button
                  key={mode.key}
                  onClick={() => setAssembleMode(mode.key)}
                  className={`w-full text-left border rounded-2xl p-4 transition-colors ${
                    assembleMode === mode.key
                      ? 'border-[#6A8776] bg-[#F0F6F2]'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-semibold text-sm mb-1">{mode.label}</div>
                  <div className="text-xs text-[#888888]">{mode.description}</div>
                </button>
              ))}
            </div>
            {assembleError && (
              <div className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{assembleError}</div>
            )}
            {assembleSuccess && (
              <div className="text-sm text-green-700 bg-green-50 rounded-xl px-3 py-2">
                Draft assembled successfully!
              </div>
            )}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setAssembleOpen(false)}
                disabled={assembling}
                className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-medium disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAssemble}
                disabled={assembling || assembleSuccess}
                className="px-5 py-2 rounded-xl bg-[#6A8776] text-white text-sm font-medium hover:bg-[#5a7366] disabled:opacity-50 flex items-center gap-2"
              >
                {assembling && <Loader2 size={14} className="animate-spin" />}
                {assembling ? 'Assembling…' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

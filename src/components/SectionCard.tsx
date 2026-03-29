import React, { useCallback, useRef, useState } from 'react';
import {
  ChevronUp,
  ChevronDown,
  Edit2,
  Check,
  X,
  BookOpen,
  SeparatorHorizontal,
  AlignLeft,
  History,
  Lock,
  Flag,
  Unlock,
  CheckCircle,
  Sparkles,
} from 'lucide-react';
import { ManuscriptSection, SectionStatus, BreakType, ReviewStatus, draftApi } from '../lib/api';
import { ActionState } from '../pages/ManuscriptWorkspace';

const STATUS_STYLES: Record<SectionStatus, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  reviewed: 'bg-blue-100 text-blue-800',
  approved: 'bg-green-100 text-green-800',
  locked: 'bg-gray-200 text-gray-600',
};

const STATUS_LABELS: Record<SectionStatus, string> = {
  pending: 'Pending',
  reviewed: 'Reviewed',
  approved: 'Approved',
  locked: 'Locked',
};

function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const base = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium';
  switch (status) {
    case 'PENDING':
      return <span className={`${base} bg-yellow-50 text-yellow-700`}>Awaiting Review</span>;
    case 'REVIEWED':
      return <span className={`${base} bg-orange-50 text-orange-700`}><Flag size={10} /> Flagged</span>;
    case 'APPROVED':
      return <span className={`${base} bg-green-100 text-green-700`}><CheckCircle size={10} /> QA Approved</span>;
    case 'LOCKED':
      return <span className={`${base} bg-gray-200 text-gray-700`}><Lock size={10} /> QA Locked</span>;
    default:
      return null;
  }
}

interface SectionCardProps {
  section: ManuscriptSection;
  isFirst: boolean;
  isLast: boolean;
  splitMode: boolean;
  onUpdate: (updated: ManuscriptSection) => void;
  onMove: (direction: 'up' | 'down') => void;
  onOpenHistory: (sectionId: string) => void;
  onReviewAction: (type: 'approve' | 'lock') => void;
  onFlagUnlockSubmit: (note: string) => void;
  actionState: ActionState | null;
  setActionState: (state: ActionState | null) => void;
  actionLoading: boolean;
  onViewAiTransform?: () => void;
}

function SectionCard({
  section,
  isFirst,
  isLast,
  splitMode,
  onUpdate,
  onMove,
  onOpenHistory,
  onReviewAction,
  onFlagUnlockSubmit,
  actionState,
  setActionState,
  actionLoading,
  onViewAiTransform,
}: SectionCardProps) {
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(section.content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const isLocked = section.status === 'locked';
  const [actionError, setActionError] = useState<string | null>(null);
  const [flagInput, setFlagInput] = useState('');

  const sourceScrollRef = useRef<HTMLDivElement>(null);
  const editedScrollRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  const handleSourceScroll = useCallback(() => {
    if (syncingRef.current || !sourceScrollRef.current || !editedScrollRef.current) return;
    syncingRef.current = true;
    const src = sourceScrollRef.current;
    const tgt = editedScrollRef.current;
    const ratio = src.scrollTop / Math.max(1, src.scrollHeight - src.clientHeight);
    tgt.scrollTop = ratio * Math.max(0, tgt.scrollHeight - tgt.clientHeight);
    requestAnimationFrame(() => { syncingRef.current = false; });
  }, []);

  const handleEditedScroll = useCallback(() => {
    if (syncingRef.current || !sourceScrollRef.current || !editedScrollRef.current) return;
    syncingRef.current = true;
    const src = editedScrollRef.current;
    const tgt = sourceScrollRef.current;
    const ratio = src.scrollTop / Math.max(1, src.scrollHeight - src.clientHeight);
    tgt.scrollTop = ratio * Math.max(0, tgt.scrollHeight - tgt.clientHeight);
    requestAnimationFrame(() => { syncingRef.current = false; });
  }, []);

  const startEdit = () => {
    if (isLocked) return;
    setEditContent(section.content);
    setEditing(true);
    setSaveError(null);
  };

  const cancelEdit = () => {
    setEditing(false);
    setSaveError(null);
  };

  const saveEdit = async () => {
    if (editContent === section.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await draftApi.updateSection(section.id, { content: editContent });
      onUpdate(updated);
      setEditing(false);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async () => {
    if (isLocked) return;
    setActionError(null);
    const nextStatus: SectionStatus = section.status === 'approved' ? 'reviewed' : 'approved';
    try {
      const updated = await draftApi.updateSection(section.id, { status: nextStatus });
      onUpdate(updated);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update status');
    }
  };

  const handleMarkAppendix = async () => {
    if (isLocked) return;
    setActionError(null);
    try {
      const updated = await draftApi.updateSection(section.id, { is_appendix: !section.is_appendix });
      onUpdate(updated);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update appendix flag');
    }
  };

  const handleInsertBreak = async (type: BreakType) => {
    if (isLocked) return;
    setActionError(null);
    const nextBreak: BreakType | null = section.break_before === type ? null : type;
    try {
      const updated = await draftApi.updateSection(section.id, { break_before: nextBreak });
      onUpdate(updated);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update break');
    }
  };

  const isModified =
    section.current_version_number !== undefined && section.current_version_number > 1;

  const reviewStatus = section.review_status;
  const isQALocked = reviewStatus === 'LOCKED';

  return (
    <div id={`section-${section.id}`} className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      {section.break_before === 'chapter' && (
        <div className="bg-[#355846] text-white text-xs font-semibold uppercase tracking-widest px-4 py-1 text-center">
          Chapter Break
        </div>
      )}
      {section.break_before === 'page' && (
        <div className="bg-gray-100 text-gray-500 text-xs font-semibold uppercase tracking-widest px-4 py-1 text-center">
          Page Break
        </div>
      )}

      <div className="p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            {section.heading || section.title ? (
              <h3 className="font-bold text-base truncate text-[#222222]">{section.heading || section.title}</h3>
            ) : (
              <span className="text-sm text-[#888888]">Section {section.position + 1}</span>
            )}
            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_STYLES[section.status]}`}>
              {STATUS_LABELS[section.status]}
            </span>
            {reviewStatus && <ReviewStatusBadge status={reviewStatus} />}
            {section.is_appendix && (
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-700">
                Appendix
              </span>
            )}
            {isModified && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-50 text-orange-600 border border-orange-200">
                Modified from original
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => onMove('up')}
              disabled={isFirst || isLocked}
              className="p-1.5 rounded-lg text-[#888888] hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move Up"
            >
              <ChevronUp size={16} />
            </button>
            <button
              onClick={() => onMove('down')}
              disabled={isLast || isLocked}
              className="p-1.5 rounded-lg text-[#888888] hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move Down"
            >
              <ChevronDown size={16} />
            </button>
          </div>
        </div>

        {section.flag_note && (
          <div className="mb-3 flex items-start gap-1.5 text-xs text-orange-700 bg-orange-50 rounded-xl px-3 py-2">
            <Flag size={11} className="mt-0.5 shrink-0" />
            <span>{section.flag_note}</span>
          </div>
        )}

        {splitMode ? (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[#888888] mb-2">Source</div>
              <div
                ref={sourceScrollRef}
                onScroll={handleSourceScroll}
                className="text-sm text-[#444444] whitespace-pre-wrap bg-[#F8F8F8] rounded-xl p-3 max-h-64 overflow-y-auto"
              >
                {section.source_chunk_text || <span className="italic text-[#aaa]">No source text available</span>}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[#888888] mb-2">Edited</div>
              {editing ? (
                <EditArea
                  content={editContent}
                  onChange={setEditContent}
                  onSave={saveEdit}
                  onCancel={cancelEdit}
                  saving={saving}
                  error={saveError}
                />
              ) : (
                <div
                  ref={editedScrollRef}
                  onScroll={handleEditedScroll}
                  className="text-sm text-[#222222] whitespace-pre-wrap bg-[#FAFDF9] rounded-xl p-3 max-h-64 overflow-y-auto border border-[#E8F0EB]"
                >
                  {section.content}
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            {editing ? (
              <EditArea
                content={editContent}
                onChange={setEditContent}
                onSave={saveEdit}
                onCancel={cancelEdit}
                saving={saving}
                error={saveError}
              />
            ) : (
              <div className="text-sm text-[#222222] whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto">
                {section.content}
              </div>
            )}
          </>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-50 pt-3">
          {!editing && (
            <button
              onClick={startEdit}
              disabled={isLocked}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Edit2 size={12} /> Edit
            </button>
          )}
          <button
            onClick={handleApprove}
            disabled={isLocked}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed ${
              section.status === 'approved'
                ? 'bg-green-100 text-green-700 hover:bg-green-200'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            <Check size={12} /> {section.status === 'approved' ? 'Unapprove' : 'Approve'}
          </button>
          <button
            onClick={handleMarkAppendix}
            disabled={isLocked}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed ${
              section.is_appendix
                ? 'bg-purple-100 text-purple-700 hover:bg-purple-200'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            <BookOpen size={12} /> {section.is_appendix ? 'Remove Appendix' : 'Mark as Appendix'}
          </button>
          <button
            onClick={() => handleInsertBreak('chapter')}
            disabled={isLocked}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed ${
              section.break_before === 'chapter'
                ? 'bg-[#355846] text-white hover:bg-[#2a4538]'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            <SeparatorHorizontal size={12} /> Chapter Break
          </button>
          <button
            onClick={() => handleInsertBreak('page')}
            disabled={isLocked}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed ${
              section.break_before === 'page'
                ? 'bg-gray-600 text-white hover:bg-gray-700'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            <AlignLeft size={12} /> Page Break
          </button>

          <div className="h-4 border-l border-gray-200 mx-1" />

          {(reviewStatus === 'PENDING' || reviewStatus === 'REVIEWED') && (
            <button
              disabled={actionLoading}
              onClick={() => setActionState({ sectionId: section.id, type: 'flag', inputValue: '' })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-50 hover:bg-orange-100 text-orange-700 disabled:opacity-40"
            >
              <Flag size={12} /> Flag
            </button>
          )}
          {reviewStatus !== 'APPROVED' && reviewStatus !== 'LOCKED' && (
            <button
              disabled={actionLoading}
              onClick={() => onReviewAction('approve')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-50 hover:bg-green-100 text-green-700 disabled:opacity-40"
            >
              <CheckCircle size={12} /> QA Approve
            </button>
          )}
          {reviewStatus === 'APPROVED' && (
            <button
              disabled={actionLoading}
              onClick={() => onReviewAction('lock')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 disabled:opacity-40"
            >
              <Lock size={12} /> Lock
            </button>
          )}
          {isQALocked && (
            <button
              disabled={actionLoading}
              onClick={() => setActionState({ sectionId: section.id, type: 'unlock', inputValue: '' })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-50 hover:bg-blue-100 text-blue-700 disabled:opacity-40"
            >
              <Unlock size={12} /> Unlock
            </button>
          )}

          {isLocked && !isQALocked && (
            <span className="flex items-center gap-1 text-xs text-gray-400">
              <Lock size={12} /> Locked
            </span>
          )}
          {onViewAiTransform && (
            <button
              onClick={onViewAiTransform}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[#6A8776] hover:bg-[#E8F0EB]"
              title="Compare cleaned vs AI-transformed text"
            >
              <Sparkles size={12} /> AI Transform
            </button>
          )}
          <button
            onClick={() => onOpenHistory(section.id)}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[#6A8776] hover:bg-[#E8F0EB]"
          >
            <History size={12} /> History
          </button>
        </div>

        {actionState && actionState.sectionId === section.id && (
          <div className="mt-3 bg-gray-50 rounded-xl p-3 space-y-2">
            <div className="text-xs font-semibold text-[#888888] uppercase tracking-wide">
              {actionState.type === 'flag' ? 'Flag note' : 'Unlock reason'}
            </div>
            <textarea
              className="w-full border border-gray-200 rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#6A8776]/40"
              rows={2}
              placeholder={actionState.type === 'flag' ? 'Describe the issue...' : 'Reason for unlocking...'}
              value={flagInput}
              onChange={(e) => setFlagInput(e.target.value)}
              disabled={actionLoading}
            />
            <div className="flex gap-2">
              <button
                onClick={() => onFlagUnlockSubmit(flagInput)}
                disabled={actionLoading}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[#222222] text-white disabled:opacity-50"
              >
                Submit
              </button>
              <button
                onClick={() => { setActionState(null); setFlagInput(''); }}
                disabled={actionLoading}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {actionError && (
          <div className="mt-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-1.5">{actionError}</div>
        )}
      </div>
    </div>
  );
}

function EditArea({
  content,
  onChange,
  onSave,
  onCancel,
  saving,
  error,
}: {
  content: string;
  onChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
}) {
  return (
    <div className="space-y-2">
      <textarea
        className="w-full min-h-[180px] border border-[#6A8776] rounded-xl p-3 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-[#6A8776]/40"
        value={content}
        onChange={(e) => onChange(e.target.value)}
        disabled={saving}
        autoFocus
      />
      {error && <div className="text-xs text-red-600">{error}</div>}
      <div className="flex gap-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#222222] text-white disabled:opacity-50"
        >
          <Check size={12} /> {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
        >
          <X size={12} /> Cancel
        </button>
      </div>
    </div>
  );
}

export default React.memo(SectionCard, (prev, next) => {
  return (
    prev.section === next.section &&
    prev.isFirst === next.isFirst &&
    prev.isLast === next.isLast &&
    prev.splitMode === next.splitMode &&
    prev.actionState === next.actionState &&
    prev.actionLoading === next.actionLoading
  );
});

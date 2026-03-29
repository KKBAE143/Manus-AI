import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, CheckCircle, Flag, Lock, Unlock } from 'lucide-react';
import Header from '../components/Header';
import { api, GlobalReviewQueue, ReviewQueueItem, ReviewStatus } from '../lib/api';

type TabKey = 'awaiting' | 'flagged' | 'approved' | 'locked';

const STATUS_LABELS: Record<ReviewStatus, string> = {
  PENDING: 'Awaiting Review',
  REVIEWED: 'Flagged',
  APPROVED: 'Approved',
  LOCKED: 'Locked',
};

function reviewStatusBadge(status: ReviewStatus) {
  const base = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium';
  switch (status) {
    case 'PENDING':
      return <span className={`${base} bg-yellow-100 text-yellow-700`}>Awaiting Review</span>;
    case 'REVIEWED':
      return <span className={`${base} bg-orange-100 text-orange-700`}><Flag size={11} /> Flagged</span>;
    case 'APPROVED':
      return <span className={`${base} bg-green-100 text-green-700`}><CheckCircle size={11} /> Approved</span>;
    case 'LOCKED':
      return <span className={`${base} bg-gray-200 text-gray-700`}><Lock size={11} /> Locked</span>;
    default:
      return <span className={`${base} bg-gray-100 text-gray-500`}>{status}</span>;
  }
}

interface ActionState {
  sectionId: string;
  type: 'flag' | 'unlock';
  inputValue: string;
}

export default function ReviewQueue() {
  const navigate = useNavigate();
  const [queue, setQueue] = useState<GlobalReviewQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('awaiting');
  const [actionState, setActionState] = useState<ActionState | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const loadQueue = useCallback(async () => {
    try {
      const data = await api.getGlobalReviewQueue();
      setQueue(data);
      setError(null);
    } catch {
      setError('Failed to load review queue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const itemsByTab: Record<TabKey, ReviewQueueItem[]> = {
    awaiting: (queue?.items ?? []).filter((i) => i.review_status === 'PENDING'),
    flagged: (queue?.items ?? []).filter((i) => i.review_status === 'REVIEWED'),
    approved: (queue?.items ?? []).filter((i) => i.review_status === 'APPROVED'),
    locked: (queue?.items ?? []).filter((i) => i.review_status === 'LOCKED'),
  };

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'awaiting', label: 'Awaiting Review', count: itemsByTab.awaiting.length },
    { key: 'flagged', label: 'Flagged', count: itemsByTab.flagged.length },
    { key: 'approved', label: 'Approved', count: itemsByTab.approved.length },
    { key: 'locked', label: 'Locked', count: itemsByTab.locked.length },
  ];

  const handleApprove = async (sectionId: string) => {
    setActionLoading(true);
    try {
      await api.approveSection(sectionId);
      await loadQueue();
    } catch {
      window.alert('Failed to approve section.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleLock = async (sectionId: string) => {
    setActionLoading(true);
    try {
      await api.lockSection(sectionId);
      await loadQueue();
    } catch {
      window.alert('Failed to lock section.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleFlag = async () => {
    if (!actionState || actionState.type !== 'flag') return;
    if (!actionState.inputValue.trim()) {
      window.alert('Please enter a flag note.');
      return;
    }
    setActionLoading(true);
    try {
      await api.flagSection(actionState.sectionId, actionState.inputValue.trim());
      setActionState(null);
      await loadQueue();
    } catch {
      window.alert('Failed to flag section.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleUnlock = async () => {
    if (!actionState || actionState.type !== 'unlock') return;
    if (!actionState.inputValue.trim()) {
      window.alert('Please enter an unlock reason.');
      return;
    }
    setActionLoading(true);
    try {
      await api.unlockSection(actionState.sectionId, actionState.inputValue.trim());
      setActionState(null);
      await loadQueue();
    } catch {
      window.alert('Failed to unlock section.');
    } finally {
      setActionLoading(false);
    }
  };

  const total = queue?.total ?? 0;
  const approved = queue?.approved_count ?? 0;

  if (loading) {
    return <main className="flex-1 flex items-center justify-center text-sm text-[#888888]">Loading review queue...</main>;
  }

  if (error) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{error}</p>
        <button onClick={loadQueue} className="px-4 py-2 rounded-lg bg-[#222222] text-white text-sm">Retry</button>
      </main>
    );
  }

  const currentItems = itemsByTab[activeTab];

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header title="Review Queue" subtitle="Centralized dashboard for reviewing, approving, and locking manuscript sections." />

      <div className="flex-1 overflow-y-auto pb-6 px-6 md:px-0 md:pr-2 space-y-6">
        <div className="bg-white rounded-3xl p-6 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-[#888888] mb-1">Overall approval progress</div>
            <div className="text-2xl font-bold">
              {approved} <span className="text-[#888888] font-normal text-base">/ {total} sections approved</span>
            </div>
          </div>
          {total > 0 && (
            <div className="w-full sm:w-64 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-[#6A8776] rounded-full transition-all"
                style={{ width: `${Math.round((approved / total) * 100)}%` }}
              />
            </div>
          )}
        </div>

        <div className="bg-white rounded-3xl p-6 shadow-sm">
          <div className="flex flex-wrap gap-2 mb-6">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 rounded-xl text-sm font-medium flex items-center gap-2 ${
                  activeTab === tab.key ? 'bg-[#222222] text-white' : 'bg-gray-100 text-[#222222]'
                }`}
              >
                {tab.label}
                <span className={`px-1.5 py-0.5 rounded-full text-xs ${
                  activeTab === tab.key ? 'bg-white/20 text-white' : 'bg-white text-[#888888]'
                }`}>{tab.count}</span>
              </button>
            ))}
          </div>

          {currentItems.length === 0 ? (
            <div className="text-sm text-[#888888] py-8 text-center">
              No sections in this category.
            </div>
          ) : (
            <div className="space-y-3">
              {currentItems.map((item) => (
                <div key={item.id} className="border border-gray-100 rounded-2xl p-4">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="font-semibold text-sm truncate">
                          {item.title || `Section ${item.section_order + 1}`}
                        </span>
                        {reviewStatusBadge(item.review_status)}
                      </div>
                      <div className="text-xs text-[#888888]">
                        {item.document_filename}
                        {item.chunk_index != null && ` • Chunk ${item.chunk_index}`}
                        {item.chunk_stage && ` • Stage: ${item.chunk_stage}`}
                        {` • ${item.section_type} • order ${item.section_order + 1}`}
                      </div>
                      {item.flag_note && (
                        <div className="mt-2 flex items-start gap-1.5 text-xs text-orange-700 bg-orange-50 rounded-xl px-3 py-2">
                          <Flag size={12} className="mt-0.5 shrink-0" />
                          <span>{item.flag_note}</span>
                        </div>
                      )}
                      {item.lock_reason && (
                        <div className="mt-2 flex items-start gap-1.5 text-xs text-gray-600 bg-gray-50 rounded-xl px-3 py-2">
                          <Unlock size={12} className="mt-0.5 shrink-0" />
                          <span>Unlock reason: {item.lock_reason}</span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                      <button
                        onClick={() => navigate(`/workspace/${item.document_id}?sectionId=${item.id}`)}
                        className="px-3 py-1.5 rounded-lg bg-[#E8F0EB] hover:bg-[#dce9e0] text-[#355846] text-xs font-medium"
                      >
                        Review in Workspace
                      </button>
                      <button
                        onClick={() => navigate(`/documents/${item.document_id}`)}
                        className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-xs font-medium"
                      >
                        View Doc
                      </button>

                      {(item.review_status === 'PENDING' || item.review_status === 'REVIEWED') && (
                        <>
                          <button
                            disabled={actionLoading}
                            onClick={() => setActionState({ sectionId: item.id, type: 'flag', inputValue: '' })}
                            className="px-3 py-1.5 rounded-lg bg-orange-50 hover:bg-orange-100 text-orange-700 text-xs font-medium flex items-center gap-1"
                          >
                            <Flag size={12} /> Flag
                          </button>
                          <button
                            disabled={actionLoading}
                            onClick={() => handleApprove(item.id)}
                            className="px-3 py-1.5 rounded-lg bg-[#E8F0EB] hover:bg-[#dce9e0] text-[#355846] text-xs font-medium flex items-center gap-1"
                          >
                            <CheckCircle size={12} /> Approve
                          </button>
                        </>
                      )}

                      {item.review_status === 'APPROVED' && (
                        <>
                          <button
                            disabled={actionLoading}
                            onClick={() => setActionState({ sectionId: item.id, type: 'unlock', inputValue: '' })}
                            className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-xs font-medium flex items-center gap-1"
                          >
                            <Unlock size={12} /> Unlock for Revision
                          </button>
                          <button
                            disabled={actionLoading}
                            onClick={() => handleLock(item.id)}
                            className="px-3 py-1.5 rounded-lg bg-[#222222] text-white text-xs font-medium flex items-center gap-1"
                          >
                            <Lock size={12} /> Lock
                          </button>
                        </>
                      )}

                      {item.review_status === 'LOCKED' && (
                        <button
                          disabled={actionLoading}
                          onClick={() => setActionState({ sectionId: item.id, type: 'unlock', inputValue: '' })}
                          className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-xs font-medium flex items-center gap-1"
                        >
                          <Unlock size={12} /> Unlock for Revision
                        </button>
                      )}
                    </div>
                  </div>

                  {actionState?.sectionId === item.id && (
                    <div className="mt-3 pt-3 border-t border-gray-100 flex flex-col sm:flex-row gap-2">
                      <input
                        autoFocus
                        value={actionState.inputValue}
                        onChange={(e) => setActionState((prev) => prev ? { ...prev, inputValue: e.target.value } : null)}
                        placeholder={actionState.type === 'flag' ? 'Describe the issue...' : 'Reason for unlocking...'}
                        className="flex-1 px-3 py-2 rounded-xl border border-gray-200 text-sm"
                      />
                      <div className="flex gap-2">
                        <button
                          disabled={actionLoading}
                          onClick={actionState.type === 'flag' ? handleFlag : handleUnlock}
                          className="px-4 py-2 rounded-xl bg-[#222222] text-white text-sm font-medium disabled:opacity-50"
                        >
                          {actionLoading ? 'Saving...' : 'Confirm'}
                        </button>
                        <button
                          onClick={() => setActionState(null)}
                          className="px-4 py-2 rounded-xl bg-gray-100 text-sm font-medium"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {total === 0 && (
          <div className="bg-white rounded-3xl p-8 shadow-sm text-center">
            <AlertTriangle size={32} className="mx-auto text-[#888888] mb-3" />
            <p className="text-[#888888] text-sm">No manuscript sections found. Assemble a draft first from a document.</p>
          </div>
        )}
      </div>
    </main>
  );
}

import React, { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Loader2 } from 'lucide-react';

import Header from '../components/Header';
import { usePollingBackoff } from '../hooks/usePollingBackoff';
import BackendUnavailableNotice from '../components/BackendUnavailableNotice';
import DeleteProjectButton from '../components/DeleteProjectButton';
import { api, DocumentSummary, isBackendUnavailableError } from '../lib/api';

const ACTIVE_DOCUMENT_STATUSES = new Set(['QUEUED', 'PROCESSING']);

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string; spin?: boolean }> = {
    MERGE_READY: { label: 'Merge Ready', className: 'bg-green-100 text-green-700' },
    PROCESSING: { label: 'Processing', className: 'bg-blue-100 text-blue-700', spin: true },
    QUEUED: { label: 'Queued', className: 'bg-yellow-100 text-yellow-700' },
    FAILED: { label: 'Failed', className: 'bg-red-100 text-red-700' },
    UPLOADED: { label: 'Uploaded', className: 'bg-gray-100 text-gray-600' },
    ARCHIVED: { label: 'Archived', className: 'bg-gray-100 text-gray-500' },
  };
  const entry = map[status];
  if (!entry) return <span className="text-sm text-[#666666]">{status}</span>;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${entry.className}`}>
      {entry.spin && <Loader2 size={10} className="animate-spin" />}
      {entry.label}
    </span>
  );
}

export default function Documents() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const [total, setTotal] = useState(0);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const deferredQuery = useDeferredValue(query.trim());

  const hasActiveJobs = useMemo(
    () => documents.some((item) => ACTIVE_DOCUMENT_STATUSES.has((item.status || '').toUpperCase())),
    [documents],
  );

  useEffect(() => {
    setPage(0);
  }, [statusFilter, deferredQuery]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await api.listDocuments({ status: statusFilter, q: deferredQuery, offset: page * pageSize, limit: pageSize });
        if (active) {
          setDocuments(data.items);
          setTotal(data.total);
          setBackendUnavailable(false);
        }
      } catch (error) {
        if (active && isBackendUnavailableError(error)) {
          setBackendUnavailable(true);
          setDocuments([]);
          setTotal(0);
        } else {
          console.error('Failed to fetch documents', error);
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    load();

    return () => {
      active = false;
    };
  }, [backendUnavailable, deferredQuery, hasActiveJobs, page, statusFilter]);

  usePollingBackoff({
    enabled: !backendUnavailable && !deferredQuery && hasActiveJobs,
    onPoll: useCallback(async () => {
      const data = await api.listDocuments({
        status: statusFilter,
        q: deferredQuery,
        offset: page * pageSize,
        limit: pageSize,
      });
      setDocuments(data.items);
      setTotal(data.total);
    }, [deferredQuery, page, pageSize, statusFilter]),
    minInterval: 4000,
    maxInterval: 60000,
  });

  const refreshDocuments = async () => {
    try {
      const data = await api.listDocuments({ status: statusFilter, q: deferredQuery, offset: page * pageSize, limit: pageSize });
      setDocuments(data.items);
      setTotal(data.total);
      setBackendUnavailable(false);
    } catch (error) {
      if (isBackendUnavailableError(error)) {
        setBackendUnavailable(true);
        setDocuments([]);
        setTotal(0);
        return;
      }
      console.error('Failed to refresh documents', error);
    }
  };

  const visibleDocuments = documents;
  const pagedDocuments = documents;

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header title="Projects" subtitle="All uploaded PDFs, pipeline runs, and generated manuscript parts." />

      <div className="flex-1 overflow-y-auto pb-6 px-6 md:px-0 md:pr-2">
        <div className="bg-white rounded-3xl p-8 shadow-sm min-h-full">
          {backendUnavailable && <div className="mb-6"><BackendUnavailableNotice apiBaseUrl={api.baseUrl} /></div>}

          <div className="flex flex-col md:flex-row gap-3 mb-6">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search filename..."
              className="px-4 py-3 rounded-xl border border-gray-200 flex-1"
            />
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="px-4 py-3 rounded-xl border border-gray-200 bg-white">
              <option value="ALL">All statuses</option>
              <option value="UPLOADED">Uploaded</option>
              <option value="QUEUED">Queued</option>
              <option value="PROCESSING">Processing</option>
              <option value="MERGE_READY">Merge Ready</option>
              <option value="FAILED">Failed</option>
              <option value="ARCHIVED">Archived</option>
            </select>
          </div>

          {loading ? (
            <div className="text-sm text-[#888888]">Loading projects...</div>
          ) : visibleDocuments.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="w-16 h-16 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center mb-4">
                <FileText size={32} />
              </div>
              <h2 className="text-xl font-bold mb-2">No projects yet</h2>
              <p className="text-sm text-[#888888]">Upload a PDF to create your first manuscript processing project.</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-gray-100 text-sm text-[#888888]">
                    <th className="pb-4 font-medium">Filename</th>
                    <th className="pb-4 font-medium">Pages</th>
                    <th className="pb-4 font-medium">Status</th>
                    <th className="pb-4 font-medium">Latest Stage</th>
                    <th className="pb-4 font-medium">Parts</th>
                    <th className="pb-4 font-medium">Updated</th>
                    <th className="pb-4 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedDocuments.map((document) => (
                    <tr key={document.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="py-4 font-semibold text-[#222222]">{document.filename}</td>
                      <td className="py-4 text-sm text-[#666666]">{document.page_count || 0}</td>
                      <td className="py-4 text-sm"><StatusBadge status={document.status} /></td>
                      <td className="py-4 text-sm text-[#666666]">{document.latest_job?.stage_name || 'Waiting'}</td>
                      <td className="py-4 text-sm text-[#666666]">{document.part_count}</td>
                      <td className="py-4 text-sm text-[#666666]">{formatDate(document.updated_at)}</td>
                      <td className="py-4 text-sm text-right">
                        <div className="flex justify-end gap-2">
                          <button
                            onClick={() => navigate(`/documents/${document.id}`)}
                            className="px-3 py-2 rounded-lg bg-gray-100 hover:bg-gray-200 font-medium"
                          >
                            Open
                          </button>
                          <DeleteProjectButton documentId={document.id} onDeleted={refreshDocuments} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              <div className="mt-6 flex items-center justify-between text-sm">
                <div className="text-[#888888]">Showing {pagedDocuments.length} of {total} filtered projects</div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                    disabled={page === 0}
                    className="px-3 py-2 rounded-lg border border-gray-200 disabled:opacity-50"
                  >
                    Prev
                  </button>
                  <button
                    onClick={() => setPage((current) => ((current + 1) * pageSize < total ? current + 1 : current))}
                    disabled={(page + 1) * pageSize >= total}
                    className="px-3 py-2 rounded-lg border border-gray-200 disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

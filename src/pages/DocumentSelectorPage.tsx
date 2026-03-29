import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, Library, Wrench, FileText, ArrowRight, Loader2 } from 'lucide-react';
import Header from '../components/Header';
import { api, DocumentSummary } from '../lib/api';

type Destination = 'workspace' | 'assembly' | 'publishing';

const DESTINATION_META: Record<Destination, { icon: React.ElementType; label: string; description: string; color: string }> = {
  workspace: {
    icon: BookOpen,
    label: 'Manuscript Workspace',
    description: 'Inspect, edit, and approve cleaned manuscript sections before export.',
    color: 'bg-blue-50 text-blue-600',
  },
  assembly: {
    icon: Library,
    label: 'Final Assembly',
    description: 'Reorder sections, include/exclude appendix, and generate the final manuscript.',
    color: 'bg-green-50 text-green-600',
  },
  publishing: {
    icon: Wrench,
    label: 'Publishing Tools',
    description: 'Set title page, front matter, TOC, page layout, and export your manuscript.',
    color: 'bg-purple-50 text-purple-600',
  },
};

const READY_STATUSES = new Set(['MERGE_READY', 'MERGED', 'merge_ready', 'merged', 'PROCESSING', 'processing', 'COMPLETED', 'completed']);

function destinationUrl(dest: Destination, docId: string): string {
  if (dest === 'workspace') return `/workspace/${docId}`;
  if (dest === 'assembly') return `/assembly/${docId}`;
  return `/publishing/${docId}`;
}

interface Props {
  destination: Destination;
}

export default function DocumentSelectorPage({ destination }: Props) {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const meta = DESTINATION_META[destination];
  const Icon = meta.icon;

  useEffect(() => {
    const lastId = localStorage.getItem('lastWorkspaceDocId');
    if (lastId) {
      navigate(destinationUrl(destination, lastId), { replace: true });
      return;
    }
    api.listDocuments({ limit: 100, offset: 0 })
      .then((res) => {
        const eligible = res.items.filter((d) => {
          const s = (d.status || '').toString().toUpperCase();
          return READY_STATUSES.has(s);
        });
        setDocuments(eligible);
      })
      .catch(() => setError('Could not load documents.'))
      .finally(() => setLoading(false));
  }, [destination, navigate]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <Header title={meta.label} subtitle={meta.description} />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto">
          <div className={`rounded-2xl p-5 flex items-center gap-4 mb-8 ${meta.color}`}>
            <Icon size={28} />
            <div>
              <p className="font-semibold text-base">{meta.label}</p>
              <p className="text-sm opacity-80">{meta.description}</p>
            </div>
          </div>

          <h2 className="text-sm font-semibold text-[#888888] uppercase tracking-wider mb-3">
            Select a project to open
          </h2>

          {loading && (
            <div className="flex items-center gap-3 text-[#888888] py-8">
              <Loader2 size={18} className="animate-spin" />
              <span>Loading projects...</span>
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-50 text-red-600 rounded-xl text-sm">{error}</div>
          )}

          {!loading && !error && documents.length === 0 && (
            <div className="bg-white rounded-2xl p-8 text-center shadow-sm">
              <FileText size={36} className="mx-auto text-[#888888] mb-3" />
              <p className="font-medium text-[#222222] mb-1">No processed documents yet</p>
              <p className="text-sm text-[#888888] mb-5">
                Upload a PDF and run the pipeline first, then come back here.
              </p>
              <button
                onClick={() => navigate('/upload')}
                className="bg-[#222222] text-white rounded-xl px-5 py-2.5 text-sm font-medium hover:bg-[#333]"
              >
                Upload a PDF
              </button>
            </div>
          )}

          {!loading && documents.length > 0 && (
            <div className="flex flex-col gap-3">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => {
                    localStorage.setItem('lastWorkspaceDocId', doc.id);
                    navigate(destinationUrl(destination, doc.id));
                  }}
                  className="bg-white rounded-2xl px-5 py-4 shadow-sm text-left flex items-center gap-4 hover:shadow-md transition-shadow group"
                >
                  <div className="w-10 h-10 rounded-xl bg-[#E8F0EB] text-[#6A8776] flex items-center justify-center shrink-0">
                    <FileText size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-[#222222] truncate">{doc.filename}</p>
                    <p className="text-xs text-[#888888] mt-0.5">
                      {doc.page_count ? `${doc.page_count} pages · ` : ''}
                      Status: {doc.status}
                    </p>
                  </div>
                  <ArrowRight size={18} className="text-[#888888] group-hover:text-[#222222] transition-colors shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

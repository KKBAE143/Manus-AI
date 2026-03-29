import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronLeft, Download, Eye, Search } from 'lucide-react';

import Header from '../components/Header';
import { absoluteUrl, api, DocumentDetail } from '../lib/api';

type PreviewResponse = {
  lines: string[];
  total: number;
};

function normalizePreviewLines(lines: string[]) {
  return lines
    .join('\n')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function classifyLine(line: string) {
  if (/^cleaned manuscript part/i.test(line)) return 'kicker';
  if (/^\[source page \d+\]$/i.test(line)) return 'marker';
  if (/^(chapter|section|disorder)\b/i.test(line)) return 'heading';
  if (/^\d+[.)-]/.test(line)) return 'subheading';
  if (line.length < 90 && /^[A-Z0-9 :&(),.'"\-]+$/.test(line)) return 'heading';
  return 'paragraph';
}

export default function DocumentPreview() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [preview, setPreview] = useState<PreviewResponse>({ lines: [], total: 0 });
  const [loading, setLoading] = useState(true);

  const partId = searchParams.get('partId') || '';

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      const data = await api.getDocument(id);
      setDocument(data);
      const resolvedPartId = partId || data.parts[0]?.id || '';
      if (resolvedPartId) {
        const response = await fetch(`${api.baseUrl}/api/v1/documents/parts/${resolvedPartId}/preview?q=${encodeURIComponent(query)}&limit=5000`);
        const previewData = await response.json();
        setPreview(previewData);
        if (!partId && data.parts[0]?.id) {
          setSearchParams((current) => {
            current.set('partId', data.parts[0].id);
            return current;
          });
        }
      }
      setLoading(false);
    };
    load().catch((error) => {
      console.error(error);
      setLoading(false);
    });
  }, [id, partId, query, setSearchParams]);

  const activePart = useMemo(() => document?.parts.find((part) => part.id === partId) || document?.parts[0] || null, [document, partId]);
  const blocks = useMemo(() => normalizePreviewLines(preview.lines), [preview.lines]);

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden bg-[#F4F2EC]">
      <Header title={document?.filename || 'Preview'} subtitle="Dedicated manuscript reader with formatting-focused preview." />

      <div className="flex-1 overflow-hidden px-6 md:px-0 md:pr-2 pb-6 grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-6">
        <aside className="bg-white rounded-3xl p-6 shadow-sm overflow-y-auto">
          <button onClick={() => navigate(`/documents/${id}`)} className="inline-flex items-center gap-2 text-sm font-medium text-[#6A8776] mb-6">
            <ChevronLeft size={16} /> Back to project
          </button>
          <div className="space-y-2">
            {document?.parts.map((part) => (
              <button
                key={part.id}
                onClick={() => setSearchParams({ partId: part.id, q: query })}
                className={`w-full text-left rounded-2xl px-4 py-3 transition-colors ${activePart?.id === part.id ? 'bg-[#222222] text-white' : 'bg-[#F8F8F8] hover:bg-[#EFEDE6]'}`}
              >
                <div className="font-semibold">Part {part.part_number}</div>
                <div className={`text-xs mt-1 ${activePart?.id === part.id ? 'text-white/70' : 'text-[#888888]'}`}>
                  Pages {part.page_start ?? '?'} - {part.page_end ?? '?'}
                </div>
              </button>
            ))}
          </div>
        </aside>

        <section className="flex flex-col gap-4 overflow-hidden">
          <div className="bg-white rounded-3xl p-5 shadow-sm flex flex-col lg:flex-row gap-4 lg:items-center lg:justify-between">
            <div>
              <div className="text-sm text-[#888888]">Previewing</div>
              <div className="text-2xl font-bold">{activePart?.filename || 'No part selected'}</div>
            </div>
            <div className="flex flex-wrap gap-3 items-center">
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#888888]" />
                <input
                  value={query}
                  onChange={(event) => {
                    const next = event.target.value;
                    setQuery(next);
                    setSearchParams((current) => {
                      if (activePart?.id) current.set('partId', activePart.id);
                      if (next) current.set('q', next);
                      else current.delete('q');
                      return current;
                    });
                  }}
                  placeholder="Search in part..."
                  className="pl-9 pr-4 py-2 rounded-xl border border-gray-200 min-w-[240px]"
                />
              </div>
              {activePart && (
                <a href={absoluteUrl(activePart.download_url)} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#222222] text-white font-medium">
                  <Download size={16} /> Download DOCX
                </a>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-[#DDD7CC] rounded-3xl p-6 shadow-inner">
            {loading ? (
              <div className="bg-white rounded-[28px] shadow-sm mx-auto max-w-4xl min-h-[70vh] flex items-center justify-center text-sm text-[#888888]">
                Loading preview...
              </div>
            ) : (
              <div className="bg-white rounded-[28px] shadow-sm mx-auto max-w-4xl min-h-[70vh] px-12 py-14">
                <div className="flex items-center justify-between mb-10 border-b border-[#EFEDE6] pb-6">
                  <div>
                    <div className="text-xs uppercase tracking-[0.25em] text-[#8C8478] mb-2">Manuscript Preview</div>
                    <h1 className="text-4xl font-semibold text-[#1E1A17]">{document?.config?.book_title || document?.filename}</h1>
                  </div>
                  <div className="text-sm text-[#8C8478] inline-flex items-center gap-2">
                    <Eye size={16} /> {preview.total} lines
                  </div>
                </div>

                <article className="space-y-6 text-[#222222] leading-8">
                  {blocks.map((line, index) => {
                    const kind = classifyLine(line);
                    if (kind === 'marker') {
                      return <div key={`${index}-${line}`} className="text-xs uppercase tracking-[0.18em] text-[#9A9388]">{line}</div>;
                    }
                    if (kind === 'kicker') {
                      return <div key={`${index}-${line}`} className="text-sm uppercase tracking-[0.2em] text-[#8C8478]">{line}</div>;
                    }
                    if (kind === 'heading') {
                      return <h2 key={`${index}-${line}`} className="text-3xl font-semibold mt-12 first:mt-0">{line}</h2>;
                    }
                    if (kind === 'subheading') {
                      return <h3 key={`${index}-${line}`} className="text-xl font-semibold mt-8">{line}</h3>;
                    }
                    return <p key={`${index}-${line}`} className="text-[1.05rem] leading-8 text-[#2A2520]">{line}</p>;
                  })}
                </article>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

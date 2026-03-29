import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Maximize2,
  Minimize2,
  List,
  X,
} from 'lucide-react';
import Header from '../components/Header';
import { api, draftApi, ManuscriptDraft, ManuscriptSection } from '../lib/api';

interface Chapter {
  index: number;
  title: string;
  sectionId: string;
}

export default function BookPreview() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [document, setDocument] = useState<{ filename: string } | null>(null);
  const [draft, setDraft] = useState<ManuscriptDraft | null>(null);
  const [sections, setSections] = useState<ManuscriptSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [currentPage, setCurrentPage] = useState(0);
  const [printMode, setPrintMode] = useState(false);
  const [tocOpen, setTocOpen] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [docData, draftData] = await Promise.all([
        api.getDocument(id),
        draftApi.ensureDraft(id),
      ]);
      setDocument({ filename: docData.filename });
      setDraft(draftData);
      const sectionData = await draftApi.getSections(draftData.id);
      setSections(sectionData);
    } catch (err: unknown) {
      let msg = err instanceof Error ? err.message : 'Failed to load preview';
      try { const parsed = JSON.parse(msg); if (parsed.detail) msg = parsed.detail; } catch {}
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const chapters: Chapter[] = sections.map((s, idx) => ({
    index: idx,
    title: s.heading || s.title || `Section ${idx + 1}`,
    sectionId: s.id,
  }));

  const currentSection = sections[currentPage] || null;
  const content = currentSection?.current_content || currentSection?.content || currentSection?.source_chunk_text || '';

  const goTo = (idx: number) => {
    setCurrentPage(Math.max(0, Math.min(idx, sections.length - 1)));
  };

  const renderContent = (text: string) => {
    if (!text) return <p className="text-[#888888] italic">No content available.</p>;
    const paragraphs = text.split('\n').filter(line => line.trim() !== '');
    return paragraphs.map((line, i) => {
      const trimmed = line.trim();
      const isHeading =
        /^={3,}/.test(trimmed) ||
        /^(CHAPTER|PART|SECTION)\s/i.test(trimmed) ||
        (trimmed.length < 80 && trimmed === trimmed.toUpperCase() && trimmed.length > 3);

      if (/^={3,}/.test(trimmed) || /^-{3,}/.test(trimmed)) {
        return <hr key={i} className="my-4 border-gray-200" />;
      }
      if (isHeading) {
        return (
          <h2 key={i} className="font-bold text-lg mt-6 mb-2 text-[#222222]">
            {trimmed}
          </h2>
        );
      }
      return (
        <p key={i} className="mb-3 text-[#333333] leading-relaxed">
          {trimmed}
        </p>
      );
    });
  };

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center text-sm text-[#888888] gap-2">
        <Loader2 size={16} className="animate-spin" /> Loading preview…
      </main>
    );
  }

  if (error || !draft) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{error || 'Draft not found.'}</p>
        <button
          onClick={() => navigate(`/workspace/${id}`)}
          className="px-4 py-2 rounded-xl bg-[#222222] text-white text-sm"
        >
          Back to Workspace
        </button>
      </main>
    );
  }

  if (printMode) {
    return (
      <div className="fixed inset-0 bg-gray-400 flex flex-col items-center overflow-auto z-50 p-8">
        <div className="flex items-center gap-4 mb-6">
          <button
            onClick={() => setPrintMode(false)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-[#222222] text-sm font-medium shadow"
          >
            <Minimize2 size={14} /> Exit Print Preview
          </button>
          <div className="text-white text-sm">
            Page {currentPage + 1} of {sections.length}
          </div>
        </div>
        <div
          className="bg-white shadow-2xl"
          style={{
            width: '21cm',
            minHeight: '29.7cm',
            padding: '2.54cm',
            fontFamily: 'Georgia, serif',
            fontSize: '11pt',
            lineHeight: '1.6',
          }}
        >
          {renderContent(content)}
        </div>
        <div className="flex gap-4 mt-6">
          <button
            onClick={() => goTo(currentPage - 1)}
            disabled={currentPage === 0}
            className="px-4 py-2 rounded-xl bg-white text-sm shadow disabled:opacity-40"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={() => goTo(currentPage + 1)}
            disabled={currentPage >= sections.length - 1}
            className="px-4 py-2 rounded-xl bg-white text-sm shadow disabled:opacity-40"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={document?.filename || 'Book Preview'}
        subtitle="Visual preview of your assembled manuscript."
      />

      <div className="bg-white border-b border-gray-100 px-4 py-3 flex items-center gap-3 flex-wrap shrink-0">
        <button
          onClick={() => navigate(`/workspace/${id}`)}
          className="flex items-center gap-1.5 text-sm text-[#888888] hover:text-[#222222]"
        >
          <ArrowLeft size={15} /> Workspace
        </button>
        <div className="h-5 w-px bg-gray-200" />
        <span className="text-sm text-[#888888]">
          Page {currentPage + 1} of {sections.length}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setTocOpen((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium transition-colors ${
              tocOpen ? 'bg-[#222222] text-white' : 'bg-gray-100 hover:bg-gray-200 text-[#222222]'
            }`}
          >
            <List size={14} /> TOC
          </button>
          <button
            onClick={() => setPrintMode(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#6A8776] text-white text-sm font-medium hover:bg-[#5a7366]"
          >
            <Maximize2 size={14} /> Print Preview
          </button>
          <button
            onClick={() => navigate(`/assembly/${id}`)}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-[#222222] text-white text-sm font-medium hover:bg-[#333]"
          >
            <BookOpen size={14} /> Final Assembly
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {tocOpen && (
          <aside className="w-56 shrink-0 bg-white border-r border-gray-100 flex flex-col overflow-y-auto p-4 gap-1">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#888888]">
                Table of Contents
              </span>
              <button onClick={() => setTocOpen(false)} className="p-1 rounded-lg hover:bg-gray-100">
                <X size={14} className="text-[#888888]" />
              </button>
            </div>
            {chapters.map((ch) => (
              <button
                key={ch.sectionId}
                onClick={() => goTo(ch.index)}
                className={`text-left px-3 py-2 rounded-xl text-sm transition-colors ${
                  currentPage === ch.index
                    ? 'bg-[#E8F0EB] text-[#355846] font-medium'
                    : 'hover:bg-gray-50 text-[#444444]'
                }`}
              >
                <span className="text-[#aaa] text-xs mr-1">{ch.index + 1}.</span>
                {ch.title}
              </button>
            ))}
          </aside>
        )}

        <div className="flex-1 bg-[#E8E8E8] flex flex-col items-center overflow-y-auto py-8 px-4">
          <div
            className="bg-white shadow-xl rounded-sm w-full max-w-2xl"
            style={{
              minHeight: '29.7cm',
              padding: '2.54cm',
              fontFamily: 'Georgia, serif',
              fontSize: '11pt',
              lineHeight: '1.6',
            }}
          >
            {currentSection && (
              <div className="mb-6 pb-4 border-b border-gray-100">
                <div className="text-xs text-[#aaa] uppercase tracking-wide">
                  {currentSection.section_type || 'Section'} • Page {currentPage + 1}
                </div>
              </div>
            )}
            {renderContent(content)}
          </div>

          <div className="flex items-center gap-4 mt-6">
            <button
              onClick={() => goTo(currentPage - 1)}
              disabled={currentPage === 0}
              className="flex items-center gap-1 px-4 py-2 rounded-xl bg-white shadow text-sm font-medium disabled:opacity-40 hover:bg-gray-50"
            >
              <ChevronLeft size={16} /> Prev
            </button>
            <div className="flex gap-1">
              {sections.slice(Math.max(0, currentPage - 2), currentPage + 3).map((_, relIdx) => {
                const absIdx = Math.max(0, currentPage - 2) + relIdx;
                return (
                  <button
                    key={absIdx}
                    onClick={() => goTo(absIdx)}
                    className={`w-8 h-8 rounded-lg text-xs font-medium transition-colors ${
                      absIdx === currentPage
                        ? 'bg-[#222222] text-white'
                        : 'bg-white shadow hover:bg-gray-50 text-[#444444]'
                    }`}
                  >
                    {absIdx + 1}
                  </button>
                );
              })}
            </div>
            <button
              onClick={() => goTo(currentPage + 1)}
              disabled={currentPage >= sections.length - 1}
              className="flex items-center gap-1 px-4 py-2 rounded-xl bg-white shadow text-sm font-medium disabled:opacity-40 hover:bg-gray-50"
            >
              Next <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

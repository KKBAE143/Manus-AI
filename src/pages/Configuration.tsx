import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Info, Loader2, ChevronRight, ChevronDown, ChevronUp } from 'lucide-react';

import BackendUnavailableNotice from '../components/BackendUnavailableNotice';
import Header from '../components/Header';
import { api, DocumentDetail, isBackendUnavailableError } from '../lib/api';

function FieldHint({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span className="relative inline-flex ml-1.5 align-middle">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onFocus={() => setShow(true)}
        onBlur={() => setShow(false)}
        className="text-[#aaa] hover:text-[#6A8776] transition-colors"
        tabIndex={-1}
        aria-label="More information"
      >
        <Info size={14} />
      </button>
      {show && (
        <span className="absolute z-50 bottom-6 left-1/2 -translate-x-1/2 w-56 bg-[#222] text-white text-xs rounded-xl px-3 py-2 shadow-lg leading-relaxed pointer-events-none">
          {text}
        </span>
      )}
    </span>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 group text-left"
    >
      <span
        className={`relative inline-flex w-10 h-6 rounded-full transition-colors duration-200 shrink-0 ${
          checked ? 'bg-[#6A8776]' : 'bg-gray-200'
        }`}
      >
        <span
          className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </span>
      <span className="text-sm text-[#444] group-hover:text-[#222]">{label}</span>
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <h3 className="text-xs font-semibold text-[#888] uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  );
}

export default function Configuration() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Array<{ id: string; filename: string }>>([]);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [cloneSource, setCloneSource] = useState('');
  const [chapterBoundaries, setChapterBoundaries] = useState<Array<{ page: number; title: string; confidence: number }> | null>(null);
  const [chapterPreviewLoading, setChapterPreviewLoading] = useState(false);
  const [chapterPreviewOpen, setChapterPreviewOpen] = useState(false);
  const [config, setConfig] = useState({
    book_title: '',
    split_mode: 'pages',
    pages_per_docx: 200,
    start_page: 1,
    end_page: 10000,
    keep_page_markers: true,
    generate_appendix_reference: true,
  });

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      try {
        const [data, allDocs] = await Promise.all([
          api.getDocument(id),
          api.listDocuments({ limit: 200, offset: 0 }),
        ]);
        setDocument(data);
        setBackendUnavailable(false);
        setDocuments(allDocs.items.filter((item) => item.id !== id).map((item) => ({ id: item.id, filename: item.filename })));
        setConfig({
          book_title: data.config?.book_title || data.filename.replace(/\.pdf$/i, ''),
          split_mode: data.config?.split_mode || 'pages',
          pages_per_docx: data.config?.pages_per_docx || 200,
          start_page: data.config?.start_page || 1,
          end_page: data.config?.end_page || Math.max(1, data.page_count || 1),
          keep_page_markers: data.config?.keep_page_markers ?? true,
          generate_appendix_reference: data.config?.generate_appendix_reference ?? true,
        });
      } catch (loadError) {
        if (isBackendUnavailableError(loadError)) {
          setBackendUnavailable(true);
          setError('Could not reach the server. Please try again in a moment.');
        } else {
          console.error(loadError);
          setError('Failed to load project settings.');
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  const handleClone = async () => {
    if (!cloneSource || !id) return;
    try {
      await api.cloneConfig(id, cloneSource);
      const data = await api.getDocument(id);
      setDocument(data);
      if (data.config) {
        setConfig({
          book_title: data.config.book_title,
          split_mode: data.config.split_mode,
          pages_per_docx: data.config.pages_per_docx,
          start_page: data.config.start_page,
          end_page: data.config.end_page,
          keep_page_markers: data.config.keep_page_markers,
          generate_appendix_reference: data.config.generate_appendix_reference,
        });
      }
    } catch (cloneError) {
      console.error(cloneError);
      setError('Failed to copy settings from the selected project.');
    }
  };

  const handleSubmit = async () => {
    if (!id) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.processDocument(id, config);
      setBackendUnavailable(false);
      navigate(`/documents/${id}?jobId=${result.job_id}`);
    } catch (submitError) {
      if (isBackendUnavailableError(submitError)) {
        setBackendUnavailable(true);
        setError('Could not start processing — server is unavailable.');
      } else {
        console.error(submitError);
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setSaving(false);
    }
  };

  const isProcessing = document?.latest_job?.status === 'IN_PROGRESS';
  const isChapterMode = config.split_mode === 'chapters' || config.split_mode === 'hybrid';

  const handlePreviewChapters = async () => {
    if (!id) return;
    setChapterPreviewLoading(true);
    setChapterBoundaries(null);
    try {
      const result = await api.previewChapters(id);
      setChapterBoundaries(result.boundaries);
      setChapterPreviewOpen(true);
    } catch (previewError) {
      console.error(previewError);
      setError('Could not detect chapters. Make sure the document has been uploaded.');
    } finally {
      setChapterPreviewLoading(false);
    }
  };

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header title="Processing Setup" subtitle="Tell us how to split and clean your PDF into manuscript files." />

      <div className="flex-1 overflow-y-auto pb-8 px-6 md:px-0 md:pr-2">
        <div className="max-w-2xl space-y-5">

          {backendUnavailable && <BackendUnavailableNotice apiBaseUrl={api.baseUrl} />}

          {loading ? (
            <div className="bg-white rounded-3xl p-8 shadow-sm flex items-center gap-3 text-sm text-[#888]">
              <Loader2 size={16} className="animate-spin" />
              Loading your project settings…
            </div>
          ) : (
            <>
              {/* File info banner */}
              <div className="bg-white rounded-3xl px-6 py-5 shadow-sm flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-[#E8F0EB] text-[#6A8776] flex items-center justify-center shrink-0">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div>
                  <p className="font-semibold text-[#222]">{document?.filename}</p>
                  <p className="text-xs text-[#888] mt-0.5">
                    {document?.page_count?.toLocaleString()} pages detected
                  </p>
                </div>
              </div>

              {error && (
                <div className="px-4 py-3 rounded-2xl bg-red-50 border border-red-100 text-sm text-red-700">
                  {error}
                </div>
              )}

              {isProcessing && (
                <div className="px-4 py-3 rounded-2xl bg-blue-50 border border-blue-100 text-sm text-blue-700 flex items-center justify-between">
                  <span>This document is already being processed.</span>
                  <button onClick={() => navigate(`/documents/${id}`)} className="ml-4 underline font-medium hover:text-blue-900">
                    View Progress →
                  </button>
                </div>
              )}

              {/* Main settings card */}
              <div className="bg-white rounded-3xl p-6 shadow-sm space-y-7">

                <Section title="Manuscript identity">
                  <div>
                    <label className="block text-sm font-medium text-[#333] mb-1.5">
                      Manuscript title
                    </label>
                    <input
                      value={config.book_title}
                      onChange={(e) => setConfig((prev) => ({ ...prev, book_title: e.target.value }))}
                      placeholder="e.g. Clinical Nutrition Handbook"
                      className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                    />
                    <p className="text-xs text-[#888] mt-1.5">This title appears on the cover page of your exported manuscript.</p>
                  </div>
                </Section>

                <div className="border-t border-gray-100" />

                <Section title="How to split your document">
                  <div>
                    <label className="block text-sm font-medium text-[#333] mb-1.5">
                      Split method
                      <FieldHint text="Choose how the pipeline divides your PDF into output files. 'By page count' is the safest choice for most documents." />
                    </label>
                    <select
                      value={config.split_mode}
                      onChange={(e) => setConfig((prev) => ({ ...prev, split_mode: e.target.value }))}
                      className="w-full px-4 py-2.5 rounded-xl border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                    >
                      <option value="pages">By page count — split every N pages</option>
                      <option value="hybrid">Hybrid — page count with chapter awareness</option>
                      <option value="chapters">By chapters — split at detected chapter headings</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-[#333] mb-1.5">
                      {isChapterMode ? 'Max pages per output file' : 'Pages per output file'}
                      <FieldHint text={
                        isChapterMode
                          ? 'In chapter mode this is the maximum size for a single output file. The pipeline tries to keep full chapters together and only splits if a chapter exceeds this limit.'
                          : 'Each DOCX file will contain this many source pages. 150–250 is recommended. Smaller numbers = more files but faster processing per chunk.'
                      } />
                    </label>
                    <div className="flex items-center gap-3">
                      <input
                        type="number"
                        min={25}
                        max={1000}
                        value={config.pages_per_docx}
                        onChange={(e) => setConfig((prev) => ({ ...prev, pages_per_docx: Number(e.target.value) || 200 }))}
                        className="w-32 px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                      />
                      <span className="text-sm text-[#888]">pages per file</span>
                    </div>
                    <p className="text-xs text-[#888] mt-1.5">
                      {isChapterMode
                        ? 'Chapters will be grouped together up to this page limit. The estimated file count depends on the chapters detected in your PDF.'
                        : <>Your {document?.page_count?.toLocaleString()} page document will produce approximately{' '}
                          <strong>{Math.ceil((config.end_page - config.start_page + 1) / config.pages_per_docx)}</strong> output files.</>
                      }
                    </p>
                  </div>

                  {isChapterMode && (
                    <div>
                      <button
                        type="button"
                        onClick={handlePreviewChapters}
                        disabled={chapterPreviewLoading}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-[#6A8776] text-[#6A8776] text-sm font-medium hover:bg-[#E8F0EB] disabled:opacity-50"
                      >
                        {chapterPreviewLoading ? (
                          <><Loader2 size={14} className="animate-spin" /> Scanning for chapters…</>
                        ) : (
                          <>Preview detected chapters</>
                        )}
                      </button>

                      {chapterBoundaries !== null && (() => {
                        const totalPages = config.end_page - config.start_page + 1;
                        let estimatedFiles: number;
                        if (chapterBoundaries.length === 0) {
                          estimatedFiles = Math.ceil(totalPages / config.pages_per_docx);
                        } else {
                          const avgChapterPages = totalPages / chapterBoundaries.length;
                          const chaptersPerFile = Math.max(1, Math.floor(config.pages_per_docx / avgChapterPages));
                          estimatedFiles = Math.ceil(chapterBoundaries.length / chaptersPerFile);
                        }
                        return (
                          <div className="mt-3">
                            <div className="flex items-center justify-between mb-2">
                              <button
                                type="button"
                                onClick={() => setChapterPreviewOpen((v) => !v)}
                                className="flex items-center gap-1.5 text-sm font-medium text-[#333]"
                              >
                                {chapterPreviewOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                {chapterBoundaries.length} chapter{chapterBoundaries.length !== 1 ? 's' : ''} detected
                              </button>
                              <span className="text-xs text-[#888]">
                                ~<strong>{estimatedFiles}</strong> output file{estimatedFiles !== 1 ? 's' : ''} estimated
                              </span>
                            </div>
                            {chapterPreviewOpen && (
                              <div className="rounded-xl border border-gray-100 overflow-hidden">
                                {chapterBoundaries.length === 0 ? (
                                  <div className="px-4 py-3 text-sm text-[#888]">No chapters detected. The pipeline will fall back to page-count splitting.</div>
                                ) : (
                                  <div className="divide-y divide-gray-100 max-h-64 overflow-y-auto">
                                    {chapterBoundaries.map((b, idx) => {
                                      const nextPage = idx + 1 < chapterBoundaries.length ? chapterBoundaries[idx + 1].page - 1 : config.end_page;
                                      return (
                                        <div key={b.page} className="flex items-baseline gap-3 px-4 py-2.5">
                                          <span className="text-xs text-[#aaa] shrink-0 w-24 text-right">pp.{b.page}–{nextPage}</span>
                                          <span className="text-sm text-[#333] truncate flex-1">{b.title}</span>
                                          <span className="text-xs text-[#aaa] shrink-0">{Math.round(b.confidence * 100)}%</span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </Section>

                <div className="border-t border-gray-100" />

                <Section title="Page range — optional">
                  <p className="text-xs text-[#888] -mt-2">Leave at defaults to process the full document. Change these only if you want to process a specific section.</p>
                  <div className="flex gap-4">
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-[#333] mb-1.5">
                        First page to include
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={config.end_page}
                        value={config.start_page}
                        onChange={(e) => setConfig((prev) => ({ ...prev, start_page: Number(e.target.value) || 1 }))}
                        className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                      />
                    </div>
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-[#333] mb-1.5">
                        Last page to include
                      </label>
                      <input
                        type="number"
                        min={config.start_page}
                        max={document?.page_count || 99999}
                        value={config.end_page}
                        onChange={(e) => setConfig((prev) => ({ ...prev, end_page: Number(e.target.value) || prev.end_page }))}
                        className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                      />
                    </div>
                  </div>
                </Section>

                <div className="border-t border-gray-100" />

                <Section title="Output options">
                  <Toggle
                    checked={config.keep_page_markers}
                    onChange={(v) => setConfig((prev) => ({ ...prev, keep_page_markers: v }))}
                    label="Include original page numbers in output files"
                  />
                  <p className="text-xs text-[#888] ml-[52px] -mt-2">
                    Adds a small marker like [SOURCE PAGE 42] before each page's content. Useful for cross-referencing with the original PDF.
                  </p>

                  <Toggle
                    checked={config.generate_appendix_reference}
                    onChange={(v) => setConfig((prev) => ({ ...prev, generate_appendix_reference: v }))}
                    label="Extract appendix and references as a separate section"
                  />
                  <p className="text-xs text-[#888] ml-[52px] -mt-2">
                    Detected appendix and bibliography pages are pulled out into their own file, keeping the main manuscript clean.
                  </p>
                </Section>

                {documents.length > 0 && (
                  <>
                    <div className="border-t border-gray-100" />
                    <Section title="Copy settings from another project">
                      <p className="text-xs text-[#888] -mt-2">Instantly apply the same settings you used on a previous project.</p>
                      <div className="flex gap-2">
                        <select
                          value={cloneSource}
                          onChange={(e) => setCloneSource(e.target.value)}
                          className="flex-1 px-4 py-2.5 rounded-xl border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#6A8776]/30"
                        >
                          <option value="">Choose a project…</option>
                          {documents.map((item) => (
                            <option key={item.id} value={item.id}>{item.filename}</option>
                          ))}
                        </select>
                        <button
                          onClick={handleClone}
                          disabled={!cloneSource}
                          className="px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50 disabled:opacity-40"
                        >
                          Copy
                        </button>
                      </div>
                    </Section>
                  </>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex justify-end gap-3 pb-2">
                <button
                  onClick={() => navigate(`/documents/${id}`)}
                  className="px-5 py-2.5 rounded-xl border border-gray-200 text-sm font-medium hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={saving || isProcessing}
                  className="px-6 py-2.5 rounded-xl bg-[#222222] text-white text-sm font-medium hover:bg-[#333] disabled:opacity-50 flex items-center gap-2"
                >
                  {saving ? (
                    <><Loader2 size={14} className="animate-spin" /> Starting…</>
                  ) : isProcessing ? (
                    'Already processing'
                  ) : (
                    <>Start Processing <ChevronRight size={14} /></>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

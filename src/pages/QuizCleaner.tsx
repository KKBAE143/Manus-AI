import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Download,
  FileQuestion,
  FileText,
  KeyRound,
  Loader2,
  Package,
  RotateCcw,
  Trash2,
  UploadCloud,
} from 'lucide-react';

import BackendUnavailableNotice from '../components/BackendUnavailableNotice';
import Header from '../components/Header';
import {
  absoluteUrl,
  api,
  isBackendUnavailableError,
  QuizPreview,
  QuizResult,
} from '../lib/api';

type Step = 'select' | 'previewing' | 'preview' | 'processing' | 'done';

export default function QuizCleaner() {
  const [step, setStep] = useState<Step>('select');
  const [quizFile, setQuizFile] = useState<File | null>(null);
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [preview, setPreview] = useState<QuizPreview | null>(null);
  const [chosenSubject, setChosenSubject] = useState<string | null>(null);
  const [result, setResult] = useState<QuizResult | null>(null);

  // Library state
  const [library, setLibrary] = useState<QuizResult[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const refreshLibrary = async () => {
    setLibraryLoading(true);
    try {
      const r = await api.listQuizLibrary();
      setLibrary(r.items);
    } catch (err) {
      if (isBackendUnavailableError(err)) setBackendUnavailable(true);
    } finally {
      setLibraryLoading(false);
    }
  };

  useEffect(() => {
    refreshLibrary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reset = () => {
    setStep('select');
    setQuizFile(null);
    setKeyFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setChosenSubject(null);
  };

  const onPreview = async () => {
    if (!quizFile) {
      setError('Please add a question paper PDF.');
      return;
    }
    setError(null);
    setStep('previewing');
    try {
      const p = await api.previewQuiz(quizFile, keyFile);
      setPreview(p);
      setChosenSubject(p.answer_key?.matched_subject?.code ?? null);
      setStep('preview');
    } catch (err) {
      handleErr(err);
      setStep('select');
    }
  };

  const onConfirm = async () => {
    if (!preview) return;
    setError(null);
    setStep('processing');
    try {
      const r = await api.confirmQuiz(preview.job_id, {
        subjectCode: chosenSubject ?? null,
        proceedWithoutKey: !preview.key_filename,
      });
      setResult(r);
      setStep('done');
      refreshLibrary();
    } catch (err) {
      handleErr(err);
      setStep('preview');
    }
  };

  const handleErr = (err: unknown) => {
    if (isBackendUnavailableError(err)) {
      setBackendUnavailable(true);
      setError('Cannot reach the backend API.');
      return;
    }
    console.error(err);
    setError(err instanceof Error ? err.message : 'Operation failed.');
  };

  const onBulkDownload = async (idsOrAll: string[] | 'all') => {
    setBulkBusy(true);
    try {
      const ids = idsOrAll === 'all' ? undefined : idsOrAll;
      const { blob, filename } = await api.bulkDownloadQuiz(ids);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      handleErr(err);
    } finally {
      setBulkBusy(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm('Delete this result permanently?')) return;
    try {
      await api.deleteQuizResult(id);
      setSelected((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
      refreshLibrary();
    } catch (err) {
      handleErr(err);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allSelected = library.length > 0 && selected.size === library.length;
  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(library.map((i) => i.id)));
  };

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title="Quiz Cleaner"
        subtitle="Strip exam-platform metadata, attach answer keys, build a library of cleaned papers."
      />

      <div className="flex-1 overflow-y-auto pb-6 px-6 md:px-0 md:pr-2 space-y-6">
        {backendUnavailable && (
          <div className="max-w-5xl mx-auto">
            <BackendUnavailableNotice apiBaseUrl={api.baseUrl} compact />
          </div>
        )}

        {error && (
          <div className="max-w-5xl mx-auto p-4 bg-red-50 border border-red-100 rounded-xl flex items-start gap-3 text-red-800">
            <AlertCircle className="shrink-0 mt-0.5" size={20} />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {/* === Upload / Preview / Done card === */}
        <div className="max-w-5xl mx-auto bg-white rounded-3xl p-8 shadow-sm">
          {step === 'select' && (
            <SelectStep
              quizFile={quizFile}
              keyFile={keyFile}
              setQuizFile={setQuizFile}
              setKeyFile={setKeyFile}
              onContinue={onPreview}
            />
          )}

          {step === 'previewing' && (
            <BusyState label="Inspecting files…" />
          )}

          {step === 'preview' && preview && (
            <PreviewStep
              preview={preview}
              chosenSubject={chosenSubject}
              setChosenSubject={setChosenSubject}
              onBack={() => setStep('select')}
              onConfirm={onConfirm}
            />
          )}

          {step === 'processing' && (
            <BusyState label="Generating cleaned PDF — this may take a few seconds…" />
          )}

          {step === 'done' && result && (
            <DoneStep result={result} onAnother={reset} />
          )}
        </div>

        {/* === Library === */}
        <div className="max-w-5xl mx-auto bg-white rounded-3xl shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4 border-b border-gray-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-[#E8F0EB] text-[#6A8776] flex items-center justify-center">
                <Package size={20} />
              </div>
              <div>
                <h3 className="font-semibold">Cleaned library</h3>
                <p className="text-xs text-[#888]">
                  {library.length} result{library.length === 1 ? '' : 's'} stored
                  {selected.size > 0 ? ` • ${selected.size} selected` : ''}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={toggleSelectAll}
                disabled={!library.length}
                className="px-3 py-2 rounded-lg text-xs border border-gray-200 hover:bg-gray-50 disabled:opacity-40"
              >
                {allSelected ? 'Clear selection' : 'Select all'}
              </button>
              <button
                onClick={() => onBulkDownload(Array.from(selected))}
                disabled={!selected.size || bulkBusy}
                className="px-3 py-2 rounded-lg text-xs bg-[#222] text-white hover:bg-[#333] disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                {bulkBusy ? <Loader2 className="animate-spin" size={14} /> : <Download size={14} />}
                Download selected (.zip)
              </button>
              <button
                onClick={() => onBulkDownload('all')}
                disabled={!library.length || bulkBusy}
                className="px-3 py-2 rounded-lg text-xs border border-gray-200 hover:bg-gray-50 disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                <Download size={14} /> Download all
              </button>
            </div>
          </div>

          {libraryLoading && !library.length ? (
            <div className="px-6 py-8 text-center text-sm text-[#888]">Loading library…</div>
          ) : library.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[#888]">
              No cleaned files yet. Process one above to get started.
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {library.map((item) => (
                <li key={item.id} className="flex items-center gap-4 px-6 py-3 hover:bg-[#FAFBFA]">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggleSelect(item.id)}
                    className="w-4 h-4 accent-[#6A8776]"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate">{item.output_filename}</p>
                    <p className="text-xs text-[#888] truncate">
                      {item.input_filename}
                      {item.answers_attached && item.answer_subject ? (
                        <> • <span className="text-[#3d8b5e]">{item.answer_subject}</span></>
                      ) : (
                        ' • no answer key'
                      )}
                      {' • '}
                      {item.stats.questions_kept} questions
                      {item.answers_attached
                        ? ` • ${item.stats.answers_matched}/${item.stats.questions_kept} answered`
                        : ''}
                      {item.answers_attached && item.stats.answers_missing_count > 0 && (
                        <span className="text-red-600"> • {item.stats.answers_missing_count} missing</span>
                      )}
                      {' • '}
                      {item.size_bytes ? `${Math.round((item.size_bytes / 1024) * 10) / 10} KB` : ''}
                    </p>
                    <p className="text-[10px] text-[#aaa]">{new Date(item.created_at).toLocaleString()}</p>
                  </div>
                  <a
                    href={absoluteUrl(item.download_url || `/api/v1/quiz/${item.id}/download`)}
                    download={item.output_filename}
                    className="px-3 py-1.5 rounded-lg text-xs border border-gray-200 hover:bg-white inline-flex items-center gap-1.5"
                  >
                    <Download size={14} /> Download
                  </a>
                  <button
                    onClick={() => onDelete(item.id)}
                    className="p-1.5 rounded-lg text-red-500 hover:bg-red-50"
                    aria-label="Delete"
                  >
                    <Trash2 size={16} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </main>
  );
}

// ----------------------------------------------------------- step views ---

function SelectStep({
  quizFile,
  keyFile,
  setQuizFile,
  setKeyFile,
  onContinue,
}: {
  quizFile: File | null;
  keyFile: File | null;
  setQuizFile: (f: File | null) => void;
  setKeyFile: (f: File | null) => void;
  onContinue: () => void;
}) {
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FileSlot
          icon={<FileText size={28} />}
          accent="#6A8776"
          accentBg="#E8F0EB"
          label="Question paper"
          required
          file={quizFile}
          onPick={setQuizFile}
          hint="Original NTA / TCS iON exam PDF."
        />
        <FileSlot
          icon={<KeyRound size={28} />}
          accent="#a07b1c"
          accentBg="#FBF3DD"
          label="Answer key"
          required={false}
          file={keyFile}
          onPick={setKeyFile}
          hint="Multi-subject final answer key PDF (optional)."
        />
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-[#888]">
          We strip Question Id / Type / Marks / Replay settings and the Hindi duplicate of every
          question. Question text, options, diagrams, graphs, and visuals are preserved as-is.
        </p>
        <button
          onClick={onContinue}
          disabled={!quizFile}
          className="px-6 py-3 rounded-xl bg-[#222] text-white font-medium hover:bg-[#333] disabled:opacity-40"
        >
          Continue
        </button>
      </div>
    </>
  );
}

function FileSlot({
  icon,
  accent,
  accentBg,
  label,
  required,
  file,
  onPick,
  hint,
}: {
  icon: React.ReactNode;
  accent: string;
  accentBg: string;
  label: string;
  required: boolean;
  file: File | null;
  onPick: (f: File | null) => void;
  hint: string;
}) {
  const [drag, setDrag] = useState(false);
  return (
    <label
      onDragEnter={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDrag(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onPick(f);
      }}
      className={`block border-2 border-dashed rounded-2xl p-6 cursor-pointer transition-colors ${
        drag ? 'bg-[#FAFBFA]' : 'hover:bg-[#FAFBFA]'
      } ${file ? 'border-transparent bg-[#F4F2EC]' : 'border-gray-200'}`}
    >
      <input
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
      <div className="flex items-start gap-4">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: accentBg, color: accent }}
        >
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="font-semibold">{label}</p>
            {required ? (
              <span className="text-[10px] uppercase tracking-wider text-[#a07b1c] bg-[#FBF3DD] px-1.5 py-0.5 rounded">
                Required
              </span>
            ) : (
              <span className="text-[10px] uppercase tracking-wider text-[#888] bg-gray-100 px-1.5 py-0.5 rounded">
                Optional
              </span>
            )}
          </div>
          <p className="text-xs text-[#888] mt-1">{hint}</p>
          {file ? (
            <div className="mt-3 flex items-center gap-2">
              <div className="px-2 py-1 rounded-md bg-white text-xs font-medium truncate max-w-[230px]">
                {file.name}
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  onPick(null);
                }}
                className="text-xs text-[#888] hover:text-red-500"
              >
                remove
              </button>
            </div>
          ) : (
            <div className="mt-3 inline-flex items-center gap-1.5 text-xs text-[#666]">
              <UploadCloud size={14} /> Drop a PDF or click to choose
            </div>
          )}
        </div>
      </div>
    </label>
  );
}

function BusyState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <div className="w-16 h-16 rounded-full bg-[#E8F0EB] text-[#6A8776] flex items-center justify-center">
        <Loader2 className="animate-spin" size={32} />
      </div>
      <p className="text-sm text-[#444]">{label}</p>
    </div>
  );
}

function PreviewStep({
  preview,
  chosenSubject,
  setChosenSubject,
  onBack,
  onConfirm,
}: {
  preview: QuizPreview;
  chosenSubject: string | null;
  setChosenSubject: (c: string | null) => void;
  onBack: () => void;
  onConfirm: () => void;
}) {
  const ak = preview.answer_key;
  const willAttachKey = !!preview.key_filename;
  const matchOk = ak?.matched_subject && ak.matched_count === preview.quiz_stats.questions_kept;
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold mb-1">Review &amp; confirm</h2>
        <p className="text-sm text-[#666]">
          Verify the detected subject and the match counts before generating the final PDF.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Pages" value={preview.quiz_stats.source_pages} />
        <Stat label="Questions kept" value={preview.quiz_stats.questions_kept} accent />
        <Stat label="Hindi removed" value={preview.quiz_stats.translations_removed} />
        <Stat label="Sections" value={preview.quiz_stats.sections_detected} />
      </div>

      {willAttachKey ? (
        <div className="rounded-2xl border border-gray-100 p-5">
          <p className="text-xs uppercase tracking-wider text-[#6A8776] font-semibold mb-3">
            Answer key
          </p>

          {!ak?.matched_subject ? (
            <div className="flex items-start gap-3 text-sm text-red-700 bg-red-50 p-3 rounded-xl">
              <AlertTriangle size={18} className="shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">No subject in the key matched any question id.</p>
                <p className="text-xs mt-1">
                  This usually means the question paper and answer key are from different exams. You
                  can still proceed without attaching answers — go back, remove the key, and continue.
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <span className="text-sm">Detected subject:</span>
                <span className="font-semibold text-[#222]">
                  ({ak.matched_subject.code}) {ak.matched_subject.name}
                </span>
                <span
                  className={`text-xs px-2 py-1 rounded-full ${
                    matchOk
                      ? 'bg-green-50 text-green-700'
                      : 'bg-amber-50 text-amber-700'
                  }`}
                >
                  {ak.matched_count} of {preview.quiz_stats.questions_kept} question ids matched
                </span>
              </div>

              {ak.subjects_in_key.length > 1 && (
                <div className="mb-4">
                  <label className="text-xs text-[#666] block mb-1">
                    Override subject (auto-detected above):
                  </label>
                  <select
                    value={chosenSubject ?? ''}
                    onChange={(e) => setChosenSubject(e.target.value || null)}
                    className="px-3 py-2 rounded-lg border border-gray-200 text-sm w-full max-w-md"
                  >
                    {ak.subjects_in_key.map((s) => (
                      <option key={s.code} value={s.code}>
                        ({s.code}) {s.name} — {ak.subject_match_counts[s.code] ?? 0} id matches
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {ak.preview_examples && ak.preview_examples.length > 0 && (
                <div className="mb-4">
                  <p className="text-xs text-[#666] mb-2">Sample answers (first {ak.preview_examples.length}):</p>
                  <ul className="text-xs space-y-1">
                    {ak.preview_examples.map((ex) => (
                      <li key={ex.q_id} className="font-mono">
                        <span className="text-[#888]">id {ex.q_id}</span>
                        {' → '}
                        <span className="text-[#222]">{ex.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {ak.answer_kinds_breakdown && (
                <div className="flex flex-wrap gap-2 text-xs">
                  {Object.entries(ak.answer_kinds_breakdown).map(([k, n]) => (
                    <span
                      key={k}
                      className="px-2 py-1 bg-gray-100 rounded font-mono text-[#444]"
                    >
                      {k}: {n}
                    </span>
                  ))}
                </div>
              )}

              {ak.missing_ids.length > 0 && (
                <div className="mt-4 p-3 bg-amber-50 border border-amber-100 rounded-xl text-xs text-amber-800">
                  <p className="font-semibold mb-1">
                    {ak.missing_ids.length} question id{ak.missing_ids.length === 1 ? '' : 's'} not in the answer key.
                  </p>
                  <p>These questions will be marked with a red "Answer key not found" warning on their pages, and listed on the cover page.</p>
                </div>
              )}

              {ak.warnings.length > 0 && (
                <div className="mt-3 p-3 bg-amber-50 border border-amber-100 rounded-xl text-xs text-amber-800">
                  <p className="font-semibold mb-1">Parser warnings:</p>
                  <ul className="list-disc pl-5 space-y-0.5">
                    {ak.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-gray-200 p-5 text-sm text-[#666]">
          No answer key uploaded. The output PDF will contain only cleaned questions, with no answer
          boxes attached.
        </div>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3 pt-2">
        <button
          onClick={onBack}
          className="px-5 py-2.5 rounded-xl border border-gray-200 text-sm hover:bg-white"
        >
          Back
        </button>
        <button
          onClick={onConfirm}
          className="px-5 py-2.5 rounded-xl bg-[#222] text-white text-sm font-medium hover:bg-[#333]"
        >
          Confirm &amp; generate
        </button>
      </div>
    </div>
  );
}

function DoneStep({ result, onAnother }: { result: QuizResult; onAnother: () => void }) {
  return (
    <div className="border border-green-100 bg-green-50 rounded-3xl p-8">
      <div className="w-16 h-16 rounded-full bg-white text-green-600 flex items-center justify-center mb-5 shadow-sm">
        <CheckCircle2 size={32} />
      </div>
      <h2 className="text-2xl font-bold mb-2">Saved to library</h2>
      <p className="text-sm text-[#4b5c50] mb-6">{result.output_filename}</p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        <Stat label="Source pages" value={result.stats.source_pages} />
        <Stat label="Questions" value={result.stats.questions_kept} accent />
        <Stat
          label="Answered"
          value={
            result.answers_attached
              ? `${result.stats.answers_matched}/${result.stats.questions_kept}`
              : '—'
          }
        />
        <Stat
          label="Missing keys"
          value={result.answers_attached ? result.stats.answers_missing_count : '—'}
        />
      </div>

      <div className="flex flex-wrap gap-3">
        <a
          href={absoluteUrl(result.download_url || `/api/v1/quiz/${result.id}/download`)}
          download={result.output_filename}
          className="bg-[#222] text-white px-6 py-3 rounded-xl font-medium hover:bg-[#333] inline-flex items-center gap-2"
        >
          <Download size={18} /> Download this PDF
        </a>
        <button
          onClick={onAnother}
          className="px-6 py-3 rounded-xl border border-gray-200 font-medium hover:bg-white inline-flex items-center gap-2"
        >
          <RotateCcw size={18} /> Process another
        </button>
      </div>

      <div className="mt-6 flex items-center gap-2 text-xs text-[#6c7a70]">
        <FileQuestion size={14} />
        <span>{result.input_filename}</span>
        {result.answer_subject ? <span> • {result.answer_subject}</span> : null}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: boolean;
}) {
  return (
    <div className={`rounded-2xl p-4 ${accent ? 'bg-white border border-green-200' : 'bg-[#FAFBFA]'}`}>
      <p className="text-[10px] uppercase tracking-wider text-[#6c7a70] font-semibold">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${accent ? 'text-[#3d8b5e]' : 'text-[#222]'}`}>
        {value}
      </p>
    </div>
  );
}

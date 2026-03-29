import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Save,
  Settings2,
} from 'lucide-react';
import Header from '../components/Header';
import { api, draftApi, ExportProfile } from '../lib/api';

const PAGE_SIZES = ['A4', 'US Letter', 'Custom'];
const MARGIN_PRESETS = [
  { label: 'Normal', top: 2.54, bottom: 2.54, left: 2.54, right: 2.54 },
  { label: 'Narrow', top: 1.27, bottom: 1.27, left: 1.27, right: 1.27 },
  { label: 'Wide', top: 2.54, bottom: 2.54, left: 3.81, right: 3.81 },
];
const FRONT_MATTER_OPTIONS = [
  { key: 'copyright', label: 'Copyright Page', field: 'copyright_text' as keyof ExportProfile },
  { key: 'disclaimer', label: 'Disclaimer', field: 'disclaimer' as keyof ExportProfile },
  { key: 'dedication', label: 'Dedication', field: 'dedication' as keyof ExportProfile },
  { key: 'preface', label: 'Preface', field: 'preface' as keyof ExportProfile },
  { key: 'acknowledgements', label: 'Acknowledgements', field: 'acknowledgements' as keyof ExportProfile },
];
const HEADING_LEVELS = [
  { value: 1, label: 'H1 only' },
  { value: 2, label: 'H1 + H2' },
  { value: 3, label: 'All headings' },
];

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${
        checked ? 'bg-[#6A8776]' : 'bg-gray-200'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-1'
        }`}
      />
    </button>
  );
}

export default function PublishingTools() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [docFilename, setDocFilename] = useState('');
  const [profile, setProfile] = useState<ExportProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [exporting, setExporting] = useState<'docx' | 'pdf' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [downloadFilename, setDownloadFilename] = useState('manuscript.docx');

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [docData, profileData] = await Promise.all([
        api.getDocument(id),
        draftApi.getExportProfile(id),
      ]);
      setDocFilename(docData.filename);
      setProfile(profileData);
    } catch (err: unknown) {
      let msg = err instanceof Error ? err.message : 'Failed to load publishing tools';
      try { const parsed = JSON.parse(msg); if (parsed.detail) msg = parsed.detail; } catch {}
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const update = (patch: Partial<ExportProfile>) => {
    setProfile((prev) => (prev ? { ...prev, ...patch } : prev));
    setSaved(false);
  };

  const updateFrontMatterSection = (key: string, value: boolean) => {
    setProfile((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        front_matter_sections: {
          ...(prev.front_matter_sections || {}),
          [key]: value,
        },
      };
    });
    setSaved(false);
  };

  const handleSave = async () => {
    if (!id || !profile) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await draftApi.updateExportProfile(id, profile);
      setProfile(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async (format: 'docx' | 'pdf') => {
    if (!id) return;
    setExporting(format);
    setExportError(null);
    setDownloadUrl(null);
    try {
      await handleSave();
      const response =
        format === 'docx'
          ? await draftApi.exportDocx(id)
          : await draftApi.exportPdf(id);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Export failed: ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      setDownloadUrl(url);
      setDownloadFilename(
        `${profile?.book_title || 'manuscript'}.${format}`
      );
    } catch (err: unknown) {
      setExportError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(null);
    }
  };

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center text-sm text-[#888888] gap-2">
        <Loader2 size={16} className="animate-spin" /> Loading publishing tools…
      </main>
    );
  }

  if (error || !profile) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-red-600">{error || 'Profile not found.'}</p>
        <button
          onClick={() => navigate(`/workspace/${id}`)}
          className="px-4 py-2 rounded-xl bg-[#222222] text-white text-sm"
        >
          Back to Workspace
        </button>
      </main>
    );
  }

  const fmSections = profile.front_matter_sections || {};

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header
        title={docFilename || 'Publishing Tools'}
        subtitle="Configure front matter, layout, and export your final manuscript."
      />

      <div className="bg-white border-b border-gray-100 px-4 py-3 flex items-center gap-3 flex-wrap shrink-0">
        <button
          onClick={() => navigate(`/workspace/${id}`)}
          className="flex items-center gap-1.5 text-sm text-[#888888] hover:text-[#222222]"
        >
          <ArrowLeft size={15} /> Workspace
        </button>
        <div className="h-5 w-px bg-gray-200" />
        <button
          onClick={() => navigate(`/assembly/${id}`)}
          className="flex items-center gap-1.5 text-sm text-[#888888] hover:text-[#222222]"
        >
          Final Assembly
        </button>
        <div className="ml-auto flex items-center gap-2">
          {saveError && (
            <span className="text-xs text-red-600">{saveError}</span>
          )}
          {saved && (
            <span className="flex items-center gap-1 text-xs text-green-700">
              <CheckCircle2 size={12} /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-[#6A8776] text-white text-sm font-medium hover:bg-[#5a7366] disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <div className="flex items-center gap-2 mb-2">
              <Settings2 size={18} className="text-[#6A8776]" />
              <h2 className="font-semibold text-base">Title Page</h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Book Title</label>
                <input
                  type="text"
                  value={profile.book_title || ''}
                  onChange={(e) => update({ book_title: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="Untitled Manuscript"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Subtitle</label>
                <input
                  type="text"
                  value={profile.subtitle || ''}
                  onChange={(e) => update({ subtitle: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="Optional subtitle"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Author Name</label>
                <input
                  type="text"
                  value={profile.author || ''}
                  onChange={(e) => update({ author: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="Author name"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Edition</label>
                <input
                  type="text"
                  value={profile.edition || ''}
                  onChange={(e) => update({ edition: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="e.g. First Edition, 2nd Edition"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Institution / Publisher</label>
                <input
                  type="text"
                  value={profile.institution || ''}
                  onChange={(e) => update({ institution: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="University / Publisher"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">ISBN</label>
                <input
                  type="text"
                  value={profile.isbn || ''}
                  onChange={(e) => update({ isbn: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  placeholder="978-XXXXXXXXXX"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Copyright Year</label>
                <input
                  type="number"
                  min="1900"
                  max="2100"
                  value={profile.copyright_year ?? new Date().getFullYear()}
                  onChange={(e) => update({ copyright_year: parseInt(e.target.value) || new Date().getFullYear() })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                />
              </div>
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <h2 className="font-semibold text-base">Front Matter</h2>

            <div className="space-y-4">
              {FRONT_MATTER_OPTIONS.map((opt) => {
                const enabled = fmSections[opt.key] ?? false;
                return (
                  <div key={opt.key} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium">{opt.label}</label>
                      <Toggle
                        checked={enabled}
                        onChange={(v) => updateFrontMatterSection(opt.key, v)}
                      />
                    </div>
                    {enabled && (
                      <textarea
                        rows={4}
                        value={(profile[opt.field] as string) || ''}
                        onChange={(e) => update({ [opt.field]: e.target.value })}
                        className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776] resize-none"
                        placeholder={`Enter ${opt.label.toLowerCase()} content…`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <h2 className="font-semibold text-base">Table of Contents</h2>

            <div className="flex items-center justify-between">
              <span className="text-sm">Auto-generate TOC</span>
              <Toggle
                checked={profile.include_toc}
                onChange={(v) => update({ include_toc: v })}
              />
            </div>

            {profile.include_toc && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">
                  Heading Levels to Include
                </label>
                <div className="flex gap-2 flex-wrap">
                  {HEADING_LEVELS.map((hl) => (
                    <button
                      key={hl.value}
                      onClick={() => update({ toc_heading_levels: hl.value })}
                      className={`px-3 py-1.5 rounded-xl text-sm font-medium transition-colors ${
                        profile.toc_heading_levels === hl.value
                          ? 'bg-[#222222] text-white'
                          : 'bg-gray-100 hover:bg-gray-200 text-[#222222]'
                      }`}
                    >
                      {hl.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <h2 className="font-semibold text-base">Heading Hierarchy Mapping</h2>
            <p className="text-xs text-[#888888]">Map detected heading levels to Word heading styles.</p>

            <div className="space-y-3">
              {['H1', 'H2', 'H3'].map((level) => (
                <div key={level} className="flex items-center gap-4">
                  <span className="text-sm font-medium w-10 text-[#6A8776]">{level}</span>
                  <span className="text-sm text-[#888888]">→</span>
                  <select
                    value={(profile.heading_mapping || {})[level] || `Heading ${level.slice(1)}`}
                    onChange={(e) =>
                      update({
                        heading_mapping: {
                          ...(profile.heading_mapping || {}),
                          [level]: e.target.value,
                        },
                      })
                    }
                    className="flex-1 px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776] bg-white"
                  >
                    <option>Heading 1</option>
                    <option>Heading 2</option>
                    <option>Heading 3</option>
                    <option>Heading 4</option>
                    <option>Normal</option>
                    <option>Title</option>
                    <option>Subtitle</option>
                  </select>
                </div>
              ))}
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <h2 className="font-semibold text-base">Page Layout</h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Page Size</label>
                <div className="flex gap-2 flex-wrap">
                  {PAGE_SIZES.map((ps) => (
                    <button
                      key={ps}
                      onClick={() => update({ page_size: ps })}
                      className={`px-3 py-1.5 rounded-xl text-sm font-medium transition-colors ${
                        profile.page_size === ps
                          ? 'bg-[#222222] text-white'
                          : 'bg-gray-100 hover:bg-gray-200 text-[#222222]'
                      }`}
                    >
                      {ps}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">Margin Preset</label>
                <div className="flex gap-2 flex-wrap">
                  {MARGIN_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      onClick={() =>
                        update({
                          margin_top_cm: preset.top,
                          margin_bottom_cm: preset.bottom,
                          margin_left_cm: preset.left,
                          margin_right_cm: preset.right,
                        })
                      }
                      className={`px-3 py-1.5 rounded-xl text-sm font-medium transition-colors ${
                        profile.margin_left_cm === preset.left && profile.margin_top_cm === preset.top
                          ? 'bg-[#222222] text-white'
                          : 'bg-gray-100 hover:bg-gray-200 text-[#222222]'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {(
                [
                  { key: 'margin_top_cm', label: 'Top' },
                  { key: 'margin_bottom_cm', label: 'Bottom' },
                  { key: 'margin_left_cm', label: 'Left' },
                  { key: 'margin_right_cm', label: 'Right' },
                ] as { key: keyof ExportProfile; label: string }[]
              ).map(({ key, label }) => (
                <div key={key} className="space-y-1">
                  <label className="text-xs text-[#888888]">{label} (cm)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={profile[key] as number}
                    onChange={(e) => update({ [key]: parseFloat(e.target.value) || 0 })}
                    className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                  />
                </div>
              ))}
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">
            <h2 className="font-semibold text-base">Page Numbering</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">
                  Start Page Number
                </label>
                <input
                  type="number"
                  min="1"
                  value={profile.page_number_start}
                  onChange={(e) => update({ page_number_start: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-[#6A8776]"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#888888] uppercase tracking-wide">
                  Number Format
                </label>
                <div className="flex gap-2">
                  {['arabic', 'roman'].map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => update({ page_number_format: fmt })}
                      className={`px-3 py-2 rounded-xl text-sm font-medium transition-colors ${
                        profile.page_number_format === fmt
                          ? 'bg-[#222222] text-white'
                          : 'bg-gray-100 hover:bg-gray-200 text-[#222222]'
                      }`}
                    >
                      {fmt === 'arabic' ? '1, 2, 3…' : 'i, ii, iii…'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-100 p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Download size={18} className="text-[#6A8776]" />
              <h2 className="font-semibold text-base">Export</h2>
            </div>

            <div className="flex gap-3 flex-wrap">
              <button
                onClick={() => handleExport('docx')}
                disabled={exporting !== null}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#222222] text-white text-sm font-medium hover:bg-[#333] disabled:opacity-50"
              >
                {exporting === 'docx' ? (
                  <><Loader2 size={14} className="animate-spin" /> Exporting…</>
                ) : (
                  <><FileText size={14} /> Export DOCX</>
                )}
              </button>

              <button
                onClick={() => handleExport('pdf')}
                disabled={exporting !== null}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#6A8776] text-white text-sm font-medium hover:bg-[#5a7366] disabled:opacity-50"
              >
                {exporting === 'pdf' ? (
                  <><Loader2 size={14} className="animate-spin" /> Converting…</>
                ) : (
                  <><FileText size={14} /> Export PDF</>
                )}
              </button>
            </div>

            <p className="text-xs text-[#888888]">
              PDF export requires LibreOffice to be installed on the server. DOCX export works without additional dependencies.
            </p>

            {exportError && (
              <div className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{exportError}</div>
            )}

            {downloadUrl && (
              <a
                href={downloadUrl}
                download={downloadFilename}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-green-600 text-white text-sm font-medium hover:bg-green-700 w-fit"
              >
                <Download size={14} /> Download {downloadFilename}
              </a>
            )}
          </section>

        </div>
      </div>
    </main>
  );
}

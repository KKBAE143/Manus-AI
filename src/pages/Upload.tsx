import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2, FileText, UploadCloud } from 'lucide-react';

import BackendUnavailableNotice from '../components/BackendUnavailableNotice';
import Header from '../components/Header';
import { api, isBackendUnavailableError } from '../lib/api';

export default function Upload() {
  const navigate = useNavigate();
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; page_count: number } | null>(null);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [largeFileWarning, setLargeFileWarning] = useState(false);

  const handleFile = async (nextFile: File) => {
    setError(null);
    setLargeFileWarning(false);
    if (!nextFile.name.toLowerCase().endsWith('.pdf')) {
      setError('Please upload a PDF file.');
      return;
    }

    if (nextFile.size > 100 * 1024 * 1024) {
      setLargeFileWarning(true);
    }

    setFile(nextFile);
    setUploading(true);
    try {
      const response = await api.uploadDocument(nextFile);
      setResult({ id: response.id, page_count: response.page_count });
      setBackendUnavailable(false);
    } catch (uploadError) {
      if (isBackendUnavailableError(uploadError)) {
        setBackendUnavailable(true);
        setError('Upload failed because the backend API is not running.');
      } else {
        console.error(uploadError);
        setError('Upload failed. Please try again.');
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      <Header title="Upload PDF" subtitle="Create a processing project for a very large manuscript PDF." />

      <div className="flex-1 overflow-y-auto pb-6 px-6 md:px-0 md:pr-2 flex items-center justify-center">
        <div className="w-full max-w-3xl bg-white rounded-3xl p-8 shadow-sm">
          {backendUnavailable && <div className="mb-6"><BackendUnavailableNotice apiBaseUrl={api.baseUrl} compact /></div>}

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-xl flex items-start gap-3 text-red-800">
              <AlertCircle className="shrink-0 mt-0.5" size={20} />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {largeFileWarning && (
            <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-3 text-amber-800">
              <AlertCircle className="shrink-0 mt-0.5" size={20} />
              <span className="text-sm flex-1">This file is larger than 100 MB — processing may take a while.</span>
              <button onClick={() => setLargeFileWarning(false)} className="text-amber-600 hover:text-amber-800 text-lg leading-none">&times;</button>
            </div>
          )}

          {!result ? (
            <label
              className={`block border-2 border-dashed rounded-3xl p-12 text-center cursor-pointer transition-colors ${
                dragActive ? 'border-[#6A8776] bg-[#E8F0EB]/40' : 'border-gray-200 hover:border-[#6A8776]/40 hover:bg-[#FAFBFA]'
              }`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={(event) => {
                event.preventDefault();
                setDragActive(false);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                const dropped = event.dataTransfer.files?.[0];
                if (dropped) handleFile(dropped);
              }}
            >
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(event) => {
                  const selected = event.target.files?.[0];
                  if (selected) handleFile(selected);
                }}
              />
              <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-[#E8F0EB] text-[#6A8776] flex items-center justify-center">
                <UploadCloud size={40} />
              </div>
              <h2 className="text-2xl font-bold mb-2">Drop a large PDF here</h2>
              <p className="text-[#888888] max-w-xl mx-auto text-sm leading-relaxed">
                The backend will register a project, detect page count, and prepare the document for strict preservation processing.
              </p>
              <div className="mt-8 inline-flex px-6 py-3 rounded-full bg-[#222222] text-white font-medium">
                {uploading ? 'Uploading...' : 'Select PDF'}
              </div>
              {file && <div className="mt-4 text-sm text-[#888888]">{file.name}</div>}
            </label>
          ) : (
            <div className="border border-green-100 bg-green-50 rounded-3xl p-8">
              <div className="w-16 h-16 rounded-full bg-white text-green-600 flex items-center justify-center mb-5 shadow-sm">
                <CheckCircle2 size={32} />
              </div>
              <h2 className="text-2xl font-bold mb-2">Project created</h2>
              <p className="text-sm text-[#4b5c50] mb-6">
                {file?.name} registered successfully. Detected page count: {result.page_count}.
              </p>
              <div className="flex items-center gap-3 text-sm text-[#4b5c50] mb-8">
                <FileText size={16} />
                <span>Project ID: {result.id}</span>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => navigate(`/config/${result.id}`)}
                  className="bg-[#222222] text-white px-6 py-3 rounded-xl font-medium hover:bg-[#333] transition-colors"
                >
                  Configure Pipeline
                </button>
                <button
                  onClick={() => navigate(`/documents/${result.id}`)}
                  className="px-6 py-3 rounded-xl border border-gray-200 font-medium hover:bg-white transition-colors"
                >
                  Open Project
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

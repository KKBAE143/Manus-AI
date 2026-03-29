import React from 'react';
import { AlertCircle } from 'lucide-react';

interface BackendUnavailableNoticeProps {
  apiBaseUrl: string;
  compact?: boolean;
}

export default function BackendUnavailableNotice({ apiBaseUrl, compact = false }: BackendUnavailableNoticeProps) {
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 shrink-0" size={compact ? 18 : 20} />
        <div>
          <div className="font-medium">Backend API unavailable</div>
          <div className={`text-sm ${compact ? 'mt-0.5' : 'mt-1'}`}>
            Start the API server at `{apiBaseUrl}` to load documents, upload files, and run processing jobs.
          </div>
        </div>
      </div>
    </div>
  );
}

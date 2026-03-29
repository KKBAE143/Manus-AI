import React from 'react';
import { ErrorBoundary as ReactErrorBoundary, FallbackProps } from 'react-error-boundary';
import { AlertTriangle } from 'lucide-react';

interface Props {
  children: React.ReactNode;
  fallbackTitle?: string;
}

function ErrorFallback({ error, resetErrorBoundary, fallbackTitle }: FallbackProps & { fallbackTitle?: string }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[40vh] gap-4 p-8">
      <div className="flex items-center gap-3 text-red-600">
        <AlertTriangle size={28} />
        <h2 className="text-lg font-semibold">
          {fallbackTitle || 'Something went wrong'}
        </h2>
      </div>
      <p className="text-sm text-gray-500 max-w-md text-center">{(error as Error).message}</p>
      <button
        onClick={resetErrorBoundary}
        className="px-4 py-2 rounded-lg bg-[#222222] text-white text-sm font-medium hover:opacity-80"
      >
        Try again
      </button>
    </div>
  );
}

export function ErrorBoundary({ children, fallbackTitle }: Props) {
  return (
    <ReactErrorBoundary
      FallbackComponent={(props) => <ErrorFallback {...props} fallbackTitle={fallbackTitle} />}
      onError={(error, info) => {
        console.error('[ErrorBoundary]', error, info.componentStack);
      }}
    >
      {children}
    </ReactErrorBoundary>
  );
}

/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { FileText, LogIn } from 'lucide-react';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Upload = lazy(() => import('./pages/Upload'));
const Configuration = lazy(() => import('./pages/Configuration'));
const Documents = lazy(() => import('./pages/Documents'));
const DocumentDetails = lazy(() => import('./pages/DocumentDetails'));
const DocumentPreview = lazy(() => import('./pages/DocumentPreview'));
const ReviewQueue = lazy(() => import('./pages/ReviewQueue'));
const ManuscriptWorkspace = lazy(() => import('./pages/ManuscriptWorkspace'));
const BookPreview = lazy(() => import('./pages/BookPreview'));
const FinalAssembly = lazy(() => import('./pages/FinalAssembly'));
const PublishingTools = lazy(() => import('./pages/PublishingTools'));
const DocumentSelectorPage = lazy(() => import('./pages/DocumentSelectorPage'));

function RouteFallback() {
  return (
    <main className="flex-1 flex items-center justify-center text-sm text-[#888888]">
      Loading...
    </main>
  );
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading, signingIn, signIn, error } = useAuth();
  const authDisabled = (import.meta.env.VITE_DISABLE_AUTH || 'true') === 'true';

  if (authDisabled) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F4F2EC] flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-12 h-12 bg-[#6A8776] rounded-xl flex items-center justify-center text-white">
            <FileText size={24} />
          </div>
          <p className="text-[#888888] font-medium">Loading platform...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-[#F4F2EC] flex items-center justify-center p-6">
        <div className="bg-white rounded-3xl p-10 shadow-sm max-w-md w-full text-center">
          <div className="w-16 h-16 bg-[#E8F0EB] text-[#6A8776] rounded-2xl flex items-center justify-center mx-auto mb-6">
            <FileText size={32} />
          </div>
          <h1 className="text-2xl font-bold mb-2">Manuscript Converter</h1>
          <p className="text-[#888888] mb-8">Sign in to access your document processing pipeline and generated artifacts.</p>
          
          {error && (
            <div className="mb-4 p-3 bg-red-50 text-red-600 rounded-xl text-sm">
              {error}
            </div>
          )}
          
          <button 
            onClick={signIn}
            disabled={signingIn}
            className={`w-full bg-[#222222] text-white rounded-xl py-3 font-medium transition-colors flex items-center justify-center gap-2 ${
              signingIn ? 'opacity-70 cursor-not-allowed' : 'hover:bg-[#333]'
            }`}
          >
            {signingIn ? (
              <>
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Signing in...
              </>
            ) : (
              <>
                <LogIn size={18} /> Continue with Google
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <AuthGuard>
          <div className="min-h-screen bg-[#F4F2EC] text-[#222222] font-sans flex flex-col md:flex-row p-0 md:p-6 gap-0 md:gap-6">
            <Sidebar />
            <div className="flex-1 flex flex-col h-[calc(100dvh-80px)] md:h-[calc(100vh-48px)] overflow-hidden w-full">
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/upload" element={<Upload />} />
                  <Route path="/config/:id" element={<Configuration />} />
                  <Route path="/merge" element={<Navigate to="/assembly" replace />} />
                  <Route path="/documents" element={<Documents />} />
                  <Route path="/documents/:id" element={
                    <ErrorBoundary fallbackTitle="Error loading document">
                      <DocumentDetails />
                    </ErrorBoundary>
                  } />
                  <Route path="/documents/:id/preview" element={<DocumentPreview />} />
                  <Route path="/review" element={<ReviewQueue />} />
                  <Route path="/workspace" element={<DocumentSelectorPage destination="workspace" />} />
                  <Route path="/workspace/:documentId" element={
                    <ErrorBoundary fallbackTitle="Error loading workspace">
                      <ManuscriptWorkspace />
                    </ErrorBoundary>
                  } />
                  <Route path="/workspace/:documentId/book-preview" element={<BookPreview />} />
                  <Route path="/assembly" element={<DocumentSelectorPage destination="assembly" />} />
                  <Route path="/assembly/:id" element={
                    <ErrorBoundary fallbackTitle="Error loading assembly">
                      <FinalAssembly />
                    </ErrorBoundary>
                  } />
                  <Route path="/publishing" element={<DocumentSelectorPage destination="publishing" />} />
                  <Route path="/publishing/:id" element={<PublishingTools />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </div>
          </div>
        </AuthGuard>
      </Router>
    </AuthProvider>
  );
}

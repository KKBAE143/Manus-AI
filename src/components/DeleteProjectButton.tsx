import React from 'react';
import { Trash2 } from 'lucide-react';

import { api } from '../lib/api';

type Props = {
  documentId: string;
  label?: string;
  className?: string;
  onDeleted?: () => void;
  stopPropagation?: boolean;
};

export default function DeleteProjectButton({
  documentId,
  label = 'Delete',
  className = '',
  onDeleted,
  stopPropagation = true,
}: Props) {
  const [deleting, setDeleting] = React.useState(false);

  const handleDelete = async (event: React.MouseEvent) => {
    if (stopPropagation) {
      event.stopPropagation();
      event.preventDefault();
    }

    const confirmed = window.confirm('Delete this project and all generated files? This cannot be undone.');
    if (!confirmed) return;

    setDeleting(true);
    try {
      await api.deleteDocument(documentId);
      onDeleted?.();
    } catch (error) {
      console.error(error);
      window.alert('Failed to delete project.');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <button
      onClick={handleDelete}
      disabled={deleting}
      className={`inline-flex items-center gap-2 rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-60 ${className}`}
    >
      <Trash2 size={14} />
      {deleting ? 'Deleting...' : label}
    </button>
  );
}

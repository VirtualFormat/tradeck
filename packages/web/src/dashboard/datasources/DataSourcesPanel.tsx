import { useState } from 'react';
import { useDataSources } from '../../api/useDataSources';
import { Card } from '../widgets/Card';
import { DataSourceList } from './DataSourceList';
import { DataSourceForm } from './DataSourceForm';

export function DataSourcesPanel({ onClose }: { onClose: () => void }): JSX.Element {
  const { data, isLoading } = useDataSources();
  const [formOpen, setFormOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  const editing = editId ? data?.find((d) => d.id === editId) : undefined;
  const closeForm = (): void => {
    setFormOpen(false);
    setEditId(null);
  };

  return (
    <div className="fixed inset-0 z-50 bg-bg/90 backdrop-blur-sm flex items-start justify-center overflow-y-auto py-10">
      <div className="w-full max-w-2xl px-4">
        <Card
          title="Data Sources · config-driven · hot-reload"
          corner={
            <button type="button" onClick={onClose} className="text-muted hover:text-fg">
              ✕ close
            </button>
          }
        >
          <div className="flex justify-end mb-2">
            {!formOpen && (
              <button
                type="button"
                onClick={() => {
                  setEditId(null);
                  setFormOpen(true);
                }}
                className="px-3 py-1 rounded border border-accent text-fg text-xs bg-panel-2"
              >
                + add source
              </button>
            )}
          </div>

          {(formOpen || editing) && (
            <div className="mb-3">
              <DataSourceForm editing={editing} onDone={closeForm} />
            </div>
          )}

          {isLoading && <div className="text-muted text-xs py-3">loading…</div>}
          {data && <DataSourceList items={data} onEdit={(id) => setEditId(id)} />}
        </Card>
      </div>
    </div>
  );
}

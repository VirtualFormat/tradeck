import type { ConnectorStatus, DataSourceWithHealth } from '@tradeck/shared';
import { useDeleteDataSource, useUpdateDataSource } from '../../api/useDataSources';

const statusDot: Record<ConnectorStatus, string> = {
  running: 'bg-up',
  starting: 'bg-accent',
  error: 'bg-down',
  stopped: 'bg-muted',
  idle: 'bg-muted',
  unknown: 'bg-muted',
};

interface Props {
  items: DataSourceWithHealth[];
  onEdit: (id: string) => void;
}

export function DataSourceList({ items, onEdit }: Props): JSX.Element {
  const update = useUpdateDataSource();
  const del = useDeleteDataSource();

  return (
    <div className="divide-y divide-border/50">
      {items.map((d) => (
        <div key={d.id} className="flex items-center gap-3 py-2 text-xs">
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot[d.status]} ${d.status === 'running' ? 'animate-pulse' : ''}`}
            title={d.status}
          />
          <div className="flex-1 min-w-0">
            <div className="text-fg truncate">{d.name}</div>
            <div className="text-muted text-[10px]">
              {d.id} · {d.type} · {d.status}
            </div>
          </div>
          <button
            type="button"
            onClick={() => update.mutate({ id: d.id, dto: { enabled: !d.enabled } })}
            className={`px-2 py-1 rounded border text-[10px] ${d.enabled ? 'border-up/40 text-up' : 'border-border text-muted'}`}
          >
            {d.enabled ? 'ON' : 'OFF'}
          </button>
          <button
            type="button"
            onClick={() => onEdit(d.id)}
            className="px-2 py-1 rounded border border-border text-muted hover:text-fg text-[10px]"
          >
            edit
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm(`Delete data source "${d.id}"?`)) del.mutate(d.id);
            }}
            className="px-2 py-1 rounded border border-down/40 text-down text-[10px]"
          >
            del
          </button>
        </div>
      ))}
    </div>
  );
}

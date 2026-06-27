import { useState } from 'react';
import type { DataSourceType, DataSourceWithHealth } from '@tradeck/shared';

// Inlined to avoid Rollup's unreliable named-export tracing through the
// shared package's CommonJS `export *` barrel for runtime value imports.
const DATA_SOURCE_TYPES: readonly DataSourceType[] = [
  'mock',
  'binance',
  'rss',
  'mock-feed',
  'http-json',
];
import { useCreateDataSource, useUpdateDataSource } from '../../api/useDataSources';

interface Props {
  editing?: DataSourceWithHealth;
  onDone: () => void;
}

const inputCls =
  'w-full bg-panel-2 border border-border rounded px-2 py-1 text-xs text-fg outline-none focus:border-accent';

export function DataSourceForm({ editing, onDone }: Props): JSX.Element {
  const create = useCreateDataSource();
  const update = useUpdateDataSource();
  const isEdit = !!editing;

  const [id, setId] = useState(editing?.id ?? '');
  const [type, setType] = useState<DataSourceType>(editing?.type ?? 'http-json');
  const [name, setName] = useState(editing?.name ?? '');
  const [symbols, setSymbols] = useState((editing?.config.symbols ?? []).join(','));
  const [optionsText, setOptionsText] = useState(
    JSON.stringify(editing?.config.options ?? { url: '', intervalMs: 5000, output: 'tick', symbol: '', mapping: { price: '$.price' } }, null, 2),
  );
  const [err, setErr] = useState<string | null>(null);

  const submit = (): void => {
    setErr(null);
    let options: Record<string, unknown>;
    try {
      options = optionsText.trim() ? (JSON.parse(optionsText) as Record<string, unknown>) : {};
    } catch {
      setErr('options is not valid JSON');
      return;
    }
    const config = {
      symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
      options,
    };
    if (isEdit) {
      update.mutate({ id: editing.id, dto: { type, name, config } }, { onSuccess: onDone, onError: (e) => setErr(String(e)) });
    } else {
      create.mutate({ id, type, name, enabled: true, config }, { onSuccess: onDone, onError: (e) => setErr(String(e)) });
    }
  };

  return (
    <div className="space-y-2 border border-border rounded p-3 bg-panel-2/40">
      <div className="text-muted text-[10px] uppercase tracking-wider">
        {isEdit ? `edit ${editing.id}` : 'new data source'}
      </div>
      {!isEdit && (
        <input className={inputCls} placeholder="id (lowercase slug)" value={id} onChange={(e) => setId(e.target.value)} />
      )}
      <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as DataSourceType)}>
        {DATA_SOURCE_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <input className={inputCls} placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
      <input className={inputCls} placeholder="symbols (comma separated)" value={symbols} onChange={(e) => setSymbols(e.target.value)} />
      <textarea className={`${inputCls} font-mono`} rows={6} value={optionsText} onChange={(e) => setOptionsText(e.target.value)} />
      {err && <div className="text-down text-[10px]">{err}</div>}
      <div className="flex gap-2">
        <button type="button" onClick={submit} className="px-3 py-1 rounded border border-accent text-fg text-xs bg-panel-2">
          {isEdit ? 'save' : 'create'}
        </button>
        <button type="button" onClick={onDone} className="px-3 py-1 rounded border border-border text-muted text-xs">
          cancel
        </button>
      </div>
    </div>
  );
}

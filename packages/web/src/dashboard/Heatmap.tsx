import { useMemo } from 'react';
import type { MarketDepthSector } from '@tradeck/shared';
import { Card } from './widgets/Card';
import type { DataSourceMode, Market } from './market';

function heatStyle(changePct: number): { background: string; borderColor: string } {
  const mag = Math.min(1, Math.abs(changePct) / 0.03);
  const color =
    changePct >= 0
      ? `rgba(32, 205, 141, ${0.18 + mag * 0.48})`
      : `rgba(240, 85, 107, ${0.18 + mag * 0.48})`;
  return {
    background: `linear-gradient(180deg, rgba(255,255,255,0.035), transparent 58%), ${color}`,
    borderColor: changePct >= 0 ? 'rgba(32,205,141,0.42)' : 'rgba(240,85,107,0.42)',
  };
}

const TILE_SPANS = [
  'col-span-3 row-span-2',
  'col-span-2 row-span-2',
  'col-span-1 row-span-2',
  'col-span-2 row-span-2',
  'col-span-2 row-span-1',
  'col-span-2 row-span-1',
  'col-span-1 row-span-1',
  'col-span-1 row-span-1',
];

interface Props {
  market: Market;
  sourceMode: DataSourceMode;
  sectors: MarketDepthSector[];
  loading: boolean;
  selectedSectorId: string | null;
  onSectorSelect: (sectorId: string) => void;
}

export function Heatmap({ sourceMode, sectors, loading, selectedSectorId, onSectorSelect }: Props): JSX.Element {
  const rows = useMemo(
    () => sectors.slice().sort((a, b) => b.heat - a.heat),
    [sectors],
  );

  return (
    <Card title="板块热度地形图" subtitle="Heat mosaic · click for stocks" corner="点击弹窗">
      {rows.length > 0 ? (
        <div className="grid h-full min-h-[220px] grid-cols-6 grid-rows-4 gap-2">
          {rows.map((sector, index) => {
            const up = sector.changePct >= 0;
            const active = selectedSectorId === sector.id;
            return (
              <button
                key={sector.id}
                type="button"
                onClick={() => onSectorSelect(sector.id)}
                style={heatStyle(sector.changePct)}
                className={`${TILE_SPANS[index % TILE_SPANS.length]} min-h-0 overflow-hidden rounded-md border p-2 text-left transition-transform hover:scale-[1.01] ${
                  active ? 'ring-1 ring-accent' : ''
                }`}
              >
                <div className="flex h-full min-h-0 flex-col justify-between">
                  <div className="min-w-0">
                    <div className="truncate text-[12px] font-semibold text-white">{sector.name}</div>
                    <div className="mt-0.5 text-[9px] uppercase tracking-[0.16em] text-white/55">
                      heat {sector.heat.toFixed(0)}
                    </div>
                  </div>
                  <div>
                    <div className={`tab-nums text-[15px] leading-none ${up ? 'text-up' : 'text-down'}`}>
                      {up ? '+' : ''}
                      {(sector.changePct * 100).toFixed(2)}%
                    </div>
                    <div className="mt-1 text-[9px] text-white/60">
                      {sector.stocks.length} 只成分股
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          {loading ? '加载板块热度数据...' : `等待 ${sourceMode === 'futu' ? 'Futu' : '真实'} 板块热度数据接入`}
        </div>
      )}
    </Card>
  );
}

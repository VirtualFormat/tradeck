import { useEffect, useMemo, useState } from 'react';
import { Responsive, WidthProvider, type Layout } from 'react-grid-layout';
import type { DashboardLayout } from '@tradeck/shared';
import { useTickStream } from '../api/useTickStream';
import { useTickers } from '../api/useTickers';
import { useMarketDepth } from '../api/useMarketDepth';
import { useDashboardLayout, useSaveLayout } from '../api/useDashboardLayout';
import { LIVE_SYMBOL } from './mock/dashboardData';
import { DashboardHeader } from './DashboardHeader';
import { MarketOverview } from './MarketOverview';
import { TopWinsCard } from './TopWinsCard';
import { MoversBar } from './MoversBar';
import { Heatmap } from './Heatmap';
import { SectorTurnoverPanel } from './SectorTurnoverPanel';
import { SectorStockPopup } from './SectorStockPopup';
import { RelationshipGraph } from './RelationshipGraph';
import { FeedList } from './FeedList';
import { DashboardFooter } from './DashboardFooter';
import { DeckSkeleton } from './widgets/Skeleton';
import { DataSourcesPanel } from './datasources/DataSourcesPanel';
import { filterByMarket, type DataSourceMode, type Market } from './market';
import { useMockMarketDepth } from './mock/marketDepth';

const Grid = WidthProvider(Responsive);
const ROW_HEIGHT = 40;

const DEFAULT_ITEMS: Layout[] = [
  { i: 'overview', x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 3 },
  { i: 'price', x: 0, y: 3, w: 7, h: 8, minW: 4, minH: 6 },
  { i: 'movers', x: 7, y: 3, w: 5, h: 8, minW: 3, minH: 6 },
  { i: 'heat', x: 0, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
  { i: 'sectorVolume', x: 6, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
  { i: 'graph', x: 0, y: 19, w: 7, h: 7, minW: 4, minH: 5 },
  { i: 'feed', x: 7, y: 19, w: 5, h: 7, minW: 3, minH: 5 },
];

function ensureCoreItems(layout: Layout[]): Layout[] {
  const source = layout.length > 0 ? layout : DEFAULT_ITEMS;
  const currentById = new Map(source.map((item) => [item.i, item]));
  return DEFAULT_ITEMS.map((defaults) => ({
    ...(currentById.get(defaults.i) ?? defaults),
    x: defaults.x,
    y: defaults.y,
    w: defaults.w,
    h: defaults.h,
    minW: defaults.minW,
    minH: defaults.minH,
  }));
}

export function DashboardPage(): JSX.Element {
  const [symbol, setSymbol] = useState<string>(LIVE_SYMBOL);
  const [market, setMarket] = useState<Market>('cn');
  const [sourceMode, setSourceMode] = useState<DataSourceMode>('auto');
  const [selectedSectorId, setSelectedSectorId] = useState<string | null>(null);
  const [popupSectorId, setPopupSectorId] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [editing, setEditing] = useState(false);
  // auto 模式用前端本地 mock sectors；eastmoney 模式调后端
  const isMockDepth = sourceMode === 'auto';
  const mockSectors = useMockMarketDepth(market, isMockDepth);
  const depthSource = sourceMode === 'eastmoney' ? 'eastmoney' : 'mock';
  const depth = useMarketDepth(depthSource, market, !isMockDepth);
  const sectors = isMockDepth ? mockSectors : depth.data?.sectors ?? [];
  const { data: tickers } = useTickers();
  const marketTickers = useMemo(
    () => filterByMarket(tickers, market, sourceMode),
    [market, sourceMode, tickers],
  );
  const liveSymbols = useMemo(
    () => marketTickers.map((t) => t.symbol).slice(0, 5),
    [marketTickers],
  );
  const popupSector = sectors.find((s) => s.id === popupSectorId) ?? null;
  useTickStream(symbol);

  useEffect(() => {
    if (liveSymbols.length === 0 || liveSymbols.includes(symbol)) return;
    setSymbol(liveSymbols[0]);
  }, [liveSymbols, symbol]);

  const { data: serverLayout, isLoading: layoutLoading } = useDashboardLayout();
  const save = useSaveLayout();
  const [items, setItems] = useState<Layout[]>([]);

  useEffect(() => {
    if (serverLayout && !editing) setItems(ensureCoreItems(serverLayout.items as Layout[]));
  }, [serverLayout, editing]);

  const onLayoutChange = (next: Layout[]): void => {
    if (editing) setItems(next);
  };

  const handleSave = (): void => {
    const layout: DashboardLayout = {
      items: items.map((l) => ({ i: l.i, x: l.x, y: l.y, w: l.w, h: l.h, minW: l.minW, minH: l.minH })),
    };
    save.mutate(layout);
    setEditing(false);
  };
  const handleReset = (): void => {
    if (serverLayout) setItems(ensureCoreItems(serverLayout.items as Layout[]));
    setEditing(false);
  };

  const cards: Record<string, JSX.Element> = {
    overview: (
      <MarketOverview
        market={market}
        sourceMode={sourceMode}
        sectors={sectors}
        loading={!isMockDepth && depth.isLoading}
        delayed={depth.data?.delayed ?? false}
      />
    ),
    price: (
      <TopWinsCard
        symbol={symbol}
        onSymbolChange={setSymbol}
        symbols={liveSymbols}
        sourceMode={sourceMode}
      />
    ),
    movers: <MoversBar market={market} sourceMode={sourceMode} tickers={marketTickers} />,
    heat: (
      <Heatmap
        market={market}
        sourceMode={sourceMode}
        sectors={sectors}
        loading={!isMockDepth && depth.isLoading}
        selectedSectorId={selectedSectorId}
        onSectorSelect={(id) => {
          setSelectedSectorId(id);
          setPopupSectorId(id);
        }}
      />
    ),
    sectorVolume: (
      <SectorTurnoverPanel
        market={market}
        sourceMode={sourceMode}
        sectors={sectors}
        loading={!isMockDepth && depth.isLoading}
        selectedSectorId={selectedSectorId}
        onSectorSelect={(id) => {
          setSelectedSectorId(id);
          setPopupSectorId(id);
        }}
      />
    ),
    graph: <RelationshipGraph />,
    feed: <FeedList />,
  };

  return (
    <div className="min-h-screen bg-bg text-fg">
      {showSources && <DataSourcesPanel onClose={() => setShowSources(false)} />}
      {popupSector && (
        <SectorStockPopup sector={popupSector} onClose={() => setPopupSectorId(null)} />
      )}
      <div className="w-full px-4 py-3">
        <DashboardHeader
          onOpenSources={() => setShowSources(true)}
          editing={editing}
          onToggleEdit={() => setEditing(true)}
          onSaveLayout={handleSave}
          onResetLayout={handleReset}
          market={market}
          onMarketChange={setMarket}
          sourceMode={sourceMode}
          onSourceModeChange={setSourceMode}
        />
        <div className="mt-3 flex justify-end">
          <span className="text-muted text-[10px] uppercase tracking-[0.15em]">
            行情数据 · {sourceMode === 'auto' ? '自动' : sourceMode === 'eastmoney' ? '东方财富' : sourceMode.toUpperCase()}
          </span>
        </div>
        {layoutLoading && items.length === 0 ? (
          <DeckSkeleton />
        ) : (
          <Grid
            className={`mt-3 ${editing ? 'rgl-editing' : ''}`}
            layouts={{ lg: items, md: items, sm: items }}
            breakpoints={{ lg: 996, md: 768, sm: 0 }}
            cols={{ lg: 12, md: 12, sm: 1 }}
            rowHeight={ROW_HEIGHT}
            isDraggable={editing}
            isResizable={editing}
            onLayoutChange={onLayoutChange}
            draggableHandle=".card-drag-handle"
            margin={[12, 12]}
          >
            {items
              .filter((l) => cards[l.i])
              .map((l) => (
                <div key={l.i} className="h-full">
                  {cards[l.i]}
                </div>
              ))}
          </Grid>
        )}
        <DashboardFooter />
      </div>
    </div>
  );
}

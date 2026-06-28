import { useEffect, useState } from 'react';
import { Responsive, WidthProvider, type Layout } from 'react-grid-layout';
import type { DashboardLayout } from '@tradeck/shared';
import { useTickStream } from '../api/useTickStream';
import { useDashboardLayout, useSaveLayout } from '../api/useDashboardLayout';
import { LIVE_SYMBOL } from './mock/dashboardData';
import { DashboardHeader } from './DashboardHeader';
import { MarketOverview } from './MarketOverview';
import { TopWinsCard } from './TopWinsCard';
import { MoversBar } from './MoversBar';
import { Heatmap } from './Heatmap';
import { RelationshipGraph } from './RelationshipGraph';
import { FeedList } from './FeedList';
import { DashboardFooter } from './DashboardFooter';
import { DeckSkeleton } from './widgets/Skeleton';
import { MarketTabs } from './widgets/MarketTabs';
import { DataSourcesPanel } from './datasources/DataSourcesPanel';
import type { Market } from './market';

const Grid = WidthProvider(Responsive);
const ROW_HEIGHT = 40;

export function DashboardPage(): JSX.Element {
  const [symbol, setSymbol] = useState<string>(LIVE_SYMBOL);
  const [market, setMarket] = useState<Market>('cn');
  const [showSources, setShowSources] = useState(false);
  const [editing, setEditing] = useState(false);
  useTickStream(symbol);

  const { data: serverLayout, isLoading: layoutLoading } = useDashboardLayout();
  const save = useSaveLayout();
  const [items, setItems] = useState<Layout[]>([]);

  useEffect(() => {
    if (serverLayout && !editing) setItems(serverLayout.items as Layout[]);
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
    if (serverLayout) setItems(serverLayout.items as Layout[]);
    setEditing(false);
  };

  const cards: Record<string, JSX.Element> = {
    overview: <MarketOverview market={market} />,
    price: <TopWinsCard symbol={symbol} onSymbolChange={setSymbol} />,
    movers: <MoversBar market={market} />,
    heat: <Heatmap market={market} />,
    graph: <RelationshipGraph />,
    feed: <FeedList />,
  };

  return (
    <div className="min-h-screen bg-bg text-fg">
      {showSources && <DataSourcesPanel onClose={() => setShowSources(false)} />}
      <div className="w-full px-4 py-3">
        <DashboardHeader
          onOpenSources={() => setShowSources(true)}
          editing={editing}
          onToggleEdit={() => setEditing(true)}
          onSaveLayout={handleSave}
          onResetLayout={handleReset}
        />
        <div className="mt-3 flex items-center justify-between">
          <MarketTabs value={market} onChange={setMarket} />
          <span className="text-muted text-[10px] uppercase tracking-[0.15em]">
            行情数据 · 东方财富（非交易时段回退 mock）
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

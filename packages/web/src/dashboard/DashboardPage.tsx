import { useEffect, useState } from 'react';
import { Responsive, WidthProvider, type Layout } from 'react-grid-layout';
import type { DashboardLayout } from '@tradeck/shared';
import { useTickStream } from '../api/useTickStream';
import { useDashboardLayout, useSaveLayout } from '../api/useDashboardLayout';
import { LIVE_SYMBOL } from './mock/dashboardData';
import { DashboardHeader } from './DashboardHeader';
import { PnlCard } from './PnlCard';
import { TopWinsCard } from './TopWinsCard';
import { ProbabilityLattice } from './ProbabilityLattice';
import { TailRidge } from './TailRidge';
import { RelationshipGraph } from './RelationshipGraph';
import { FeedList } from './FeedList';
import { DashboardFooter } from './DashboardFooter';
import { DataSourcesPanel } from './datasources/DataSourcesPanel';

const Grid = WidthProvider(Responsive);
const ROW_HEIGHT = 40;

export function DashboardPage(): JSX.Element {
  const [symbol, setSymbol] = useState<string>(LIVE_SYMBOL);
  const [showSources, setShowSources] = useState(false);
  const [editing, setEditing] = useState(false);
  useTickStream(symbol);

  const { data: serverLayout } = useDashboardLayout();
  const save = useSaveLayout();
  const [items, setItems] = useState<Layout[]>([]);

  // sync local layout from server when (re)loaded and not actively editing
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
    pnl: <PnlCard />,
    topwins: <TopWinsCard symbol={symbol} onSymbolChange={setSymbol} />,
    lattice: <ProbabilityLattice />,
    ridge: <TailRidge />,
    graph: <RelationshipGraph />,
    feed: <FeedList />,
  };

  return (
    <div className="min-h-screen bg-bg text-fg">
      {showSources && <DataSourcesPanel onClose={() => setShowSources(false)} />}
      <div className="max-w-[1400px] mx-auto px-4 py-3">
        <DashboardHeader
          onOpenSources={() => setShowSources(true)}
          editing={editing}
          onToggleEdit={() => setEditing(true)}
          onSaveLayout={handleSave}
          onResetLayout={handleReset}
        />
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
          {items.map((l) => (
            <div key={l.i} className="h-full">
              {cards[l.i] ?? null}
            </div>
          ))}
        </Grid>
        <DashboardFooter />
      </div>
    </div>
  );
}

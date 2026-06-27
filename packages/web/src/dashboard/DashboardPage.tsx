import { useState } from 'react';
import { useTickStream } from '../api/useTickStream';
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

export function DashboardPage(): JSX.Element {
  const [symbol, setSymbol] = useState<string>(LIVE_SYMBOL);
  const [showSources, setShowSources] = useState(false);
  // Live tick subscription follows the selected symbol (SSE -> Zustand).
  useTickStream(symbol);

  return (
    <div className="min-h-screen bg-bg text-fg">
      {showSources && <DataSourcesPanel onClose={() => setShowSources(false)} />}
      <div className="max-w-[1400px] mx-auto px-4 py-3 flex flex-col gap-3">
        <DashboardHeader onOpenSources={() => setShowSources(true)} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <PnlCard />
          <TopWinsCard symbol={symbol} onSymbolChange={setSymbol} />
        </div>
        <ProbabilityLattice />
        <TailRidge />
        <RelationshipGraph />
        <FeedList />
        <DashboardFooter />
      </div>
    </div>
  );
}

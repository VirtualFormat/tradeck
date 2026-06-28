import type { CSSProperties, ReactNode } from 'react';

/** A single shimmering placeholder block. Sizing via className or style. */
export function Skeleton({
  className,
  style,
}: {
  className?: string;
  style?: CSSProperties;
}): JSX.Element {
  return <div className={`skeleton ${className ?? ''}`} style={style} />;
}

/** Grid of ticker-card placeholders matching MarketOverview's layout. */
export function CardGridSkeleton({ count = 6 }: { count?: number }): JSX.Element {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-panel-2 border border-border rounded-md p-2.5">
          <div className="flex items-center justify-between">
            <Skeleton className="h-2.5 w-14" />
            <Skeleton className="h-2.5 w-8" />
          </div>
          <Skeleton className="h-5 w-24 mt-2" />
          <Skeleton className="h-2 w-10 mt-2" />
        </div>
      ))}
    </div>
  );
}

/** Horizontal-bar placeholders for MoversBar. */
export function BarsSkeleton({ count = 6 }: { count?: number }): JSX.Element {
  // descending widths read like a sorted ranking
  const widths = ['90%', '74%', '58%', '46%', '34%', '22%'];
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-2">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-2.5 w-16 shrink-0" />
          <Skeleton className="h-4" style={{ width: widths[i % widths.length] }} />
        </div>
      ))}
    </div>
  );
}

/** Treemap-ish tile placeholders for Heatmap. */
export function TilesSkeleton(): JSX.Element {
  return (
    <div className="grid h-full grid-cols-3 grid-rows-2 gap-1.5">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="rounded" />
      ))}
    </div>
  );
}

/** News-row placeholders for FeedList. */
export function FeedSkeleton({ count = 6 }: { count?: number }): JSX.Element {
  return (
    <div className="divide-y divide-border/50">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="py-2.5">
          <div className="flex items-start justify-between gap-2">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-2.5 w-6 shrink-0" />
          </div>
          <div className="mt-2 flex gap-2">
            <Skeleton className="h-2 w-16" />
            <Skeleton className="h-2 w-10" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Full-area chart placeholder (used while OHLCV history loads). */
export function ChartSkeleton(): JSX.Element {
  return (
    <div className="flex h-full w-full items-end gap-1 px-2 pb-6 pt-2">
      {Array.from({ length: 28 }).map((_, i) => {
        // pseudo-random but stable heights for a candle silhouette
        const h = 30 + ((i * 37) % 60);
        return <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />;
      })}
    </div>
  );
}

/** A blank panel chrome (border + header rule) wrapping skeleton body. */
function PanelShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <div
      className={`panel-surface border border-border rounded-card px-3.5 py-2.5 flex flex-col ${className ?? ''}`}
    >
      <div className="mb-2.5 shrink-0 border-b border-border/60 pb-2">
        <Skeleton className="h-3 w-32" />
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * Whole-deck placeholder shown before the saved layout arrives. Mirrors the
 * default 12-col proportions (overview row, 7/5 split ×2, full-width graph).
 */
export function DeckSkeleton(): JSX.Element {
  return (
    <div className="mt-3 flex flex-col gap-3">
      <PanelShell className="h-[180px]">
        <CardGridSkeleton />
      </PanelShell>
      <div className="flex gap-3">
        <PanelShell className="h-[300px] flex-[7]">
          <ChartSkeleton />
        </PanelShell>
        <PanelShell className="h-[300px] flex-[5]">
          <BarsSkeleton />
        </PanelShell>
      </div>
      <div className="flex gap-3">
        <PanelShell className="h-[260px] flex-[7]">
          <TilesSkeleton />
        </PanelShell>
        <PanelShell className="h-[260px] flex-[5]">
          <FeedSkeleton count={5} />
        </PanelShell>
      </div>
      <PanelShell className="h-[260px]">
        <Skeleton className="h-full w-full" />
      </PanelShell>
    </div>
  );
}

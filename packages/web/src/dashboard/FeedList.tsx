import { Card } from './widgets/Card';
import { FeedSkeleton } from './widgets/Skeleton';
import { useFeed } from '../api/useFeed';

function relTime(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function FeedList(): JSX.Element {
  const { data, isLoading } = useFeed(30);

  return (
    <Card title="资讯流" subtitle="News Feed" corner="polling 10s" scroll>
      {isLoading && <FeedSkeleton count={7} />}
      <div className="divide-y divide-border/50">
        {!isLoading && (data?.length ?? 0) === 0 && (
          <div className="text-muted text-xs py-3">no items yet</div>
        )}
        {data?.map((item) => (
          <a
            key={`${item.source}:${item.id}`}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="group block py-2 hover:bg-panel-2 -mx-1.5 px-1.5 rounded transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-fg-dim text-xs leading-snug group-hover:text-fg transition-colors">
                {item.title}
              </span>
              <span className="tab-nums text-muted text-[10px] shrink-0 pt-0.5">
                {relTime(item.publishedAt)}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-muted text-[9.5px] uppercase tracking-wider">{item.source}</span>
              {item.tags?.map((t) => (
                <span
                  key={t}
                  className="text-accent/90 text-[9.5px] border border-accent/25 bg-accent/5 rounded px-1"
                >
                  {t}
                </span>
              ))}
            </div>
          </a>
        ))}
      </div>
    </Card>
  );
}

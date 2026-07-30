import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getAggregatedNews } from "@/lib/openbb";
import type { NewsArticle } from "@/lib/openbb";

const DASHBOARD_NEWS_SYMBOLS = [
  "NVDA",
  "AAPL",
  "600519.SH",
  "300750.SZ",
];

function validNews(article: NewsArticle): boolean {
  return Boolean(article.title?.trim() && article.url?.trim());
}

export async function DashboardNews() {
  const articles = await getAggregatedNews(DASHBOARD_NEWS_SYMBOLS, 2).catch(
    () => [] as NewsArticle[]
  );
  const seenUrls = new Set<string>();
  const topNews = articles
    .filter(validNews)
    .filter((article) => {
      if (seenUrls.has(article.url)) return false;
      seenUrls.add(article.url);
      return true;
    })
    .slice(0, 5);

  return (
    <Card size="sm" className="min-h-0 flex-1 gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          热门资讯
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground">
          美股 / A股
        </CardAction>
      </CardHeader>
      <CardContent className="px-3.5">
        {topNews.length > 0 ? (
          <div className="flex flex-col">
            {topNews.map((article) => (
              <a
                key={`${article.symbol}-${article.url}`}
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex min-h-10 items-start gap-2 border-b border-border/60 py-1.5 transition-colors last:border-b-0 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <Badge
                  variant="secondary"
                  className="mt-0.5 h-4 max-w-20 shrink-0 rounded-sm px-1.5 py-0 text-[10px] font-medium text-up"
                >
                  <span className="truncate">{article.symbol}</span>
                </Badge>
                <span className="line-clamp-2 min-w-0 flex-1 text-xs leading-4 text-fg-dim">
                  {article.title}
                </span>
              </a>
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="暂无热门资讯"
            className="min-h-44 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

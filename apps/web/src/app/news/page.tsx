/**
 * 新闻流页
 * 路由：/news
 * 默认聚合热门股新闻，支持按 symbol 查询
 */
import Link from "next/link";
import { getAggregatedNews, type NewsArticle } from "@/lib/openbb";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// 默认聚合的热门股票（覆盖美股科技 + 中国 ADR + 汽车）
const DEFAULT_SYMBOLS = [
  "AAPL",
  "MSFT",
  "NVDA",
  "TSLA",
  "AMZN",
  "GOOGL",
  "META",
  "BABA",
];

function fmtDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffH = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffH < 1) return "刚刚";
  if (diffH < 24) return `${diffH} 小时前`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 7) return `${diffD} 天前`;
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function NewsItem({ article }: { article: NewsArticle }) {
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block border-b border-border/50 py-3 transition-colors hover:bg-panel-2/50 -mx-2 px-2 rounded-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium leading-snug text-fg line-clamp-2">
            {article.title}
          </h3>
          {article.summary && (
            <p className="mt-1 text-xs text-fg-dim line-clamp-2">
              {article.summary}
            </p>
          )}
          <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted">
            <span>{article.publisher ?? article.source ?? "—"}</span>
            <span>·</span>
            <span>{fmtDate(article.date)}</span>
          </div>
        </div>
        {article.symbol && (
          <Badge variant="secondary" className="shrink-0">
            {article.symbol}
          </Badge>
        )}
      </div>
    </a>
  );
}

export default async function NewsPage({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}) {
  const { symbol } = await searchParams;

  let articles: NewsArticle[] = [];

  if (symbol) {
    // 按 symbol 查询
    articles = await getAggregatedNews([symbol.toUpperCase()], 20);
  } else {
    // 默认聚合
    articles = await getAggregatedNews(DEFAULT_SYMBOLS, 3);
  }

  return (
    <div className="px-4 lg:px-6">
      <div className="mx-auto max-w-3xl">
        {/* 快捷 symbol 切换 */}
        <div className="mb-4 flex flex-wrap gap-1.5">
          <Link href="/news">
            <Badge
              variant={!symbol ? "default" : "secondary"}
              className="cursor-pointer"
            >
              全部
            </Badge>
          </Link>
          {DEFAULT_SYMBOLS.map((s) => (
            <Link key={s} href={`/news?symbol=${s}`}>
              <Badge
                variant={symbol === s ? "default" : "secondary"}
                className="cursor-pointer"
              >
                {s}
              </Badge>
            </Link>
          ))}
        </div>

        {/* 新闻列表 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {articles.length > 0
                ? `${articles.length} 条新闻`
                : "无新闻数据"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {articles.length > 0 ? (
              articles.map((article, i) => (
                <NewsItem key={`${article.url}-${i}`} article={article} />
              ))
            ) : (
              <div className="py-8 text-center text-muted">
                无新闻数据
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

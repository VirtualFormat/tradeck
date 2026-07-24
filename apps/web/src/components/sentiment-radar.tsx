/**
 * 情绪雷达（首页用，服务端组件）
 * - 数据：backend /api/sentiment（6 维情绪评分）
 * - 渲染：Card + SentimentRadarChart（RadarChart）
 * - 评分档位（参照 tickflow）：≥70 强势 / ≥55 偏暖 / ≥45 震荡 / ≥30 偏冷 / <30 冰点
 */
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  SentimentRadarChart,
  type SentimentDim,
} from "@/components/sentiment-radar-chart";
import { EmptyState } from "@/components/empty-state";

interface SentimentData {
  score: number;
  dims: SentimentDim[];
}

async function fetchSentiment(): Promise<SentimentData> {
  try {
    const BACKEND_API_URL =
      process.env.BACKEND_API_URL ?? "http://localhost:8080";
    const res = await fetch(`${BACKEND_API_URL}/api/sentiment`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 300 },
    });
    if (!res.ok) return { score: 0, dims: [] };
    return await res.json();
  } catch {
    return { score: 0, dims: [] };
  }
}

function scoreLevel(score: number): { label: string; colorClass: string } {
  if (score >= 70) return { label: "强势", colorClass: "text-up" };
  if (score >= 55) return { label: "偏暖", colorClass: "text-warn" };
  if (score >= 45) return { label: "震荡", colorClass: "text-fg-dim" };
  if (score >= 30) return { label: "偏冷", colorClass: "text-accent" };
  return { label: "冰点", colorClass: "text-down" };
}

export async function SentimentRadar() {
  const data = await fetchSentiment();
  const level = scoreLevel(data.score);

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <div>
          <CardTitle className="text-base font-medium text-fg-dim">
            情绪雷达
          </CardTitle>
          <CardDescription>6 维市场情绪评分（0-100）</CardDescription>
        </div>
        <CardAction>
          <Badge variant="outline" className={level.colorClass}>
            {data.score} · {level.label}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {data.dims.length > 0 ? (
          <SentimentRadarChart dims={data.dims} />
        ) : (
          <EmptyState compact title="无数据" className="h-[220px]" />
        )}
      </CardContent>
    </Card>
  );
}

/**
 * 美债收益率曲线面板（服务端组件）
 * 曲线图（11 期限三条线）+ 10Y-2Y 利差面积图，标题右侧 Badge 显示当前利差
 */
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { EmptyState } from "@/components/empty-state";
import { YieldCurveChart } from "@/components/yield-curve-chart";
import { YieldSpreadChart } from "@/components/yield-spread-chart";
import { fetchYieldCurve, fetchYieldSpread } from "@/lib/openbb";

export async function YieldCurvePanel() {
  const [curve, spread] = await Promise.all([
    fetchYieldCurve(),
    fetchYieldSpread(365),
  ]);

  // 当前 10Y-2Y 利差（曲线值为 %，×100 转 bp）
  const y10 = curve.find((p) => p.tenor === "10Y")?.latest;
  const y2 = curve.find((p) => p.tenor === "2Y")?.latest;
  const spreadBp =
    y10 != null && y2 != null ? Math.round((y10 - y2) * 100) : null;

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base font-medium text-fg-dim">
            美债收益率曲线
          </CardTitle>
          {spreadBp != null &&
            (spreadBp < 0 ? (
              <Badge
                variant="secondary"
                className="text-up"
              >
                倒挂 {Math.abs(spreadBp)} bp
              </Badge>
            ) : (
              <Badge
                variant="secondary"
                className="text-down"
              >
                利差 {spreadBp} bp
              </Badge>
            ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {curve.length === 0 && spread.length === 0 ? (
          <EmptyState compact title="无数据" />
        ) : (
          <>
            <YieldCurveChart data={curve} />
            <Separator />
            <div>
              <div className="mb-2 text-xs text-muted">10Y-2Y 利差走势（近一年，bp）</div>
              <YieldSpreadChart data={spread} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

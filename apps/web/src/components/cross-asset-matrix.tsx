/**
 * 跨资产总览矩阵（服务端组件）
 * 数据：backend /api/cross-assets（股指/商品/汇率/波动率/债券，分组小标题行）
 */
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";
import { fetchCrossAssets, type CrossAssetItem } from "@/lib/openbb";
import { cn } from "@/lib/utils";

// 分组小标题（category 固定顺序）
const CATEGORY_LABELS: Record<CrossAssetItem["category"], string> = {
  equity_index: "股指",
  commodity: "商品",
  fx: "汇率",
  volatility: "波动率",
  bond: "债券",
};
const CATEGORY_ORDER: CrossAssetItem["category"][] = [
  "equity_index",
  "commodity",
  "fx",
  "volatility",
  "bond",
];

// 债券行单位标注（10Y/2Y 为 %，利差为 bp）
const BOND_UNITS: Record<string, string> = {
  US10Y: "%",
  US2Y: "%",
  US10Y2Y: "bp",
};

function fmtClose(v: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** 涨跌着色：正红负绿（A 股习惯），null 置灰 */
function ChangeCell({
  value,
  suffix = "%",
  digits = 2,
}: {
  value: number | null;
  suffix?: string;
  digits?: number;
}) {
  if (value == null) {
    return <TableCell className="text-right text-muted-foreground">—</TableCell>;
  }
  return (
    <TableCell
      className={cn(
        "text-right tabular-nums",
        value > 0 && "text-up",
        value < 0 && "text-down"
      )}
    >
      {value > 0 ? "+" : ""}
      {value.toFixed(digits)}
      {suffix}
    </TableCell>
  );
}

export async function CrossAssetMatrix() {
  const items = await fetchCrossAssets();

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          跨资产总览
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyState compact title="无数据" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead className="text-right">最新</TableHead>
                <TableHead className="text-right">1D</TableHead>
                <TableHead className="text-right">1W</TableHead>
                <TableHead className="text-right">1M</TableHead>
                <TableHead className="text-right">3M</TableHead>
                <TableHead className="text-right">1Y</TableHead>
                <TableHead className="text-right">距MA200</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {CATEGORY_ORDER.map((cat) => {
                const rows = items.filter((i) => i.category === cat);
                if (rows.length === 0) return null;
                return [
                  // 分组跨列小标题行
                  <TableRow key={`group-${cat}`} className="hover:bg-transparent">
                    <TableCell
                      colSpan={8}
                      className="bg-muted/30 py-1 text-xs font-medium text-fg-dim"
                    >
                      {CATEGORY_LABELS[cat]}
                    </TableCell>
                  </TableRow>,
                  ...rows.map((item) => {
                    const unit = BOND_UNITS[item.symbol];
                    const isSpread = item.symbol === "US10Y2Y";
                    return (
                      <TableRow key={item.symbol}>
                        <TableCell className="font-medium">
                          {item.name}
                          {unit && (
                            <Badge
                              variant="secondary"
                              className="ml-1.5 px-1 text-[10px]"
                            >
                              {unit}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtClose(item.close)}
                        </TableCell>
                        {/* 债券行为差值（pp/bp），其余为变化率 % */}
                        {item.category === "bond" ? (
                          <>
                            <ChangeCell value={item.chg_1d} suffix="" digits={isSpread ? 1 : 2} />
                            <ChangeCell value={item.chg_1w} suffix="" digits={isSpread ? 1 : 2} />
                            <ChangeCell value={item.chg_1m} suffix="" digits={isSpread ? 1 : 2} />
                            <ChangeCell value={item.chg_3m} suffix="" digits={isSpread ? 1 : 2} />
                            <ChangeCell value={item.chg_1y} suffix="" digits={isSpread ? 1 : 2} />
                          </>
                        ) : (
                          <>
                            <ChangeCell value={item.chg_1d} />
                            <ChangeCell value={item.chg_1w} />
                            <ChangeCell value={item.chg_1m} />
                            <ChangeCell value={item.chg_3m} />
                            <ChangeCell value={item.chg_1y} />
                          </>
                        )}
                        <ChangeCell value={item.dist_ma200} />
                      </TableRow>
                    );
                  }),
                ];
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

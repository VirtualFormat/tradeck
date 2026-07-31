import { EmptyState } from "@/components/empty-state";
import { MarketSummaryCard } from "@/components/markets-v3/market-summary-card";
import { Badge } from "@/components/ui/badge";
import { fmtDataDate } from "@/lib/format";
import type { CrossAssetItem } from "@/lib/openbb";
import { cn } from "@/lib/utils";

const SECTOR_ETFS = [
  { symbol: "XLK", name: "科技" },
  { symbol: "XLF", name: "金融" },
  { symbol: "XLE", name: "能源" },
  { symbol: "XLV", name: "医疗" },
  { symbol: "XLU", name: "公用事业" },
  { symbol: "XLY", name: "可选消费" },
  { symbol: "XLP", name: "必选消费" },
  { symbol: "XLI", name: "工业" },
];

function signedPercent(value: number | null): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function changeClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

export function SectorRotation({ items }: { items: CrossAssetItem[] }) {
  const rows = SECTOR_ETFS.map((sector) => {
    const item = items.find((candidate) => candidate.symbol === sector.symbol);
    return item ? { ...sector, item } : null;
  }).filter(
    (
      row
    ): row is {
      symbol: string;
      name: string;
      item: CrossAssetItem;
    } => Boolean(row)
  );

  const latestDate = rows
    .map((row) => row.item.latest_date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  return (
    <MarketSummaryCard
      title="板块轮动"
      description="Sector ETF · 1D / 1W"
      action={
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="text-[10px]">
            {rows.length}/{SECTOR_ETFS.length} 覆盖
          </Badge>
          <Badge variant="secondary" className="text-[10px] tabular-nums">
            {fmtDataDate(latestDate) ?? "等待覆盖"}
          </Badge>
        </div>
      }
    >
      {rows.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {rows.map(({ symbol, name, item }) => (
            <div
              key={symbol}
              className="min-w-0 rounded-lg bg-secondary px-3 py-2.5"
            >
              <div className="truncate text-[10px] text-muted-foreground">
                {name} {symbol}
              </div>
              <div
                className={cn(
                  "mt-1 text-sm font-semibold tabular-nums",
                  changeClass(item.chg_1d)
                )}
              >
                {signedPercent(item.chg_1d)}
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground tabular-nums">
                1W {signedPercent(item.chg_1w)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="暂无 Sector ETF 数据"
          description="当前 /api/cross-assets 尚未覆盖 XLK、XLF、XLE 等行业 ETF；此处不使用设计示例值"
          className="min-h-24 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}

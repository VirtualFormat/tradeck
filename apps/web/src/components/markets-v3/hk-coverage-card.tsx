import { WarningCircleIcon } from "@phosphor-icons/react/dist/ssr";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface HkCoverageCardProps {
  variant?: "notice" | "summary" | "detail";
  className?: string;
}

const COVERAGE_GAPS = [
  "行业热力：等待可靠港股行业源",
  "主板成交额：等待全市场行情源",
  "南向资金：等待港股通数据源",
];

/** 港股 V3 覆盖说明：只描述真实覆盖，缺失数据不使用估算值填充。 */
export function HkCoverageCard({
  variant = "detail",
  className,
}: HkCoverageCardProps) {
  if (variant === "notice") {
    return (
      <Card
        size="sm"
        className={cn(
          "gap-2 border-warn/25 bg-warn/5 py-3 ring-warn/15",
          className
        )}
      >
        <CardHeader className="grid-cols-[auto_1fr] items-start gap-x-2 px-3">
          <WarningCircleIcon
            className="mt-0.5 size-4 text-warn"
            aria-hidden
          />
          <div className="min-w-0">
            <CardTitle className="text-xs text-warn">
              当前定位：指数 + 12 只代表标的
            </CardTitle>
            <CardDescription className="mt-1 text-[11px] leading-4">
              非全市场榜单；行业、主板成交额与南向资金等待可靠数据源。
            </CardDescription>
          </div>
        </CardHeader>
      </Card>
    );
  }

  if (variant === "summary") {
    return (
      <Card
        size="sm"
        className={cn("h-full gap-3 py-3.5", className)}
      >
        <CardHeader className="gap-1 px-3.5">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-sm">数据覆盖</CardTitle>
            <Badge variant="secondary" className="text-[10px]">
              12 只代表标的
            </Badge>
          </div>
          <CardDescription className="text-xs">
            港股指数与代表标的观察页
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 px-3.5 text-xs">
          <div className="rounded-lg bg-secondary px-3 py-2.5">
            <div className="text-muted-foreground">指数</div>
            <div className="mt-1 font-medium text-foreground">
              恒指 / 国企
            </div>
          </div>
          <div className="rounded-lg bg-secondary px-3 py-2.5">
            <div className="text-muted-foreground">报价</div>
            <div className="mt-1 font-medium text-foreground">12 只代表标的</div>
          </div>
          <div className="rounded-lg bg-warn/10 px-3 py-2.5">
            <div className="text-muted-foreground">行业与资金</div>
            <div className="mt-1 font-medium text-warn">等待可靠数据源</div>
          </div>
          <div className="rounded-lg bg-secondary px-3 py-2.5">
            <div className="text-muted-foreground">新闻</div>
            <div className="mt-1 font-medium text-foreground">当前覆盖有限</div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      size="sm"
      className={cn(
        "gap-3 border-warn/20 bg-warn/5 py-3 ring-warn/15",
        className
      )}
    >
      <CardHeader className="gap-1 px-3.5">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">覆盖说明</CardTitle>
          <Badge
            variant="outline"
            className="border-warn/30 text-[10px] text-warn"
          >
            非全市场
          </Badge>
        </div>
        <CardDescription className="text-xs leading-5">
          当前只展示港股指数、日 K 市场宽度与 12 只代表标的报价。
        </CardDescription>
      </CardHeader>
      <CardContent className="px-3.5">
        <ul className="space-y-2 text-xs leading-4 text-warn">
          {COVERAGE_GAPS.map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden className="mt-1 size-1.5 shrink-0 rounded-full bg-warn" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

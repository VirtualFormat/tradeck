/** 宏观工作区：事件日历视图（财报与未来宏观发布）。 */
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
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
import {
  fetchEarningsCalendar,
  fetchEconomicCalendar,
} from "@/lib/openbb";

function fmtCalDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
}

function fmtSession(session: string | null): string {
  if (session === "BMO") return "盘前";
  if (session === "AMC") return "盘后";
  return "—";
}

function importanceClass(importance: string | null): string {
  if (importance === "高" || importance === "high") return "text-up";
  if (importance === "中" || importance === "medium") return "text-warn";
  return "text-muted-foreground";
}

export async function MacroEventsSection() {
  const [earnings, econEvents] = await Promise.all([
    fetchEarningsCalendar(14).catch(() => []),
    fetchEconomicCalendar(7).catch(() => []),
  ]);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">财报日历（未来 14 天）</CardTitle>
        </CardHeader>
        <CardContent>
          {earnings.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>代码</TableHead>
                  <TableHead>时段</TableHead>
                  <TableHead className="text-right">EPS 预期</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {earnings.map((item) => (
                  <TableRow key={`${item.symbol}-${item.report_date}`}>
                    <TableCell className="tab-nums whitespace-nowrap">
                      {fmtCalDate(item.report_date)}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/stocks/${item.symbol}`}
                        className="font-medium hover:text-accent"
                      >
                        {item.symbol}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtSession(item.session)}
                    </TableCell>
                    <TableCell className="text-right tab-nums">
                      {item.eps_estimate != null
                        ? item.eps_estimate.toFixed(2)
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">宏观事件日历（未来 7 天）</CardTitle>
        </CardHeader>
        <CardContent>
          {econEvents.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead>国家</TableHead>
                  <TableHead>事件</TableHead>
                  <TableHead>重要性</TableHead>
                  <TableHead className="text-right">预期</TableHead>
                  <TableHead className="text-right">前值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {econEvents.map((item, idx) => (
                  <TableRow key={`${item.event_date}-${item.event_name}-${idx}`}>
                    <TableCell className="tab-nums whitespace-nowrap">
                      {fmtCalDate(item.event_date)}
                    </TableCell>
                    <TableCell className="tab-nums text-muted-foreground">
                      {item.event_time ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {item.country ?? "—"}
                    </TableCell>
                    <TableCell>{item.event_name}</TableCell>
                    <TableCell className={importanceClass(item.importance)}>
                      {item.importance ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tab-nums">
                      {item.forecast ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tab-nums text-muted-foreground">
                      {item.previous ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

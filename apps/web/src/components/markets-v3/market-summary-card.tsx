import type { ReactNode } from "react";

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MarketSummaryCardProps {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

/** V3 市场页通用内容卡，统一标题、说明和响应式内边距。 */
export function MarketSummaryCard({
  title,
  description,
  action,
  children,
  className,
  contentClassName,
}: MarketSummaryCardProps) {
  return (
    <Card className={cn("min-w-0 gap-3 py-3.5 md:py-4", className)}>
      <CardHeader className="gap-0.5 px-3.5 md:px-4">
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className={cn("min-w-0 px-3.5 md:px-4", contentClassName)}>
        {children}
      </CardContent>
    </Card>
  );
}

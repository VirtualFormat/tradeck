/**
 * 全站统一空态入口（ui/empty 薄封装，phosphor 图标）
 * 规则：任何「暂无数据」场景一律使用本组件，禁止手写空态 div
 * 无 "use client" 的纯展示组件：server / client 组件均可使用
 * （图标走 phosphor SSR 入口：主入口的 csr 模块含 createContext，RSC 层会崩）
 */
import { TrayIcon } from "@phosphor-icons/react/dist/ssr";

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title?: string;
  description?: string;
  className?: string;
  /** 紧凑变体：固定高度图表槽 / 小卡片内使用，缩小图标与间距，避免撑破布局 */
  compact?: boolean;
  /** 条带内联变体：不显示图标，仅保留一行文字 */
  inline?: boolean;
}

export function EmptyState({
  title = "暂无数据",
  description,
  className,
  compact = false,
  inline = false,
}: EmptyStateProps) {
  return (
    <Empty
      className={cn(
        compact && "gap-2 p-2 md:p-2",
        inline && "min-h-0 flex-none items-start p-0 text-left",
        className
      )}
    >
      <EmptyHeader
        className={cn(
          compact && "gap-1",
          inline && "max-w-none flex-row items-center gap-1"
        )}
      >
        {!inline && (
          <EmptyMedia
            variant="icon"
            className={cn(compact && "size-7 [&_svg]:size-4")}
          >
            <TrayIcon />
          </EmptyMedia>
        )}
        <EmptyTitle
          className={cn(
            compact && "text-xs font-normal text-muted-foreground",
            inline && "text-xs font-normal text-muted-foreground"
          )}
        >
          {title}
        </EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
    </Empty>
  );
}

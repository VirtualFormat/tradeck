import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface MarketPageShellProps {
  toolbar: ReactNode;
  indices?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

/**
 * 市场页 V3 共享外壳。
 *
 * Sidebar 由根布局统一提供；这里仅负责页面内容宽度、留白和纵向节奏。
 */
export function MarketPageShell({
  toolbar,
  indices,
  children,
  className,
  contentClassName,
}: MarketPageShellProps) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full min-w-0 max-w-[1600px] flex-col gap-4 px-3 sm:px-4 md:gap-5 lg:px-6 xl:gap-6",
        className
      )}
    >
      {toolbar}
      {indices}
      <div
        className={cn(
          "flex min-w-0 flex-col gap-4 md:gap-5 xl:gap-6",
          contentClassName
        )}
      >
        {children}
      </div>
    </div>
  );
}

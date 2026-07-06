/**
 * 统一页头组件（借鉴 TickFlow PageHeader）
 */
import { type ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}

export function PageHeader({ title, subtitle, right }: PageHeaderProps) {
  return (
    <header className="mb-6 flex items-end justify-between border-b border-border pb-3">
      <div>
        <h1 className="text-lg font-semibold tracking-wide">{title}</h1>
        {subtitle && (
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-muted">
            {subtitle}
          </p>
        )}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </header>
  );
}

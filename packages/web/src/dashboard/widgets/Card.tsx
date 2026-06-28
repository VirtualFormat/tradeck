import type { ReactNode } from 'react';

interface Props {
  title?: string;
  /** Short English subtitle shown next to the title. */
  subtitle?: string;
  /** Mark panels backed by mock/placeholder data. */
  demo?: boolean;
  corner?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ title, subtitle, demo, corner, className, children }: Props): JSX.Element {
  return (
    <section
      className={`bg-panel border border-border rounded-card p-4 h-full overflow-hidden flex flex-col ${className ?? ''}`}
    >
      {(title || corner) && (
        // header doubles as the grid drag handle (active only in edit mode)
        <header className="card-drag-handle flex items-center justify-between mb-3 shrink-0 gap-2">
          <div className="flex items-baseline gap-2 min-w-0">
            {title && <h2 className="text-fg text-[12px] tracking-wide truncate">{title}</h2>}
            {subtitle && (
              <span className="text-muted text-[10px] uppercase tracking-[0.15em] truncate">
                {subtitle}
              </span>
            )}
            {demo && (
              <span className="shrink-0 text-[9px] uppercase tracking-wider text-muted border border-border rounded px-1">
                demo
              </span>
            )}
          </div>
          {corner && <div className="text-muted text-[11px] shrink-0">{corner}</div>}
        </header>
      )}
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </section>
  );
}

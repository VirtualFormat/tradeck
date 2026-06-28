import type { ReactNode } from 'react';

interface Props {
  title?: string;
  /** Short English subtitle shown next to the title. */
  subtitle?: string;
  /** Mark panels backed by mock/placeholder data. */
  demo?: boolean;
  /** Allow the body to scroll (only the feed needs this); default fits/clips. */
  scroll?: boolean;
  corner?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({
  title,
  subtitle,
  demo,
  scroll,
  corner,
  className,
  children,
}: Props): JSX.Element {
  return (
    <section
      className={`panel-surface border border-border rounded-card px-3.5 py-2.5 h-full overflow-hidden flex flex-col ${className ?? ''}`}
    >
      {(title || corner) && (
        // header doubles as the grid drag handle (active only in edit mode)
        <header className="card-drag-handle flex items-center justify-between mb-2.5 shrink-0 gap-2 border-b border-border/60 pb-2">
          <div className="flex items-baseline gap-2 min-w-0">
            {title && (
              <h2 className="text-fg text-[12.5px] font-medium tracking-wide truncate">{title}</h2>
            )}
            {subtitle && (
              <span className="text-muted text-[9.5px] uppercase tracking-[0.18em] truncate">
                {subtitle}
              </span>
            )}
            {demo && (
              <span className="shrink-0 text-[8.5px] uppercase tracking-wider text-accent/80 border border-accent/30 bg-accent/5 rounded px-1 py-px">
                demo
              </span>
            )}
          </div>
          {corner && <div className="text-muted text-[10.5px] shrink-0">{corner}</div>}
        </header>
      )}
      <div className={`flex-1 min-h-0 ${scroll ? 'overflow-auto scroll-thin' : 'overflow-hidden'}`}>
        {children}
      </div>
    </section>
  );
}

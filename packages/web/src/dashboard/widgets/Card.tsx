import type { ReactNode } from 'react';

interface Props {
  title?: string;
  corner?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ title, corner, className, children }: Props): JSX.Element {
  return (
    <section
      className={`bg-panel border border-border rounded-card p-4 h-full overflow-hidden flex flex-col ${className ?? ''}`}
    >
      {(title || corner) && (
        // header doubles as the grid drag handle (active only in edit mode)
        <header className="card-drag-handle flex items-center justify-between mb-3 shrink-0">
          {title && (
            <h2 className="text-muted text-[11px] uppercase tracking-[0.2em]">{title}</h2>
          )}
          {corner && <div className="text-muted text-[11px]">{corner}</div>}
        </header>
      )}
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </section>
  );
}

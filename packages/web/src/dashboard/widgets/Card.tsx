import type { ReactNode } from 'react';

interface Props {
  title?: string;
  corner?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ title, corner, className, children }: Props): JSX.Element {
  return (
    <section className={`bg-panel border border-border rounded-card p-4 ${className ?? ''}`}>
      {(title || corner) && (
        <header className="flex items-center justify-between mb-3">
          {title && (
            <h2 className="text-muted text-[11px] uppercase tracking-[0.2em]">{title}</h2>
          )}
          {corner && <div className="text-muted text-[11px]">{corner}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

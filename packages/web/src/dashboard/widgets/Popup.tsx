import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}

export function Popup({ title, subtitle, onClose, children }: Props): JSX.Element {
  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/55 px-4 py-6">
      <section className="panel-surface relative z-[10000] flex h-[min(500px,78vh)] w-[min(760px,92vw)] flex-col overflow-hidden rounded-card border border-border-strong shadow-2xl">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-[13px] font-medium text-fg">{title}</h2>
            {subtitle && (
              <div className="mt-0.5 truncate text-[9.5px] uppercase tracking-[0.18em] text-muted">
                {subtitle}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="chip shrink-0 px-2.5 py-1 text-[11px] text-muted hover:text-fg"
          >
            CLOSE
          </button>
        </header>
        <div className="min-h-0 flex-1 p-3">{children}</div>
      </section>
    </div>,
    document.body,
  );
}

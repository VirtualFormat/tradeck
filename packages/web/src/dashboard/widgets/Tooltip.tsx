import type { ReactNode } from 'react';

export interface TooltipState {
  x: number;
  y: number;
  content: ReactNode;
}

/** Lightweight absolutely-positioned tooltip rendered inside a relative parent. */
export function Tooltip({ tip }: { tip: TooltipState | null }): JSX.Element | null {
  if (!tip) return null;
  return (
    <div
      className="pointer-events-none absolute z-20 bg-panel-2 border border-border rounded px-2.5 py-1.5 text-[11px] text-fg shadow-lg"
      style={{ left: tip.x + 12, top: tip.y + 12, maxWidth: 220 }}
    >
      {tip.content}
    </div>
  );
}

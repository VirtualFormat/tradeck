import { useRef, useState } from 'react';
import { Card } from './widgets/Card';
import { Tooltip, type TooltipState } from './widgets/Tooltip';
import { graphMock } from './mock/dashboardData';
import { useAnimationClock } from './hooks/useAnimationClock';
import { projectGalaxy, useGalaxy, type NodeKind } from './hooks/useGalaxy3D';

const W = 720;
const H = 300;

const nodeColor: Record<NodeKind, string> = {
  up: 'var(--color-up)',
  down: 'var(--color-down)',
  neu: 'var(--color-muted)',
  hub: 'var(--color-fg)',
};
const kindLabel: Record<NodeKind, string> = {
  up: 'Bull signal',
  down: 'Bear signal',
  neu: 'Median path',
  hub: 'Cluster hub',
};

interface Drag {
  startX: number;
  startY: number;
  yaw: number;
  pitch: number;
}

export function RelationshipGraph(): JSX.Element {
  const g = graphMock;
  const t = useAnimationClock();
  const galaxy = useGalaxy(46);

  const wrapRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  // manual rotation offsets applied on top of auto-rotation
  const [manual, setManual] = useState({ yaw: 0, pitch: 0 });
  const [dragging, setDragging] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<TooltipState | null>(null);

  // auto-rotate only while not dragging
  const autoYaw = dragging ? 0 : t * 0.5;
  const autoPitch = dragging ? 0 : Math.sin(t * 0.25) * 0.25;
  const yaw = manual.yaw + autoYaw;
  const pitch = Math.max(-1.2, Math.min(1.2, manual.pitch + autoPitch));

  const projected = projectGalaxy(galaxy.nodes, yaw, pitch, W, H);
  const order = projected.map((_, i) => i).sort((a, b) => projected[a].z - projected[b].z);
  const iter = 720 + Math.floor(t * 7);

  // convert a mouse event to viewBox coords
  const toLocal = (e: React.MouseEvent): { x: number; y: number } => {
    const rect = wrapRef.current!.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * W,
      y: ((e.clientY - rect.top) / rect.height) * H,
    };
  };

  const onDown = (e: React.MouseEvent): void => {
    drag.current = { startX: e.clientX, startY: e.clientY, yaw: manual.yaw, pitch: manual.pitch };
    setDragging(true);
  };
  const onMove = (e: React.MouseEvent): void => {
    if (drag.current) {
      // freeze auto-rotation into manual on first drag move so it doesn't jump
      const d = drag.current;
      const dx = (e.clientX - d.startX) / 120;
      const dy = (e.clientY - d.startY) / 120;
      setManual({ yaw: d.yaw + dx, pitch: d.pitch + dy });
      return;
    }
    // hover detection: nearest node within its radius
    const { x, y } = toLocal(e);
    let best: string | null = null;
    let bestD = Infinity;
    for (const p of projected) {
      const dd = (p.sx - x) ** 2 + (p.sy - y) ** 2;
      if (dd < (p.r + 4) ** 2 && dd < bestD) {
        bestD = dd;
        best = p.id;
      }
    }
    setHover(best);
    if (best) {
      const p = projected.find((n) => n.id === best)!;
      const rect = wrapRef.current!.getBoundingClientRect();
      setTip({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        content: (
          <div>
            <div className="text-fg">{p.label ?? p.id}</div>
            <div className="text-muted">{kindLabel[p.kind]}</div>
            <div className="tab-nums text-muted">depth {p.z.toFixed(2)}</div>
          </div>
        ),
      });
    } else {
      setTip(null);
    }
  };
  const onUp = (): void => {
    drag.current = null;
    setDragging(false);
  };
  const onLeave = (): void => {
    drag.current = null;
    setDragging(false);
    setHover(null);
    setTip(null);
  };

  return (
    <Card
      title="关系图谱"
      subtitle="Relationship Graph"
      demo
      corner={`iter ${iter} · drag to rotate`}
    >
      <div className="grid grid-cols-1 lg:grid-cols-[160px_minmax(0,1fr)_180px] gap-4">
        <div className="space-y-1.5">
          {g.legend.map((l) => (
            <div key={l} className="text-[11px] text-muted">
              · {l}
            </div>
          ))}
        </div>

        <div ref={wrapRef} className="relative min-h-[300px]">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className={`w-full select-none ${dragging ? 'cursor-grabbing' : 'cursor-grab'}`}
            style={{ height: 280 }}
            onMouseDown={onDown}
            onMouseMove={onMove}
            onMouseUp={onUp}
            onMouseLeave={onLeave}
          >
            <defs>
              <radialGradient id="hubGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="var(--color-fg)" stopOpacity="0.4" />
                <stop offset="100%" stopColor="var(--color-fg)" stopOpacity="0" />
              </radialGradient>
            </defs>

            {galaxy.edges.map((e, i) => {
              const a = projected[e.from];
              const b = projected[e.to];
              const lit = hover && (a.id === hover || b.id === hover);
              const op = lit ? 0.9 : Math.max(0.05, ((a.z + b.z) / 2 + 1) / 2) * 0.5;
              return (
                <line
                  key={i}
                  x1={a.sx}
                  y1={a.sy}
                  x2={b.sx}
                  y2={b.sy}
                  stroke={lit ? 'var(--color-fg)' : 'var(--color-accent)'}
                  strokeWidth={lit ? 1.2 : 0.6}
                  strokeOpacity={op}
                />
              );
            })}

            {order.map((idx) => {
              const p = projected[idx];
              const isHover = p.id === hover;
              const depthOpacity = 0.35 + ((p.z + 1) / 2) * 0.65;
              const pulse = p.kind === 'hub' ? 1 + Math.sin(t * 2) * 0.06 : 1;
              const r = p.r * pulse * (isHover ? 1.5 : 1);
              return (
                <g key={p.id} opacity={isHover ? 1 : depthOpacity}>
                  {(p.kind === 'hub' || r > 12 || isHover) && (
                    <circle cx={p.sx} cy={p.sy} r={r * 2.4} fill="url(#hubGlow)" />
                  )}
                  <circle
                    cx={p.sx}
                    cy={p.sy}
                    r={r}
                    fill={nodeColor[p.kind]}
                    stroke={isHover ? 'var(--color-fg)' : 'none'}
                    strokeWidth={isHover ? 1.5 : 0}
                  />
                  {p.label && p.scale > 0.7 && (
                    <text
                      x={p.sx}
                      y={p.sy - r - 4}
                      fill="var(--color-muted)"
                      fontSize={9}
                      textAnchor="middle"
                    >
                      {p.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          <Tooltip tip={tip} />
        </div>

        <div className="space-y-3">
          <div>
            <div className="text-muted text-[10px] uppercase tracking-wider">P(UP)</div>
            <div className="tab-nums text-up text-2xl">{g.pUp.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-muted text-[10px] uppercase tracking-wider">P(DOWN)</div>
            <div className="tab-nums text-down text-2xl">{g.pDown.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-muted text-[10px] uppercase tracking-wider">Confidence</div>
            <div className="h-2 bg-panel-2 rounded mt-1 overflow-hidden">
              <div className="h-full bg-accent" style={{ width: `${g.confidence * 100}%` }} />
            </div>
            <div className="tab-nums text-fg text-xs mt-1">{(g.confidence * 100).toFixed(1)}%</div>
          </div>
        </div>

        <div className="lg:col-span-full flex items-end gap-1 h-12">
          {g.bars.map((b, i) => (
            <div
              key={i}
              className={`flex-1 rounded-sm ${i > g.bars.length / 2 ? 'bg-up/60' : 'bg-down/50'}`}
              style={{ height: `${Math.max(8, b * 100)}%` }}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

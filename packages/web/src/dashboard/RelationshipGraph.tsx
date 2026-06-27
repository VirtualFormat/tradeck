import { Card } from './widgets/Card';
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

export function RelationshipGraph(): JSX.Element {
  const g = graphMock;
  const t = useAnimationClock();
  const galaxy = useGalaxy(46);

  const projected = projectGalaxy(galaxy.nodes, t, W, H);
  // painter's order: draw far (low z) first, near (high z) last
  const order = projected.map((_, i) => i).sort((a, b) => projected[a].z - projected[b].z);
  const iter = 720 + Math.floor(t * 7);

  return (
    <Card title="Mirofish · relationship graph simulation" corner={`iter ${iter}`}>
      <div className="grid grid-cols-1 lg:grid-cols-[160px_minmax(0,1fr)_180px] gap-4">
        <div className="space-y-1.5">
          {g.legend.map((l) => (
            <div key={l} className="text-[11px] text-muted">
              · {l}
            </div>
          ))}
        </div>

        <div className="min-h-[300px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 280 }}>
            <defs>
              <radialGradient id="hubGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="var(--color-fg)" stopOpacity="0.4" />
                <stop offset="100%" stopColor="var(--color-fg)" stopOpacity="0" />
              </radialGradient>
            </defs>

            {/* edges (depth-faded) */}
            {galaxy.edges.map((e, i) => {
              const a = projected[e.from];
              const b = projected[e.to];
              const op = Math.max(0.05, ((a.z + b.z) / 2 + 1) / 2) * 0.5;
              return (
                <line
                  key={i}
                  x1={a.sx}
                  y1={a.sy}
                  x2={b.sx}
                  y2={b.sy}
                  stroke="var(--color-accent)"
                  strokeWidth={0.6}
                  strokeOpacity={op}
                />
              );
            })}

            {/* nodes back-to-front for correct 3D occlusion */}
            {order.map((idx) => {
              const p = projected[idx];
              const depthOpacity = 0.35 + ((p.z + 1) / 2) * 0.65;
              const pulse = p.kind === 'hub' ? 1 + Math.sin(t * 2) * 0.06 : 1;
              const r = p.r * pulse;
              return (
                <g key={p.id} opacity={depthOpacity}>
                  {(p.kind === 'hub' || r > 12) && (
                    <circle cx={p.sx} cy={p.sy} r={r * 2.4} fill="url(#hubGlow)" />
                  )}
                  <circle cx={p.sx} cy={p.sy} r={r} fill={nodeColor[p.kind]} />
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

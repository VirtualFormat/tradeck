import { Card } from './widgets/Card';
import { graphMock, type GraphNode } from './mock/dashboardData';

const W = 720;
const H = 260;

const nodeFill: Record<GraphNode['kind'], string> = {
  up: 'var(--color-up)',
  down: 'var(--color-down)',
  neu: 'var(--color-muted)',
  hub: 'var(--color-fg)',
};

export function RelationshipGraph(): JSX.Element {
  const g = graphMock;
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  return (
    <Card title="Mirofish · relationship graph simulation">
      <div className="grid grid-cols-1 lg:grid-cols-[160px_minmax(0,1fr)_180px] gap-4">
        <div className="space-y-1.5">
          {g.legend.map((l) => (
            <div key={l} className="text-[11px] text-muted">
              · {l}
            </div>
          ))}
        </div>

        <div className="min-h-[260px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 240 }}>
            {g.edges.map((e, i) => {
              const a = byId.get(e.from);
              const b = byId.get(e.to);
              if (!a || !b) return null;
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="var(--color-border)"
                  strokeWidth={1}
                />
              );
            })}
            {g.nodes.map((n) => (
              <g key={n.id}>
                <circle cx={n.x} cy={n.y} r={n.r} fill={nodeFill[n.kind]} opacity={0.85} />
                {n.r >= 14 && (
                  <text x={n.x} y={n.y - n.r - 4} fill="var(--color-muted)" fontSize={9} textAnchor="middle">
                    {n.id}
                  </text>
                )}
              </g>
            ))}
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

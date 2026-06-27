import { Card } from './widgets/Card';
import { MetricRow } from './widgets/MetricRow';
import { latticeMetrics, latticeMock } from './mock/dashboardData';
import { galtonPins } from './mock/svgPaths';

const W = 600;
const H = 200;
const pins = galtonPins(8, W, H);

export function ProbabilityLattice(): JSX.Element {
  return (
    <Card title="Probability Lattice · 5,944 trades, one board">
      <div className="grid grid-cols-1 lg:grid-cols-[180px_minmax(0,1fr)] gap-4">
        <div>
          {latticeMetrics.map((m) => (
            <MetricRow key={m.label} {...m} />
          ))}
        </div>
        <div className="min-h-[220px] flex flex-col">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 160 }}>
            <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--color-border)" strokeDasharray="3 3" />
            {pins.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={2} fill="var(--color-muted)" opacity={0.6} />
            ))}
            {[0.46, 0.52, 0.58, 0.49].map((fx, i) => (
              <circle key={`h${i}`} cx={fx * W} cy={H - 14 - i * 22} r={4} fill="var(--color-fg)" />
            ))}
          </svg>
          <div className="flex items-end gap-1 h-16 mt-1">
            {latticeMock.bars.map((b, i) => (
              <div
                key={i}
                className="flex-1 bg-up/50 rounded-sm"
                style={{ height: `${Math.max(6, b * 100)}%` }}
              />
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

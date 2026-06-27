import { Card } from './widgets/Card';
import { MetricRow } from './widgets/MetricRow';
import { ridgeCurves, ridgeMetrics } from './mock/dashboardData';
import { ridgePath } from './mock/svgPaths';

const W = 600;
const H = 220;

export function TailRidge(): JSX.Element {
  return (
    <Card title="Tail Probability Ridge · strike landscape">
      <div className="grid grid-cols-1 lg:grid-cols-[180px_minmax(0,1fr)] gap-4">
        <div>
          {ridgeMetrics.map((m) => (
            <MetricRow key={m.label} {...m} />
          ))}
        </div>
        <div className="min-h-[220px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 200 }}>
            {ridgeCurves
              .slice()
              .reverse()
              .map((c, i) => {
                const d = ridgePath(c, W, H);
                return (
                  <path
                    key={i}
                    d={`${d} L ${W},${c.baseY} L 0,${c.baseY} Z`}
                    fill="var(--color-panel-2)"
                    stroke="var(--color-fg)"
                    strokeWidth={1}
                    opacity={c.opacity}
                  />
                );
              })}
          </svg>
        </div>
      </div>
    </Card>
  );
}

import { Card } from './widgets/Card';
import { MetricRow } from './widgets/MetricRow';
import { ridgeCurves, ridgeMetrics } from './mock/dashboardData';
import { ridgePath } from './mock/svgPaths';
import { useAnimationClock } from './hooks/useAnimationClock';

const W = 600;
const H = 240;

export function TailRidge(): JSX.Element {
  const t = useAnimationClock();
  // back-to-front: index 0 = farthest (top, dim), last = nearest (bottom, bright)
  const ordered = ridgeCurves.slice().reverse();
  const n = ordered.length;

  return (
    <Card title="Tail Probability Ridge · strike landscape">
      <div className="grid grid-cols-1 lg:grid-cols-[180px_minmax(0,1fr)] gap-4">
        <div>
          {ridgeMetrics.map((m) => (
            <MetricRow key={m.label} {...m} />
          ))}
        </div>
        <div className="min-h-[240px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 220 }}>
            <defs>
              {/* per-depth vertical fill: bright crest fading to dark base (3D body) */}
              <linearGradient id="ridgeFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-fg)" stopOpacity="0.18" />
                <stop offset="55%" stopColor="var(--color-panel-2)" stopOpacity="0.9" />
                <stop offset="100%" stopColor="var(--color-bg)" stopOpacity="1" />
              </linearGradient>
              {/* tail-zone red wash on the right */}
              <linearGradient id="tailZone" x1="0" y1="0" x2="1" y2="0">
                <stop offset="60%" stopColor="var(--color-down)" stopOpacity="0" />
                <stop offset="100%" stopColor="var(--color-down)" stopOpacity="0.35" />
              </linearGradient>
            </defs>

            {ordered.map((c, i) => {
              const depth = i / (n - 1); // 0 far .. 1 near
              // parallax: farther ridges drift more horizontally as they breathe
              const driftPhase = i * 0.5;
              const drift = Math.sin(t * 0.5 + driftPhase) * (1 - depth) * 16;
              const baseY = 40 + i * ((H - 70) / n);
              const d = ridgePath({ ...c, baseY }, W, H, t, driftPhase);
              // nearer = brighter stroke + more opaque body; farther = dim
              const strokeOpacity = 0.25 + depth * 0.65;
              const bodyOpacity = 0.5 + depth * 0.5;
              return (
                <g key={i} transform={`translate(${drift} 0)`}>
                  <path
                    d={`${d} L ${W},${baseY} L 0,${baseY} Z`}
                    fill="url(#ridgeFill)"
                    opacity={bodyOpacity}
                  />
                  <path
                    d={d}
                    fill="none"
                    stroke="var(--color-fg)"
                    strokeWidth={depth > 0.8 ? 1.4 : 1}
                    strokeOpacity={strokeOpacity}
                  />
                </g>
              );
            })}

            {/* tail payout zone + strike frontier */}
            <rect x={W * 0.72} y={0} width={W * 0.28} height={H} fill="url(#tailZone)" />
            <line
              x1={W * 0.72}
              y1={H}
              x2={W * 0.86}
              y2={10}
              stroke="var(--color-down)"
              strokeWidth={1}
              strokeDasharray="4 4"
              opacity={0.6}
            />
          </svg>
        </div>
      </div>
    </Card>
  );
}

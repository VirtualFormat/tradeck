import { useRef, useState } from 'react';
import { Card } from './widgets/Card';
import { MetricRow } from './widgets/MetricRow';
import { Tooltip, type TooltipState } from './widgets/Tooltip';
import type { MetricItem } from './mock/dashboardData';
import { galtonPins } from './mock/svgPaths';
import { useGaltonBoard } from './hooks/useGaltonBoard';

const W = 600;
const H = 200;
const ROWS = 8;
const BINS = 9;
const pins = galtonPins(ROWS, W, H);

export function ProbabilityLattice(): JSX.Element {
  const { balls, bins, dropped } = useGaltonBoard({ rows: ROWS, bins: BINS });
  const barsRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TooltipState | null>(null);
  const [hoverBin, setHoverBin] = useState<number | null>(null);

  const maxBin = Math.max(1, ...bins);
  const greenPct = dropped > 0 ? ((bins.slice(Math.floor(BINS / 2)).reduce((a, b) => a + b, 0) / dropped) * 100) : 0;

  // live metrics derived from the running simulation
  const metrics: MetricItem[] = [
    { label: 'BALLS DROPPED', value: dropped.toLocaleString('en-US') },
    { label: 'LANDED GREEN', value: `${greenPct.toFixed(1)}%`, tone: 'up' },
    { label: 'EV / TRADE', value: '+$118', tone: 'up' },
    { label: 'SESSION PNL', value: `+$${(dropped * 4).toLocaleString('en-US')}`, tone: 'up' },
    { label: 'ALL-TIME', value: '5,944' },
    { label: 'REALIZED', value: '+$401,819', tone: 'up' },
  ];

  return (
    <Card title="概率分布" subtitle="Probability Distribution · Galton" demo>
      <div className="grid grid-cols-1 lg:grid-cols-[180px_minmax(0,1fr)] gap-4">
        <div>
          {metrics.map((m) => (
            <MetricRow key={m.label} {...m} />
          ))}
        </div>
        <div className="min-h-[220px] flex flex-col">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 160 }}>
            {/* breakeven divider */}
            <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--color-border)" strokeDasharray="3 3" />
            {/* static pegs */}
            {pins.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={2} fill="var(--color-muted)" opacity={0.6} />
            ))}
            {/* falling balls */}
            {balls.map((b) => {
              const y = ((b.row + b.rowProgress) / ROWS) * (H - 16) + 6;
              return <circle key={b.id} cx={b.x * W} cy={y} r={3.5} fill="var(--color-fg)" />;
            })}
          </svg>
          {/* live histogram (hover for detail) */}
          <div ref={barsRef} className="relative flex items-end gap-1 h-16 mt-1">
            {bins.map((count, i) => {
              const isProfit = i >= Math.floor(BINS / 2);
              const isHover = hoverBin === i;
              const pct = dropped > 0 ? ((count / dropped) * 100).toFixed(1) : '0.0';
              return (
                <div
                  key={i}
                  className={`flex-1 rounded-sm transition-[height,opacity] duration-300 cursor-pointer ${isProfit ? 'bg-up/60' : 'bg-down/40'} ${isHover ? 'opacity-100 outline outline-1 outline-fg/60' : 'opacity-90'}`}
                  style={{ height: `${Math.max(2, (count / maxBin) * 100)}%` }}
                  onMouseEnter={(e) => {
                    setHoverBin(i);
                    const rect = barsRef.current!.getBoundingClientRect();
                    setTip({
                      x: e.clientX - rect.left,
                      y: e.clientY - rect.top,
                      content: (
                        <div>
                          <div className="text-fg">bin {i + 1}</div>
                          <div className="tab-nums text-muted">count {count}</div>
                          <div className="tab-nums text-muted">{pct}% of drops</div>
                        </div>
                      ),
                    });
                  }}
                  onMouseLeave={() => {
                    setHoverBin(null);
                    setTip(null);
                  }}
                />
              );
            })}
            <Tooltip tip={tip} />
          </div>
        </div>
      </div>
    </Card>
  );
}

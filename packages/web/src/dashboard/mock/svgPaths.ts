import type { RidgeCurve } from './dashboardData';

/** Galton-board pin coordinates: a triangular lattice within [0..w] x [0..h]. */
export function galtonPins(rows: number, w: number, h: number): { x: number; y: number }[] {
  const pins: { x: number; y: number }[] = [];
  const rowGap = h / (rows + 1);
  for (let r = 0; r < rows; r++) {
    const count = r + 1;
    const y = rowGap * (r + 1);
    const span = (count - 1) * (w / (rows + 2));
    const startX = (w - span) / 2;
    const colGap = count > 1 ? span / (count - 1) : 0;
    for (let c = 0; c < count; c++) {
      pins.push({ x: startX + c * colGap, y });
    }
  }
  return pins;
}

/** Smooth ridgeline path (probability-density-ish bump) for a curve spec. */
export function ridgePath(curve: RidgeCurve, w: number, h: number): string {
  const steps = 48;
  const peak = curve.peakX * w;
  const sigma = w * 0.18;
  const points: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const x = (i / steps) * w;
    const g = Math.exp(-((x - peak) ** 2) / (2 * sigma ** 2));
    const y = curve.baseY - g * h * 0.16 * curve.amp;
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return `M ${points.join(' L ')}`;
}

import { useEffect, useRef, useState } from 'react';

export interface Ball {
  id: number;
  /** 0..1 horizontal position (updated each step) */
  x: number;
  /** current row index (0 = top) */
  row: number;
  /** 0..1 vertical progress within current row, for smooth fall */
  rowProgress: number;
  /** target bin index once landed */
  done: boolean;
}

export interface GaltonState {
  balls: Ball[];
  bins: number[]; // counts per bin
  dropped: number;
}

interface Options {
  rows: number;
  bins: number;
  /** ms between spawning new balls */
  spawnMs?: number;
  /** rows advanced per second */
  fallSpeed?: number;
  maxConcurrent?: number;
}

/**
 * Galton board (quincunx) simulation driven by requestAnimationFrame.
 * Balls fall from the top, bounce left/right at each peg row, then accumulate
 * into bottom bins (frequency histogram trends bell-shaped). Mock visual only.
 */
export function useGaltonBoard({
  rows,
  bins,
  spawnMs = 600,
  fallSpeed = 6,
  maxConcurrent = 5,
}: Options): GaltonState {
  const [state, setState] = useState<GaltonState>(() => ({
    balls: [],
    bins: new Array(bins).fill(0),
    dropped: 0,
  }));

  const raf = useRef<number>(0);
  const lastTs = useRef<number>(0);
  const lastSpawn = useRef<number>(0);
  const nextId = useRef<number>(0);

  useEffect(() => {
    const step = (ts: number): void => {
      if (!lastTs.current) lastTs.current = ts;
      const dt = (ts - lastTs.current) / 1000;
      lastTs.current = ts;

      setState((prev) => {
        let balls = prev.balls.map((b) => ({ ...b }));
        const binCounts = prev.bins.slice();
        let dropped = prev.dropped;

        // advance each ball
        const landed: Ball[] = [];
        balls.forEach((b) => {
          b.rowProgress += dt * fallSpeed;
          while (b.rowProgress >= 1) {
            b.rowProgress -= 1;
            b.row += 1;
            // bounce: nudge x left/right by half a bin width
            const dir = Math.random() < 0.5 ? -1 : 1;
            b.x = Math.min(0.98, Math.max(0.02, b.x + dir * (0.5 / rows)));
            if (b.row >= rows) {
              b.done = true;
              landed.push(b);
            }
          }
        });

        // commit landed balls to bins
        landed.forEach((b) => {
          const bin = Math.min(bins - 1, Math.max(0, Math.floor(b.x * bins)));
          binCounts[bin] += 1;
          dropped += 1;
        });
        balls = balls.filter((b) => !b.done);

        // spawn new ball
        if (ts - lastSpawn.current >= spawnMs && balls.length < maxConcurrent) {
          lastSpawn.current = ts;
          balls.push({ id: nextId.current++, x: 0.5, row: 0, rowProgress: 0, done: false });
        }

        return { balls, bins: binCounts, dropped };
      });

      raf.current = requestAnimationFrame(step);
    };

    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [rows, bins, spawnMs, fallSpeed, maxConcurrent]);

  return state;
}

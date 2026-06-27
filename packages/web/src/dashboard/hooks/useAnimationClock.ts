import { useEffect, useRef, useState } from 'react';

/**
 * Returns a continuously increasing time value (seconds) driven by rAF, for
 * smooth periodic animations. Pauses when the tab is hidden to save CPU.
 * StrictMode-safe (cancels rAF on cleanup).
 */
export function useAnimationClock(): number {
  const [t, setT] = useState(0);
  const raf = useRef<number>(0);
  const start = useRef<number>(0);

  useEffect(() => {
    const step = (ts: number): void => {
      if (!start.current) start.current = ts;
      if (!document.hidden) setT((ts - start.current) / 1000);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, []);

  return t;
}

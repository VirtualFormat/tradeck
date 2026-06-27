import { useMemo } from 'react';

export type NodeKind = 'up' | 'down' | 'neu' | 'hub';

export interface Node3D {
  id: string;
  label?: string;
  // position on a unit sphere-ish volume
  x: number;
  y: number;
  z: number;
  baseR: number;
  kind: NodeKind;
}

export interface Edge3D {
  from: number;
  to: number;
}

export interface ProjectedNode {
  id: string;
  label?: string;
  sx: number; // screen x
  sy: number; // screen y
  scale: number; // depth scale (0..1), nearer = larger
  z: number; // rotated depth (-1..1), for painter's-order sort
  kind: NodeKind;
  r: number; // rendered radius
}

interface Galaxy {
  nodes: Node3D[];
  edges: Edge3D[];
}

/** Deterministic pseudo-random in [0,1) from an integer seed. */
function rand(seed: number): number {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

/** Build a fixed galaxy: a central hub + satellites distributed in a 3D shell. */
export function useGalaxy(count = 46): Galaxy {
  return useMemo(() => {
    const nodes: Node3D[] = [];
    const hubs: { id: string; label: string }[] = [
      { id: 'hub_prime', label: 'HUB_PRIME' },
      { id: 'bear_cluster', label: 'BEAR_CLUSTER' },
      { id: 'catalyst', label: 'CATALYST' },
      { id: 'miro', label: 'MIRO' },
    ];
    // hubs on an inner ring
    hubs.forEach((h, i) => {
      const a = (i / hubs.length) * Math.PI * 2;
      nodes.push({
        id: h.id,
        label: h.label,
        x: Math.cos(a) * 0.45,
        y: Math.sin(a) * 0.18,
        z: Math.sin(a) * 0.45,
        baseR: i === 0 ? 22 : 15,
        kind: i === 0 ? 'hub' : i === 1 ? 'down' : i === 3 ? 'up' : 'neu',
      });
    });
    // satellites on a fibonacci sphere for even spread
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < count; i++) {
      const yy = 1 - (i / (count - 1)) * 2; // -1..1
      const radius = Math.sqrt(1 - yy * yy);
      const theta = golden * i;
      const jitter = 0.85 + rand(i) * 0.25;
      const kindRoll = rand(i * 7.3);
      nodes.push({
        id: `s${i}`,
        x: Math.cos(theta) * radius * jitter,
        y: yy * jitter,
        z: Math.sin(theta) * radius * jitter,
        baseR: 2 + rand(i * 3.1) * 4,
        kind: kindRoll < 0.55 ? 'down' : kindRoll < 0.8 ? 'up' : 'neu',
      });
    }

    // edges: each satellite links to its nearest hub (index 0..3)
    const edges: Edge3D[] = [];
    for (let i = 4; i < nodes.length; i++) {
      let best = 0;
      let bestD = Infinity;
      for (let h = 0; h < 4; h++) {
        const dx = nodes[i].x - nodes[h].x;
        const dy = nodes[i].y - nodes[h].y;
        const dz = nodes[i].z - nodes[h].z;
        const d = dx * dx + dy * dy + dz * dz;
        if (d < bestD) {
          bestD = d;
          best = h;
        }
      }
      if (rand(i * 5.7) > 0.25) edges.push({ from: best, to: i });
    }
    // hub-to-hub backbone
    edges.push({ from: 1, to: 0 }, { from: 0, to: 2 }, { from: 2, to: 3 });

    return { nodes, edges };
  }, [count]);
}

/** Rotate the galaxy around the Y axis by angle `t` and project to 2D screen. */
export function projectGalaxy(
  nodes: Node3D[],
  t: number,
  w: number,
  h: number,
): ProjectedNode[] {
  const cx = w / 2;
  const cy = h / 2;
  const spread = Math.min(w, h) * 0.42;
  const ay = t * 0.5; // yaw
  const ax = Math.sin(t * 0.25) * 0.25; // gentle tilt
  const cosY = Math.cos(ay);
  const sinY = Math.sin(ay);
  const cosX = Math.cos(ax);
  const sinX = Math.sin(ax);
  const persp = 2.2; // perspective strength

  return nodes.map((n) => {
    // rotate around Y
    let x = n.x * cosY - n.z * sinY;
    let z = n.x * sinY + n.z * cosY;
    let y = n.y;
    // tilt around X
    const y2 = y * cosX - z * sinX;
    z = y * sinX + z * cosX;
    y = y2;

    const depth = persp / (persp - z); // nearer (z>0) -> larger
    const sx = cx + x * spread * depth;
    const sy = cy + y * spread * depth;
    const scale = Math.max(0.15, Math.min(1.4, depth - 0.2));
    return {
      id: n.id,
      label: n.label,
      sx,
      sy,
      scale,
      z,
      kind: n.kind,
      r: n.baseR * scale,
    };
  });
}

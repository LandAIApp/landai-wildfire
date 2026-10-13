import type { LngLat, Ring } from '../types/api';

const R = 6378137;

/** Spherical area in hectares of a lon/lat ring (closed or open). Same formula as the backend. */
export function ringAreaHectares(points: LngLat[]): number {
  if (points.length < 3) return 0;
  const ring = isClosed(points) ? points : [...points, points[0]];
  let total = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [lon1, lat1] = ring[i];
    const [lon2, lat2] = ring[i + 1];
    total += ((lon2 - lon1) * Math.PI / 180)
      * (2 + Math.sin(lat1 * Math.PI / 180) + Math.sin(lat2 * Math.PI / 180));
  }
  return Math.abs(total * R * R / 2) / 10_000;
}

export function isClosed(points: LngLat[]): boolean {
  if (points.length < 2) return false;
  const a = points[0], b = points[points.length - 1];
  return a[0] === b[0] && a[1] === b[1];
}

export function closeRing(points: LngLat[]): Ring {
  return isClosed(points) ? points : [...points, points[0]];
}

export function rectangleRing(a: LngLat, b: LngLat): Ring {
  const [x1, y1] = a, [x2, y2] = b;
  return [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]];
}

const orient = (p: LngLat, q: LngLat, r: LngLat) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
const onSeg = (p: LngLat, q: LngLat, r: LngLat) =>
  Math.min(p[0], r[0]) <= q[0] && q[0] <= Math.max(p[0], r[0])
  && Math.min(p[1], r[1]) <= q[1] && q[1] <= Math.max(p[1], r[1]);

function intersect(p1: LngLat, q1: LngLat, p2: LngLat, q2: LngLat): boolean {
  const o1 = orient(p1, q1, p2), o2 = orient(p1, q1, q2), o3 = orient(p2, q2, p1), o4 = orient(p2, q2, q1);
  if (o1 * o2 < 0 && o3 * o4 < 0) return true;
  return (o1 === 0 && onSeg(p1, p2, q1)) || (o2 === 0 && onSeg(p1, q2, q1))
    || (o3 === 0 && onSeg(p2, p1, q2)) || (o4 === 0 && onSeg(p2, q1, q2));
}

/** True when two non-adjacent edges of the closed ring touch or cross. */
export function hasSelfIntersection(points: LngLat[]): boolean {
  const ring = closeRing(points);
  const n = ring.length - 1;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue;
      if (intersect(ring[i], ring[i + 1], ring[j], ring[j + 1])) return true;
    }
  }
  return false;
}

export type AreaLevel = 'none' | 'small' | 'ok' | 'warn' | 'over';

export interface Limits { max: number; warn: number; min: number }

/** Level of an area against the (backend-provided) limits. `small` only applies to drawn areas. */
export function areaLevel(hectares: number | null, limits: Limits, drawn: boolean): AreaLevel {
  if (hectares === null || !(hectares > 0)) return 'none';
  if (hectares > limits.max) return 'over';
  if (drawn && hectares < limits.min) return 'small';
  if (hectares > limits.warn) return 'warn';
  return 'ok';
}

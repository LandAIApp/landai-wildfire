import { describe, expect, it } from 'vitest';
import { areaLevel, closeRing, hasSelfIntersection, rectangleRing, ringAreaHectares } from './geometry';
import type { LngLat } from '../types/api';

const SQUARE: LngLat[] = [[-75, 4], [-74.9, 4], [-74.9, 4.1], [-75, 4.1], [-75, 4]];
const limits = { max: 100_000, warn: 50_000, min: 10 };

describe('geometry', () => {
  it('computes the same area as the backend (~12,3xx ha for 0.1° x 0.1° at 4°N)', () => {
    const ha = ringAreaHectares(SQUARE);
    expect(ha).toBeGreaterThan(12_000);
    expect(ha).toBeLessThan(12_500);
    expect(ringAreaHectares(SQUARE.slice(0, -1))).toBeCloseTo(ha, 6);
    expect(ringAreaHectares([[0, 0], [1, 1]])).toBe(0);
  });
  it('builds rectangles and closes rings', () => {
    const r = rectangleRing([0, 0], [1, 1]);
    expect(r).toHaveLength(5);
    expect(r[0]).toEqual(r[4]);
    expect(closeRing([[0, 0], [1, 0], [1, 1]])).toHaveLength(4);
  });
  it('detects self-intersection', () => {
    expect(hasSelfIntersection([[0, 0], [1, 1], [1, 0], [0, 1]])).toBe(true);
    expect(hasSelfIntersection(SQUARE)).toBe(false);
  });
  it('classifies the area level against the backend-provided limits', () => {
    expect(areaLevel(null, limits, true)).toBe('none');
    expect(areaLevel(5, limits, true)).toBe('small');
    expect(areaLevel(5, limits, false)).toBe('ok');
    expect(areaLevel(60_000, limits, true)).toBe('warn');
    expect(areaLevel(100_001, limits, false)).toBe('over');
  });
});

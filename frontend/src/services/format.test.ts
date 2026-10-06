import { describe, expect, it } from 'vitest';
import { formatHectares } from './format';

describe('formatHectares', () => {
  it('rounds and groups thousands (English)', () => {
    expect(formatHectares(1234.6, 'en')).toBe('1,235 ha');
  });
  it('uses Spanish grouping', () => {
    expect(formatHectares(1234567, 'es')).toMatch(/^1[.\u00a0 ]?234[.\u00a0 ]?567 ha$/);
  });
  it('handles zero', () => {
    expect(formatHectares(0, 'en')).toBe('0 ha');
  });
  it('handles missing values in both languages', () => {
    expect(formatHectares(null, 'en')).toBe('No data');
    expect(formatHectares(undefined, 'es')).toBe('Sin datos');
  });
});

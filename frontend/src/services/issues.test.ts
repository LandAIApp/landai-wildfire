import { describe, expect, it } from 'vitest';
import { describeError, describeIssue } from './issues';

describe('describeIssue', () => {
  it('translates by code and fills parameters', () => {
    const issue = { code: 'municipality_not_found', message: 'server text' };
    expect(describeIssue('es', issue, { department: 'Tolima', municipality: 'X' })).toContain('«X»');
    expect(describeIssue('en', issue, { department: 'Tolima', municipality: 'X' })).toContain('“X”');
  });
  it('formats hectares per language', () => {
    const issue = { code: 'aoi_large', message: 'm' };
    expect(describeIssue('en', issue, { aoiHectares: 150000 })).toContain('150,000');
  });
  it('falls back to the server message for unknown codes', () => {
    expect(describeIssue('es', { code: 'brand_new', message: 'Mensaje del servidor' })).toBe('Mensaje del servidor');
  });
});

describe('describeError', () => {
  const BASE = 'http://localhost:8000';
  it('translates known technical codes without changing them', () => {
    const err = { code: 'no_training_samples', message: 'raw' };
    expect(describeError('es', err, BASE)).toContain('muestras de entrenamiento');
    expect(describeError('en', err, BASE)).toContain('training samples');
    expect(err.code).toBe('no_training_samples');
  });
  it('includes the API base for network errors', () => {
    expect(describeError('en', { code: 'network_error', message: 'x' }, BASE)).toContain(BASE);
  });
  it('maps generic HTTP codes', () => {
    expect(describeError('es', { code: 'http_503', message: 'x' }, BASE)).toContain('503');
  });
  it('falls back to the raw message, then to a generic text', () => {
    expect(describeError('es', { code: 'weird', message: 'raw msg' }, BASE)).toBe('raw msg');
    expect(describeError('en', {}, BASE)).toBe('Unexpected error.');
    expect(describeError('en', 'boom', BASE)).toBe('Unexpected error.');
  });
  it('lists translated blocking errors for preflight_failed', () => {
    const err = { code: 'preflight_failed', message: 'x', details: [{ code: 'no_post_images', message: 'm' }] };
    expect(describeError('es', err, BASE)).toContain('POST');
  });
});

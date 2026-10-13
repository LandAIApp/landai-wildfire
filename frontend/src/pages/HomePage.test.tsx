// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ANALYSIS, CONFIG, EXPOSURE, noOsmExposure, partialExposure } from '../test/fixtures';

// The real map is Leaflet (not meaningful in jsdom): a stub exposes the drawing callbacks to the tests.
vi.mock('../components/MapView', () => ({
  default: (props: Record<string, unknown> & {
    onPoint: (p: [number, number]) => void; onFinish: () => void; onRingChange: (r: [number, number][]) => void;
    exposure: unknown; drawTool: string | null;
  }) => (
    <div data-testid="map-mock" data-tool={props.drawTool ?? ''} data-has-exposure={String(!!props.exposure)}>
      <button onClick={() => props.onPoint([-75, 4])}>pt1</button>
      <button onClick={() => props.onPoint([-74.9, 4])}>pt2</button>
      <button onClick={() => props.onPoint([-74.9, 4.1])}>pt3</button>
      <button onClick={() => props.onPoint([-75, 4.1])}>pt4</button>
      <button onClick={() => props.onFinish()}>finish-map</button>
      <button onClick={() => props.onRingChange([[-75, 4], [-74.99, 4], [-74.99, 4.01], [-75, 4.01], [-75, 4]])}>move-vertex</button>
    </div>
  ),
}));

const api = vi.hoisted(() => ({
  config: vi.fn(), departments: vi.fn(), municipalities: vi.fn(), preflight: vi.fn(), analyze: vi.fn(),
  exposure: vi.fn(), recordedDemo: vi.fn(),
}));
vi.mock('../services/api', () => ({ API_BASE: 'http://test', api }));

import { LanguageProvider } from '../i18n/LanguageContext';
import HomePage from './HomePage';

function renderPage(lang: 'es' | 'en' = 'en') {
  return render(<LanguageProvider initial={lang}><HomePage /></LanguageProvider>);
}

beforeEach(() => {
  api.config.mockResolvedValue(CONFIG);
  api.departments.mockResolvedValue({ departments: ['Tolima'] });
  api.municipalities.mockResolvedValue({ municipalities: ['San Luis'] });
  api.preflight.mockResolvedValue({ status: 'ok', valid: true, pre_count: 5, post_count: 2, history_count: 9,
    date_windows: ANALYSIS.date_windows, aoi_hectares: 28000, aoi_kind: 'municipality', warnings: [], blocking_errors: [] });
  api.analyze.mockResolvedValue(ANALYSIS);
  api.exposure.mockResolvedValue(EXPOSURE);
  api.recordedDemo.mockResolvedValue(null);
});
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

const click = (name: RegExp | string) => fireEvent.click(screen.getByRole('button', { name }));
const clickTab = async (name: string) => {
  await waitFor(() => expect((screen.getByRole('tab', { name }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('tab', { name }));
};
const drawSquare = async (lang: 'es' | 'en' = 'en') => {
  await clickTab(lang === 'en' ? 'Draw area' : 'Dibujar área');
  click(lang === 'en' ? 'Polygon' : 'Polígono');
  for (const p of ['pt1', 'pt2', 'pt3', 'pt4']) click(p);
  click('finish-map');
};

describe('Mode A: municipality (unchanged contract)', () => {
  it('sends department + municipality and never a geometry', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText('Municipality')).toBeTruthy());
    fireEvent.change(await screen.findByLabelText('Department'), { target: { value: 'Tolima' } });
    await waitFor(() => expect((screen.getByLabelText('Municipality') as HTMLSelectElement).options.length).toBeGreaterThan(1));
    fireEvent.change(screen.getByLabelText('Municipality'), { target: { value: 'San Luis' } });
    click('Analyze Wildfire');
    await waitFor(() => expect(api.analyze).toHaveBeenCalled());
    const body = api.analyze.mock.calls[0][0];
    expect(body.department).toBe('Tolima');
    expect(body.municipality).toBe('San Luis');
    expect('geometry' in body).toBe(false);
  });
});

describe('Mode B: draw a custom study area', () => {
  it('draws a polygon, shows ha and km² and sends only the geometry', async () => {
    renderPage();
    await drawSquare();
    const value = screen.getByTestId('area-value').textContent ?? '';
    expect(value).toMatch(/ha/);
    expect(value).toMatch(/km²/);
    expect(screen.getByTestId('area-level').textContent).toMatch(/Within the limit/);
    click('Analyze Wildfire');
    await waitFor(() => expect(api.analyze).toHaveBeenCalled());
    const body = api.analyze.mock.calls[0][0];
    expect(body.geometry.type).toBe('Polygon');
    expect(body.geometry.coordinates[0]).toHaveLength(5);
    expect(body.geometry.coordinates[0][0]).toEqual(body.geometry.coordinates[0][4]);
    expect('department' in body).toBe(false);
    expect('municipality' in body).toBe(false);
  });

  it('uses the limit announced by the backend, not a hard-coded one', async () => {
    api.config.mockResolvedValue({ ...CONFIG, aoi: { ...CONFIG.aoi, custom: { ...CONFIG.aoi.custom, max_hectares: 2000, warn_hectares: 1000 } } });
    renderPage();
    await waitFor(() => expect(api.config).toHaveBeenCalled());
    await drawSquare();
    // ~12,300 ha square is far above 2,000 ha
    await waitFor(() => expect(screen.getByTestId('area-level').textContent).toMatch(/Exceeds/));
    expect((screen.getByRole('button', { name: 'Analyze Wildfire' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Check Data' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('area-foot').textContent).toMatch(/2,000/);
  });

  it('warns near the limit but still allows the run', async () => {
    api.config.mockResolvedValue({ ...CONFIG, aoi: { ...CONFIG.aoi, custom: { ...CONFIG.aoi.custom, max_hectares: 20000, warn_hectares: 10000 } } });
    renderPage();
    await waitFor(() => expect(api.config).toHaveBeenCalled());
    await drawSquare();
    await waitFor(() => expect(screen.getByTestId('area-level').textContent).toMatch(/Close to the limit/));
    expect((screen.getByRole('button', { name: 'Analyze Wildfire' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('blocks a self-intersecting polygon', async () => {
    renderPage();
    await clickTab('Draw area'); click('Polygon');
    for (const p of ['pt1', 'pt3', 'pt2', 'pt4']) click(p);   // bow-tie
    click('finish-map');
    expect(screen.getByText(/crosses itself/i)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Analyze Wildfire' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('edits (vertex move) and deletes the area', async () => {
    renderPage();
    await drawSquare();
    const before = screen.getByTestId('area-value').textContent;
    click('move-vertex');
    await waitFor(() => expect(screen.getByTestId('area-value').textContent).not.toEqual(before));
    fireEvent.click(screen.getAllByRole('button', { name: 'Clear' })[0]);
    expect(screen.getByTestId('area-value').textContent).toBe('—');
    expect((screen.getByRole('button', { name: 'Analyze Wildfire' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('rectangle tool closes after two clicks', async () => {
    renderPage();
    await clickTab('Draw area'); click('Rectangle');
    click('pt1'); click('pt3');
    expect(screen.getByTestId('area-value').textContent).toMatch(/ha/);
  });

  it('is available in Spanish', async () => {
    renderPage('es');
    await clickTab('Dibujar área');
    expect(screen.getByRole('button', { name: 'Polígono' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Rectángulo' })).toBeTruthy();
  });

  it('switching modes never mixes both selections', async () => {
    renderPage();
    await drawSquare();
    await clickTab('By municipality');
    await waitFor(() => expect((screen.getByLabelText('Municipality') as HTMLSelectElement).value).toBe('San Luis'));
    click('Analyze Wildfire');
    await waitFor(() => expect(api.analyze).toHaveBeenCalled());
    const body = api.analyze.mock.calls[0][0];
    expect(body.municipality).toBe('San Luis');
    expect('geometry' in body).toBe(false);          // the drawn polygon is not sent in municipality mode
  });
});

describe('Exposure: explicit action only', () => {
  async function runWildfire() {
    renderPage();
    await drawSquare();
    click('Analyze Wildfire');
    await waitFor(() => expect(api.analyze).toHaveBeenCalled());
    await screen.findByTestId('exposure-action');
  }

  it('does not call the exposure endpoint after the wildfire analysis', async () => {
    await runWildfire();
    expect(api.exposure).not.toHaveBeenCalled();
  });

  it('sends the backend analysis reference (never a polygon) with threshold and buffer', async () => {
    await runWildfire();
    fireEvent.change(screen.getByLabelText('Affected-area threshold'), { target: { value: '0.5' } });
    fireEvent.change(screen.getByLabelText('Proximity zone (m)'), { target: { value: '300' } });
    click('Analyze Exposure');
    await waitFor(() => expect(api.exposure).toHaveBeenCalledTimes(1));
    expect(api.exposure.mock.calls[0][0]).toEqual({ analysis_ref: 'signed-ref.abc', threshold: 0.5, buffer_m: 300 });
    const panel = await screen.findByTestId('exposure-panel');
    expect(within(panel).getByTestId('card-population').textContent).toMatch(/1,234/);
    expect(screen.getByTestId('map-mock').dataset.hasExposure).toBe('true');
  });

  it('disables the action when the area exceeds the exposure limit', async () => {
    api.analyze.mockResolvedValue({ ...ANALYSIS, aoi: { kind: 'drawn', hectares: 80000, department: null, municipality: null } });
    await runWildfire();
    expect((screen.getByRole('button', { name: 'Analyze Exposure' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toMatch(/exceeds the exposure module limit/);
  });

  it('shows loading state for each source while the request runs', async () => {
    let resolve: (v: unknown) => void = () => undefined;
    api.exposure.mockReturnValue(new Promise((r) => { resolve = r; }));
    await runWildfire();
    click('Analyze Exposure');
    const strip = await screen.findByTestId('source-strip');
    expect(strip.textContent).toMatch(/Loading/);
    resolve(EXPOSURE);
    await waitFor(() => expect(screen.getByTestId('exposure-status').textContent).toMatch(/Complete/));
  });

  it('shows a translated error when the exposure request fails, and keeps the wildfire result', async () => {
    api.exposure.mockRejectedValue({ code: 'invalid_analysis_ref', message: 'x' });
    await runWildfire();
    click('Analyze Exposure');
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/expired or is not valid/));
    fireEvent.click(screen.getByTestId('tab-results'));
    expect(screen.getAllByText(/affected area/i).length).toBeGreaterThan(0);
  });

  it('loads a recorded demo only on request and labels it', async () => {
    api.recordedDemo.mockResolvedValue({ recorded: true, recorded_at: '2026-09-30T10:00:00+00:00',
      recorded_from_live_services: true, event: 'San Luis, Tolima', analysis: ANALYSIS, exposure: EXPOSURE });
    renderPage();
    const tab = await screen.findByTestId('tab-exposure');
    fireEvent.click(tab);
    expect(screen.queryByTestId('demo-badge')).toBeNull();
    click('Load recorded demo');
    expect(await screen.findByTestId('demo-badge')).toBeTruthy();
    expect(screen.queryByTestId('exposure-action')).toBeNull();
  });
});

describe('Dashboard rendering', () => {
  async function showExposure(data: unknown, lang: 'es' | 'en' = 'en') {
    api.exposure.mockResolvedValue(data);
    renderPage(lang);
    await drawSquare(lang);
    click(lang === 'en' ? 'Analyze Wildfire' : 'Analizar incendio');
    await screen.findByTestId('exposure-action');
    click(lang === 'en' ? 'Analyze Exposure' : 'Analizar exposición');
    return screen.findByTestId('exposure-status');
  }

  it('partial: population unavailable (never 0) while OSM still renders', async () => {
    await showExposure(partialExposure());
    expect(screen.getByTestId('exposure-status').textContent).toMatch(/Partial/);
    const pop = screen.getByTestId('card-population').textContent ?? '';
    expect(pop).toMatch(/Population estimate unavailable/);
    expect(pop).not.toMatch(/\b0\b/);
    expect(screen.getByTestId('card-buildings').textContent).toMatch(/42/);
    expect(screen.getByTestId('source-worldpop').className).toMatch(/error/);
    expect(screen.getByTestId('source-openstreetmap').className).toMatch(/success/);
    expect(screen.getByTestId('exposure-warnings').textContent).toMatch(/WorldPop/);
  });

  it('OSM failure: unavailable instead of zero, population still shown', async () => {
    await showExposure(noOsmExposure());
    for (const key of ['buildings', 'roads', 'health', 'education']) {
      expect(screen.getByTestId(`card-${key}`).textContent).toMatch(/Unavailable/);
    }
    expect(screen.getByTestId('card-population').textContent).toMatch(/1,234/);
  });

  it('shows the methodological notice verbatim (EN)', async () => {
    await showExposure(EXPOSURE);
    expect(screen.getByTestId('exposure-notice').textContent).toContain(
      'Exposure estimates are preliminary. Intersecting buildings, roads or population with a satellite-derived affected area does not confirm physical damage, casualties or displacement.');
  });

  it('shows the methodological notice verbatim (ES)', async () => {
    await showExposure(EXPOSURE, 'es');
    expect(screen.getByTestId('exposure-notice').textContent).toContain(
      'Las estimaciones de exposición son preliminares. La intersección de edificios, vías o población con un área potencialmente afectada no confirma daños físicos, víctimas ni desplazamientos.');
    expect(screen.getByTestId('card-population').textContent).toMatch(/Población estimada/);
  });

  it('shows summary, context, details and sensitivity', async () => {
    await showExposure(EXPOSURE);
    expect(screen.getByTestId('card-area').textContent).toMatch(/400 ha/);
    expect(screen.getByTestId('card-area').textContent).toMatch(/4\.00 km²/);
    expect(screen.getByTestId('card-pct').textContent).toMatch(/1\.4 %/);
    expect(screen.getByTestId('card-roads').textContent).toMatch(/7\.5/);
    expect(screen.getByTestId('buildings-table').textContent).toMatch(/Residential/);
    expect(screen.getByTestId('roads-table').textContent).toMatch(/Primary/);
    expect(screen.getByTestId('facilities-table').textContent).toMatch(/Clínica Central/);
    expect(screen.getByTestId('sensitivity').textContent).toMatch(/0\.35/);
    expect(screen.getByTestId('proximity').textContent).toMatch(/500 m/);
    expect(screen.getByTestId('pop-note').textContent).toMatch(/not a census count/);
  });

  it('exports GeoJSON, CSV and the report', async () => {
    const created: Blob[] = [];
    URL.createObjectURL = vi.fn((b: Blob) => { created.push(b); return 'blob:x'; });
    URL.revokeObjectURL = vi.fn();
    await showExposure(EXPOSURE);
    fireEvent.click(screen.getByTestId('export-geojson'));
    fireEvent.click(screen.getByTestId('export-csv'));
    fireEvent.click(screen.getByTestId('export-report'));
    expect(created).toHaveLength(3);
    const read = (b: Blob) => new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.readAsText(b); });
    const geo = JSON.parse(await read(created[0]));
    const layers = geo.features.map((f: GeoJSON.Feature) => f.properties?.layer);
    expect(layers).toContain('aoi');
    expect(layers).toContain('footprint');
    const aoi = geo.features.find((f: GeoJSON.Feature) => f.properties?.layer === 'aoi');
    const foot = geo.features.find((f: GeoJSON.Feature) => f.properties?.layer === 'footprint');
    expect(JSON.stringify(aoi.geometry)).not.toEqual(JSON.stringify(foot.geometry));
    expect(await read(created[1])).toContain('affected_area_ha');
    expect(JSON.parse(await read(created[2])).report_type).toBe('landai_exposure_report');
  });
});

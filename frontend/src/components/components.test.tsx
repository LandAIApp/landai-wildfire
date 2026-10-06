import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalyzeResponse } from '../types/api';
import { ALL_IDS, stubLayers } from '../services/layers.test';

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

async function load() {
  const { LanguageProvider } = await import('../i18n/LanguageContext');
  const Header = (await import('./Header')).default;
  const ResultsPanel = (await import('./ResultsPanel')).default;
  const LayerPanel = (await import('./LayerPanel')).default;
  const ControlPanel = (await import('./ControlPanel')).default;
  return { LanguageProvider, Header, ResultsPanel, LayerPanel, ControlPanel };
}

const result: AnalyzeResponse = {
  status: 'ok',
  metadata: { model_version: 'V7.6', equivalence_validated: false, department: 'Tolima', municipality: 'San Luis',
    fire_date: '2026-08-05', analysis_end: '2026-08-15', aoi_hectares: 1000, generated_at: '', disclaimer: '' },
  image_counts: { pre: 5, post: 2, history: 9 },
  date_windows: { pre: { start: null, end: null }, post: { start: null, end: null }, history: { start: null, end: null } },
  training: { positive_samples: 800, negative_samples: 2000, note: '' },
  area_statistics: {},
  area_hectares: [
    { threshold: 0.35, key: 'wf035', label: 'Possible', hectares: 120 },
    { threshold: 0.5, key: 'wf050', label: 'Probable', hectares: 90 },
    { threshold: 0.6, key: 'wf060', label: 'Moderate-high', hectares: 70 },
    { threshold: 0.72, key: 'wf072', label: 'High confidence', hectares: 40 },
    { threshold: 0.85, key: 'wf085', label: 'Very high confidence', hectares: 10 },
  ],
  layers: [], boundary: { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } },
  bounds: [[0, 0], [1, 1]], warnings: [],
};

describe('Header', () => {
  it('renders brand, product, beta tag and the ES | EN switch (Spanish by default)', async () => {
    const { LanguageProvider, Header } = await load();
    const html = renderToString(<LanguageProvider initial="es"><Header /></LanguageProvider>);
    expect(html).toContain('assets/brand/logo-landai-light.png');
    expect(html).toContain('Wildfire Intelligence');
    expect(html).toContain('Land AI Labs · Beta');
    expect(html).toContain('Inteligencia para evaluación preliminar de áreas afectadas');
    expect(html).toMatch(/aria-pressed="true"[^>]*>ES</);
    expect(html).toMatch(/aria-pressed="false"[^>]*>EN</);
  });
  it('switches the subtitle to English', async () => {
    const { LanguageProvider, Header } = await load();
    const html = renderToString(<LanguageProvider initial="en"><Header /></LanguageProvider>);
    expect(html).toContain('Intelligence for preliminary burned-area assessment');
    expect(html).toMatch(/aria-pressed="true"[^>]*>EN</);
  });
});

describe('ResultsPanel', () => {
  it('shows an empty state and the disclaimer before any analysis', async () => {
    const { LanguageProvider, ResultsPanel } = await load();
    const es = renderToString(<LanguageProvider initial="es"><ResultsPanel result={null} /></LanguageProvider>);
    expect(es).toContain('Ejecuta un análisis');
    expect(es).toContain('no es un perímetro oficial de incendio validado');
    const en = renderToString(<LanguageProvider initial="en"><ResultsPanel result={null} /></LanguageProvider>);
    expect(en).toContain('Run an analysis');
    expect(en).toContain('not an officially validated wildfire perimeter');
  });
  it('lists the five thresholds with localized labels', async () => {
    const { LanguageProvider, ResultsPanel } = await load();
    const es = renderToString(<LanguageProvider initial="es"><ResultsPanel result={result} /></LanguageProvider>);
    for (const label of ['Posible', 'Probable', 'Moderada-alta', 'Alta confianza', 'Muy alta confianza']) {
      expect(es).toContain(label);
    }
    for (const t of ['0.35', '0.50', '0.60', '0.72', '0.85']) expect(es).toContain(`≥ ${t}`);
  });
  it('shows the CTA link only when VITE_LANDAI_CONTACT_URL is configured', async () => {
    let m = await load();
    let html = renderToString(<m.LanguageProvider initial="es"><m.ResultsPanel result={result} /></m.LanguageProvider>);
    expect(html).toContain('¿Necesitas este análisis para otro territorio');
    expect(html).not.toContain('Habla con Land AI');

    vi.stubEnv('VITE_LANDAI_CONTACT_URL', 'https://example.com/contacto');
    vi.resetModules();
    m = await load();
    html = renderToString(<m.LanguageProvider initial="es"><m.ResultsPanel result={result} /></m.LanguageProvider>);
    expect(html).toContain('href="https://example.com/contacto"');
    expect(html).toContain('Habla con Land AI →');
    html = renderToString(<m.LanguageProvider initial="en"><m.ResultsPanel result={result} /></m.LanguageProvider>);
    expect(html).toContain('Talk to Land AI →');
  });
});

describe('LayerPanel', () => {
  const noop = () => undefined;
  it('shows main layers and keeps advanced ones collapsed by default', async () => {
    const { LanguageProvider, LayerPanel } = await load();
    const html = renderToString(
      <LanguageProvider initial="es">
        <LayerPanel layers={stubLayers()} visible={{ post: true, burn_050: true }} opacity={{}} onToggle={noop} onOpacity={noop} />
      </LanguageProvider>);
    expect(html).toContain('Principales');
    expect(html).toContain('Imagen POST (posterior)');
    expect(html).toContain('Focos activos VIIRS');
    expect(html).toContain('Avanzadas (9)');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('Cambio dNBR');
    expect(ALL_IDS.length).toBe(13);
  });
  it('renders English group names', async () => {
    const { LanguageProvider, LayerPanel } = await load();
    const html = renderToString(
      <LanguageProvider initial="en">
        <LayerPanel layers={stubLayers()} visible={{}} opacity={{}} onToggle={noop} onOpacity={noop} />
      </LanguageProvider>);
    expect(html).toContain('Main');
    expect(html).toContain('Advanced (9)');
  });
});

describe('ControlPanel', () => {
  it('exposes the example button and localized controls', async () => {
    const { LanguageProvider, ControlPanel } = await load();
    const props = {
      departments: ['Tolima'], municipalities: ['San Luis'], department: 'Tolima', municipality: 'San Luis',
      fireDate: '2026-08-05', endDate: '2026-08-15', minDate: '2018-08-01', maxDate: '2026-12-31',
      busy: null, elapsed: 0, status: { kind: 'idle' as const, text: 'ok' }, preflight: null,
      counts: { pre: null, post: null, history: null },
      onDepartment: () => undefined, onMunicipality: () => undefined, onFireDate: () => undefined,
      onEndDate: () => undefined, onExample: () => undefined, onCheck: () => undefined, onAnalyze: () => undefined,
    };
    const es = renderToString(<LanguageProvider initial="es"><ControlPanel {...props} /></LanguageProvider>);
    for (const s of ['Cargar ejemplo', 'Verificar datos', 'Analizar incendio', 'Imágenes PRE', 'Imágenes históricas']) {
      expect(es).toContain(s);
    }
    const en = renderToString(<LanguageProvider initial="en"><ControlPanel {...props} /></LanguageProvider>);
    for (const s of ['Try example', 'Check Data', 'Analyze Wildfire', 'PRE images', 'History images']) {
      expect(en).toContain(s);
    }
  });
});

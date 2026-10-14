import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AreaPanel from '../components/AreaPanel';
import ControlPanel, { type AreaMode, type Busy, type Status, type StatusKind } from '../components/ControlPanel';
import DrawBar from '../components/DrawBar';
import ExposureAction from '../components/ExposureAction';
import ExposurePanel from '../components/ExposurePanel';
import Header from '../components/Header';
import LayerPanel, { type ExposureLayerEntry } from '../components/LayerPanel';
import MapView, { type DrawTool, type ExposureFocus } from '../components/MapView';
import Methodology from '../components/Methodology';
import ResultsPanel from '../components/ResultsPanel';
import { useI18n } from '../i18n/LanguageContext';
import type { MessageKey, Params } from '../i18n';
import { api, API_BASE } from '../services/api';
import { DEFAULT_CONFIG, mergeConfig } from '../services/config';
import { DEFAULT_EXPOSURE_VISIBLE, EXPOSURE_LAYERS } from '../services/exposure';
import { formatNumber } from '../services/format';
import { areaLevel, closeRing, hasSelfIntersection, rectangleRing, ringAreaHectares } from '../services/geometry';
import { describeError } from '../services/issues';
import { newProgressId, useProgress } from '../services/progress';
import type {
  AnalyzeResponse, ExposureLayerName, ExposureResponse, LngLat, PreflightResponse, PublicConfig,
  RecordedDemo, Ring, WildfireRequest,
} from '../types/api';

// Demonstration parameters (same defaults as the reference GEE app).
const EXAMPLE = {
  department: 'Tolima', municipality: 'San Luis', fireDate: '2026-08-05', endDate: '2026-08-15',
} as const;

const todayIso = () => new Date().toISOString().slice(0, 10);
const round6 = (p: LngLat): LngLat => [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6];
type Tab = 'results' | 'exposure';

/** Status is stored as a message key (or raw error) so it re-translates when the language changes. */
interface StatusState { kind: StatusKind; key?: MessageKey; params?: Params; error?: unknown }

export default function HomePage() {
  const { lang, t } = useI18n();
  const [config, setConfig] = useState<PublicConfig>(DEFAULT_CONFIG);
  const [mode, setMode] = useState<AreaMode>('municipality');
  const [drawTool, setDrawTool] = useState<DrawTool | null>(null);
  const [draft, setDraft] = useState<LngLat[]>([]);
  const [ring, setRing] = useState<Ring | null>(null);
  const [tab, setTab] = useState<Tab>('results');
  const [threshold, setThreshold] = useState<number>(DEFAULT_CONFIG.exposure.default_threshold);
  const [bufferM, setBufferM] = useState<number>(DEFAULT_CONFIG.exposure.default_buffer_m);
  const [exposure, setExposure] = useState<ExposureResponse | null>(null);
  const [exposureLoading, setExposureLoading] = useState(false);
  const [exposureError, setExposureError] = useState<unknown>(null);
  const [exposureVisible, setExposureVisible] = useState<Record<ExposureLayerName, boolean>>(DEFAULT_EXPOSURE_VISIBLE);
  // Real backend stages (polled while a heavy request runs) and guards against double clicks.
  const [analysisPid, setAnalysisPid] = useState<string | null>(null);
  const [exposurePid, setExposurePid] = useState<string | null>(null);
  const analysisInFlight = useRef(false);
  const exposureInFlight = useRef(false);
  const exposureProgress = useProgress(exposurePid, exposureLoading);
  const [focus, setFocus] = useState<ExposureFocus | null>(null);
  const onFocus = (target: { osm?: string; layer?: ExposureLayerName }) => {
    setFocus((f) => ({ ...target, seq: (f?.seq ?? 0) + 1 }));
    document.getElementById('map-section')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  };
  const [demo, setDemo] = useState<RecordedDemo | null>(null);
  const [demoActive, setDemoActive] = useState(false);
  const [departments, setDepartments] = useState<string[]>([]);
  const [municipalities, setMunicipalities] = useState<string[]>([]);
  const [department, setDepartment] = useState('');
  const [municipality, setMunicipality] = useState('');
  const [fireDate, setFireDate] = useState<string>(EXAMPLE.fireDate);
  const [endDate, setEndDate] = useState<string>(EXAMPLE.endDate);

  const [busy, setBusy] = useState<Busy>(null);
  const analysisProgress = useProgress(analysisPid, busy === 'analysis');
  const [elapsed, setElapsed] = useState(0);
  const [statusState, setStatusState] = useState<StatusState>({ kind: 'idle', key: 'status.idle' });
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [opacity, setOpacity] = useState<Record<string, number>>({});
  const timer = useRef<number | null>(null);

  const status = useMemo<Status>(() => ({
    kind: statusState.kind,
    text: statusState.error !== undefined
      ? describeError(lang, statusState.error, API_BASE)
      : t(statusState.key ?? 'status.idle', statusState.params),
  }), [statusState, lang, t]);

  const fail = (error: unknown) => setStatusState({ kind: 'error', error });

  // Authoritative limits from the backend (defaults only until it answers) + optional recorded demo.
  useEffect(() => {
    api.config().then((c) => {
      const merged = mergeConfig(c);
      setConfig(merged);
      setThreshold(merged.exposure.default_threshold);
      setBufferM(merged.exposure.default_buffer_m);
    }).catch(() => { /* keep defaults */ });
    api.recordedDemo().then(setDemo).catch(() => setDemo(null));
  }, []);

  // Load departments once.
  useEffect(() => {
    setBusy('catalog');
    setStatusState({ kind: 'info', key: 'status.loadingDepartments' });
    api.departments()
      .then(({ departments: ds }) => {
        setDepartments(ds);
        if (ds.includes(EXAMPLE.department)) setDepartment(EXAMPLE.department);
        setStatusState({ kind: 'idle', key: 'status.idle' });
      })
      .catch(fail)
      .finally(() => setBusy(null));
  }, []);

  // Load municipalities when the department changes.
  useEffect(() => {
    if (!department) { setMunicipalities([]); setMunicipality(''); return; }
    let cancelled = false;
    setBusy('catalog');
    api.municipalities(department)
      .then(({ municipalities: ms }) => {
        if (cancelled) return;
        setMunicipalities(ms);
        setMunicipality(department === EXAMPLE.department && ms.includes(EXAMPLE.municipality)
          ? EXAMPLE.municipality : (ms[0] ?? ''));
      })
      .catch((e) => !cancelled && fail(e))
      .finally(() => !cancelled && setBusy(null));
    return () => { cancelled = true; };
  }, [department]);

  // Elapsed-time counter while an analysis runs.
  useEffect(() => {
    if (busy === 'analysis') {
      setElapsed(0);
      timer.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    }
    return () => { if (timer.current) { window.clearInterval(timer.current); timer.current = null; } };
  }, [busy]);

  const invalidate = useCallback(() => {
    setPreflight(null);
    setResult(null);
    setExposure(null);
    setExposureError(null);
    setDemoActive(false);
    setTab('results');
    setVisible({});
    setStatusState({ kind: 'idle', key: 'status.inputsChanged' });
  }, []);

  // ---- study-area measurement against the BACKEND-provided limits ----
  const custom = config.aoi.custom;
  const limits = mode === 'draw'
    ? { max: custom.max_hectares, warn: custom.warn_hectares, min: custom.min_hectares, maxVertices: custom.max_vertices }
    : { max: config.aoi.municipality.max_hectares, warn: config.aoi.municipality.warn_hectares, min: 0, maxVertices: custom.max_vertices };
  const drawnPoints = ring ?? (draft.length >= 3 ? draft : null);
  const hectares = mode === 'draw'
    ? (drawnPoints ? ringAreaHectares(drawnPoints) : null)
    : (preflight?.aoi_hectares ?? null);
  const level = areaLevel(hectares, limits, mode === 'draw');
  const vertexCount = ring ? ring.length - 1 : draft.length;
  const selfIntersects = mode === 'draw' && !!ring && hasSelfIntersection(ring);
  const tooManyVertices = mode === 'draw' && vertexCount > custom.max_vertices;
  const areaReady = mode === 'municipality'
    ? !!department && !!municipality
    : !!ring && (level === 'ok' || level === 'warn') && !selfIntersects && !tooManyVertices;

  const body = useMemo<WildfireRequest>(() => (mode === 'municipality'
    ? { department, municipality, fire_date: fireDate, analysis_end: endDate }
    : { geometry: { type: 'Polygon', coordinates: [(ring ?? []).map(round6)] }, fire_date: fireDate, analysis_end: endDate }),
  [mode, department, municipality, ring, fireDate, endDate]);

  // ---- drawing handlers ----
  const stopDrawing = () => { setDrawTool(null); setDraft([]); };
  const onTool = (tool: DrawTool) => {
    invalidate(); setRing(null); setDraft([]); setDrawTool(tool);
    if (window.innerWidth <= 820) {
      window.setTimeout(() => document.getElementById('map-section')?.scrollIntoView({ behavior: 'smooth' }), 50);
    }
  };
  const onPoint = (p: LngLat) => {
    if (drawTool === 'polygon') {
      setDraft((d) => (d.length && d[d.length - 1][0] === p[0] && d[d.length - 1][1] === p[1] ? d : [...d, p]));
    } else if (drawTool === 'rectangle') {
      if (draft.length === 0) { setDraft([p]); return; }
      if (draft[0][0] === p[0] || draft[0][1] === p[1]) return;
      setRing(rectangleRing(draft[0], p));
      stopDrawing();
    }
  };
  const onFinish = () => {
    if (drawTool !== 'polygon' || draft.length < 3) return;
    setRing(closeRing(draft));
    stopDrawing();
  };
  const onClear = () => { invalidate(); setRing(null); stopDrawing(); };
  const onMode = (m: AreaMode) => { invalidate(); stopDrawing(); setMode(m); };

  /** Fills the form with the demonstration case. Does NOT run anything. */
  const onExample = () => {
    invalidate();
    stopDrawing();
    setMode('municipality');
    setDepartment(EXAMPLE.department);
    setMunicipality(EXAMPLE.municipality);
    setFireDate(EXAMPLE.fireDate);
    setEndDate(EXAMPLE.endDate);
    setStatusState({ kind: 'info', key: 'status.exampleLoaded' });
  };

  const onCheck = async () => {
    setBusy('preflight');
    setResult(null);
    setStatusState({ kind: 'info', key: 'status.checking' });
    try {
      const pf = await api.preflight(body);
      setPreflight(pf);
      setStatusState(pf.valid
        ? { kind: 'success', key: 'status.preflightOk' }
        : { kind: 'error', key: 'status.preflightBlocked' });
    } catch (e) {
      setPreflight(null);
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const onAnalyze = async () => {
    if (analysisInFlight.current) return;          // a second click while one request is running is ignored
    analysisInFlight.current = true;
    const pid = newProgressId();
    setAnalysisPid(pid);
    setBusy('analysis');
    setResult(null);
    setStatusState({ kind: 'info', key: 'status.analyzing' });
    try {
      const res = await api.analyze({ ...body, progress_id: pid });
      setResult(res);
      setPreflight(null);
      const v: Record<string, boolean> = {};
      const o: Record<string, number> = {};
      res.layers.forEach((l) => { v[l.id] = l.visible_by_default; o[l.id] = 0.8; });
      setVisible(v);
      setOpacity(o);
      setStatusState(res.warnings.length
        ? { kind: 'warning', key: 'status.doneWarnings' }
        : { kind: 'success', key: 'status.done' });
      // On phones the map sits below the controls: bring it into view.
      if (window.innerWidth <= 820) {
        window.setTimeout(() => document.getElementById('map-section')?.scrollIntoView({ behavior: 'smooth' }), 100);
      }
    } catch (e) {
      fail(e);
    } finally {
      analysisInFlight.current = false;
      setBusy(null);
    }
  };

  const onExposure = async () => {
    if (!result?.analysis_ref || exposureInFlight.current) return;   // ignore repeated clicks
    exposureInFlight.current = true;
    const pid = newProgressId();
    setExposurePid(pid);
    setExposureLoading(true);
    setExposureError(null);
    setExposure(null);
    setTab('exposure');
    try {
      const res = await api.exposure({ analysis_ref: result.analysis_ref, threshold, buffer_m: bufferM, progress_id: pid });
      setExposure(res);
      setExposureVisible(DEFAULT_EXPOSURE_VISIBLE);
    } catch (e) {
      setExposureError(e);
    } finally {
      exposureInFlight.current = false;
      setExposureLoading(false);
    }
  };

  /** Loads a REAL result recorded earlier (clearly labelled); nothing is computed or invented. */
  const onLoadDemo = () => {
    if (!demo) return;
    invalidate();
    stopDrawing();
    setDemoActive(true);
    setResult(demo.analysis);
    setExposure(demo.exposure);
    setExposureVisible(DEFAULT_EXPOSURE_VISIBLE);
    setTab('exposure');
  };

  const exposureEntries: ExposureLayerEntry[] = exposure
    ? EXPOSURE_LAYERS.flatMap((name) => {
      const fc = exposure.layers[name];
      return fc && fc.features.length ? [{ name, total: fc.metadata?.total ?? fc.features.length, shown: fc.features.length }] : [];
    })
    : [];
  const showTabs = !!result || !!exposure || exposureLoading || !!demo;

  const counts = result
    ? result.image_counts
    : { pre: preflight?.pre_count ?? null, post: preflight?.post_count ?? null,
        history: preflight?.history_count ?? null };

  const areaPanel = (
    <AreaPanel
      mode={mode} drawTool={drawTool} draftCount={draft.length} hasRing={!!ring} vertexCount={vertexCount}
      hectares={hectares} level={level} limits={limits} selfIntersects={selfIntersects}
      tooManyVertices={tooManyVertices} disabled={busy !== null}
      onTool={onTool} onFinish={onFinish} onUndo={() => setDraft((d) => d.slice(0, -1))} onClear={onClear}
    />
  );

  return (
    <div className="app">
      <Header />
      <div className="body">
        <aside className="sidebar">
          <ControlPanel
            mode={mode} onMode={onMode} areaSlot={areaPanel} areaReady={areaReady} maxHectares={limits.max}
            departments={departments} municipalities={municipalities}
            department={department} municipality={municipality}
            fireDate={fireDate} endDate={endDate} minDate={config.aoi.min_fire_date} maxDate={todayIso()}
            busy={busy} elapsed={elapsed} status={status} preflight={preflight} counts={counts}
            progress={analysisProgress} paused={config.service?.analysis_enabled === false}
            onDepartment={(v) => { setDepartment(v); invalidate(); }}
            onMunicipality={(v) => { setMunicipality(v); invalidate(); }}
            onFireDate={(v) => { setFireDate(v); invalidate(); }}
            onEndDate={(v) => { setEndDate(v); invalidate(); }}
            onExample={onExample} onCheck={onCheck} onAnalyze={onAnalyze}
          />
          {showTabs && (
            <div className="tabs" role="tablist" aria-label={t('tabs.results')}>
              {(['results', 'exposure'] as const).map((k) => (
                <button key={k} type="button" role="tab" aria-selected={tab === k} data-testid={`tab-${k}`}
                        className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>
                  {t(`tabs.${k}` as 'tabs.results')}
                </button>
              ))}
            </div>
          )}
          {tab === 'results' && (
            <>
              <ResultsPanel result={result} />
              {result && !demoActive && (
                <ExposureAction
                  result={result} config={config} threshold={threshold} bufferM={bufferM}
                  running={exposureLoading} disabled={busy !== null}
                  paused={config.service?.exposure_enabled === false}
                  onThreshold={setThreshold} onBuffer={setBufferM} onRun={onExposure}
                />
              )}
              <Methodology result={result} />
            </>
          )}
          {tab === 'exposure' && (
            <ExposurePanel
              exposure={exposure} loading={exposureLoading} error={exposureError} apiBase={API_BASE} progress={exposureProgress}
              demoRecordedAt={demoActive && demo ? demo.recorded_at : null}
              canLoadDemo={!!demo} onLoadDemo={onLoadDemo} onFocus={onFocus}
            />
          )}
        </aside>
        <main className="map-wrap" id="map-section">
          <MapView
            layers={result?.layers ?? []} visible={visible} opacity={opacity}
            boundary={result?.boundary ?? null} bounds={result?.bounds ?? null}
            drawTool={mode === 'draw' ? drawTool : null} draft={draft} ring={mode === 'draw' ? ring : null}
            level={level}
            limitChip={mode === 'draw' ? t('map.limitChip', { max: formatNumber(limits.max, lang) }) : undefined}
            onPoint={onPoint} onFinish={onFinish}
            onRingChange={(r) => { setRing(r); invalidate(); }}
            exposure={exposure?.layers ?? null} exposureVisible={exposureVisible} focus={focus}
          />
          {mode === 'draw' && !result && (
            <DrawBar
              hectares={hectares} level={level} maxHectares={limits.max}
              drawing={drawTool !== null} isPolygon={drawTool === 'polygon'} draftCount={draft.length}
              hasRing={!!ring} onFinish={onFinish} onUndo={() => setDraft((d) => d.slice(0, -1))} onClear={onClear}
            />
          )}
          <LayerPanel layers={result?.layers ?? []} visible={visible} opacity={opacity}
                      onToggle={(id) => setVisible((v) => ({ ...v, [id]: !v[id] }))}
                      onOpacity={(id, val) => setOpacity((o) => ({ ...o, [id]: val }))}
                      exposureLayers={exposureEntries} exposureVisible={exposureVisible}
                      onExposureToggle={(name) => setExposureVisible((v) => ({ ...v, [name]: !v[name] }))} />
        </main>
      </div>
    </div>
  );
}

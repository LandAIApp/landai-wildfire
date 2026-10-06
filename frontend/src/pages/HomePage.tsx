import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from '../components/Header';
import ControlPanel, { type Busy, type Status, type StatusKind } from '../components/ControlPanel';
import LayerPanel from '../components/LayerPanel';
import MapView from '../components/MapView';
import Methodology from '../components/Methodology';
import ResultsPanel from '../components/ResultsPanel';
import { useI18n } from '../i18n/LanguageContext';
import type { MessageKey, Params } from '../i18n';
import { api, API_BASE } from '../services/api';
import { describeError } from '../services/issues';
import type { AnalyzeResponse, PreflightResponse, WildfireRequest } from '../types/api';

// Demonstration parameters (same defaults as the reference GEE app).
const EXAMPLE = {
  department: 'Tolima', municipality: 'San Luis', fireDate: '2026-08-05', endDate: '2026-08-15',
} as const;
const MIN_DATE = '2018-08-01';

const todayIso = () => new Date().toISOString().slice(0, 10);

/** Status is stored as a message key (or raw error) so it re-translates when the language changes. */
interface StatusState { kind: StatusKind; key?: MessageKey; params?: Params; error?: unknown }

export default function HomePage() {
  const { lang, t } = useI18n();
  const [departments, setDepartments] = useState<string[]>([]);
  const [municipalities, setMunicipalities] = useState<string[]>([]);
  const [department, setDepartment] = useState('');
  const [municipality, setMunicipality] = useState('');
  const [fireDate, setFireDate] = useState<string>(EXAMPLE.fireDate);
  const [endDate, setEndDate] = useState<string>(EXAMPLE.endDate);

  const [busy, setBusy] = useState<Busy>(null);
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
    setVisible({});
    setStatusState({ kind: 'idle', key: 'status.inputsChanged' });
  }, []);

  const body = useMemo<WildfireRequest>(() => ({
    department, municipality, fire_date: fireDate, analysis_end: endDate,
  }), [department, municipality, fireDate, endDate]);

  /** Fills the form with the demonstration case. Does NOT run anything. */
  const onExample = () => {
    invalidate();
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
    setBusy('analysis');
    setResult(null);
    setStatusState({ kind: 'info', key: 'status.analyzing' });
    try {
      const res = await api.analyze(body);
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
      setBusy(null);
    }
  };

  const counts = result
    ? result.image_counts
    : { pre: preflight?.pre_count ?? null, post: preflight?.post_count ?? null,
        history: preflight?.history_count ?? null };

  return (
    <div className="app">
      <Header />
      <div className="body">
        <aside className="sidebar">
          <ControlPanel
            departments={departments} municipalities={municipalities}
            department={department} municipality={municipality}
            fireDate={fireDate} endDate={endDate} minDate={MIN_DATE} maxDate={todayIso()}
            busy={busy} elapsed={elapsed} status={status} preflight={preflight} counts={counts}
            onDepartment={(v) => { setDepartment(v); invalidate(); }}
            onMunicipality={(v) => { setMunicipality(v); invalidate(); }}
            onFireDate={(v) => { setFireDate(v); invalidate(); }}
            onEndDate={(v) => { setEndDate(v); invalidate(); }}
            onExample={onExample} onCheck={onCheck} onAnalyze={onAnalyze}
          />
          <ResultsPanel result={result} />
          <Methodology result={result} />
        </aside>
        <main className="map-wrap" id="map-section">
          <MapView layers={result?.layers ?? []} visible={visible} opacity={opacity}
                   boundary={result?.boundary ?? null} bounds={result?.bounds ?? null} />
          <LayerPanel layers={result?.layers ?? []} visible={visible} opacity={opacity}
                      onToggle={(id) => setVisible((v) => ({ ...v, [id]: !v[id] }))}
                      onOpacity={(id, val) => setOpacity((o) => ({ ...o, [id]: val }))} />
        </main>
      </div>
    </div>
  );
}

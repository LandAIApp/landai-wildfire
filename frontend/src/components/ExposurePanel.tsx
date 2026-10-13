import BarChart from './BarChart';
import { useI18n } from '../i18n/LanguageContext';
import {
  buildGeoJson, buildReport, displayMetric, displayPopulation, download, exportFileName, sourceState,
  warningKey, type MetricDisplay,
} from '../services/exposure';
import { formatArea, formatDateTime, formatDecimal, formatKm2, formatNumber } from '../services/format';
import { describeError } from '../services/issues';
import type { ExposureLayerName, ExposureMetric, ExposureResponse, SourceKey } from '../types/api';

interface Props {
  exposure: ExposureResponse | null;
  loading: boolean;
  error: unknown;
  apiBase: string;
  /** Present when the data is a recorded demo (real results recorded earlier). */
  demoRecordedAt: string | null;
  canLoadDemo: boolean;
  onLoadDemo: () => void;
  /** Zoom the map to a feature (OSM id) or to a whole exposure layer. */
  onFocus?: (target: { osm?: string; layer?: ExposureLayerName }) => void;
}

const SOURCES: SourceKey[] = ['earth_observation', 'openstreetmap', 'worldpop'];
const BUILDING_ORDER = ['residential', 'commercial', 'industrial', 'public', 'agricultural', 'other'];

function Value({ d, unit }: { d: MetricDisplay; unit?: string }) {
  const { t } = useI18n();
  if (d.kind === 'value') return <strong>{d.text}{unit ? <small> {unit}</small> : null}</strong>;
  return <strong className="missing">{d.reason === 'no_osm_data' ? t('exposure.noOsmData') : t('exposure.unavailable')}</strong>;
}

export default function ExposurePanel(p: Props) {
  const { lang, t, tOptional } = useI18n();
  const res = p.exposure;

  const header = (
    <div className="card-head">
      <h2>{t('exposure.title')}</h2>
      {res && (
        <span className={`badge ${res.status}`} data-testid="exposure-status">
          {t(res.status === 'success' ? 'exposure.status.success' : 'exposure.status.partial')}
        </span>
      )}
    </div>
  );

  if (p.loading) {
    return (
      <section className="card exposure-panel" data-testid="exposure-panel">
        {header}
        <div className="status info"><span className="spinner" aria-hidden /><span>{t('exposure.running')}</span></div>
        <SourceStrip res={null} loading />
      </section>
    );
  }

  if (!res) {
    return (
      <section className="card exposure-panel" data-testid="exposure-panel">
        {header}
        {p.error !== null && p.error !== undefined && (
          <div className="alert error" role="alert">{describeError(lang, p.error, p.apiBase)}</div>
        )}
        <p className="muted">{t('exposure.empty')}</p>
        {p.canLoadDemo && (
          <button type="button" className="btn secondary" onClick={p.onLoadDemo}>{t('exposure.loadDemo')}</button>
        )}
        <Notice />
      </section>
    );
  }

  const m = res.metrics;
  const a = res.analysis;
  const buffer = formatNumber(a.buffer_m, lang);
  const osm = res.sources.openstreetmap;
  const dateLabel = p.demoRecordedAt ? formatDateTime(p.demoRecordedAt, lang) : '';
  const pop = m.population;
  const popDisplay = displayPopulation(res, lang);

  const within = (metric: ExposureMetric) =>
    metric.value === null ? null : t('exposure.card.withinBuffer', { count: formatNumber(metric.value, lang), buffer });

  const card = (key: string, label: string, body: JSX.Element, hint?: string | null, sub?: string | null) => (
    <div className="metric-card" key={key} data-testid={`card-${key}`}>
      <span className="metric-label">{label}</span>
      {body}
      {sub && <span className="metric-sub">{sub}</span>}
      {hint && <span className="metric-hint">{hint}</span>}
    </div>
  );

  return (
    <section className="card exposure-panel" data-testid="exposure-panel">
      {header}
      {p.demoRecordedAt && (
        <div className="alert info" data-testid="demo-badge">
          {t('exposure.demoBadge', { date: dateLabel })}. {t('exposure.demoNote', { date: dateLabel })}
        </div>
      )}
      <SourceStrip res={res} loading={false} />
      {res.status === 'partial' && <p className="muted small">{t('exposure.sourceState.partialNote')}</p>}

      <div className="metric-grid">
        {card('area', t('exposure.card.area'),
          <strong>{formatArea(m.affected_area_ha, lang)}</strong>, null, formatKm2(m.affected_area_ha, lang))}
        {card('pct', t('exposure.card.pct'),
          m.affected_pct_of_aoi === null ? <strong className="missing">{t('exposure.unavailable')}</strong>
            : <strong>{formatDecimal(m.affected_pct_of_aoi, lang, 1)} %</strong>,
          null, formatArea(a.aoi_hectares, lang))}
        {card('population', t('exposure.card.population'),
          popDisplay.kind === 'value' ? <strong>{popDisplay.text}</strong>
            : <strong className="missing">{pop.status === 'skipped' ? t('exposure.skipped') : t('exposure.popUnavailable')}</strong>,
          popDisplay.kind === 'value'
            ? t('exposure.card.populationHint', { year: pop.year ?? '', resolution: pop.resolution ?? '' }) : null)}
        {card('buildings', t('exposure.card.buildings'),
          <Value d={displayMetric(m.buildings_intersecting, lang)} />, t('exposure.card.buildingsHint'),
          within(m.buildings_within_buffer))}
        {card('roads', t('exposure.card.roads'),
          <Value d={displayMetric(m.roads_km_intersecting, lang, 1)} unit={t('exposure.unit.km')} />, t('exposure.card.roadsHint'),
          m.roads_km_within_buffer.value === null ? null
            : t('exposure.card.withinBuffer', { count: `${formatDecimal(m.roads_km_within_buffer.value, lang, 1)} km`, buffer }))}
        {card('health', t('exposure.card.health'),
          <Value d={displayMetric(m.health_intersecting, lang)} />, t('exposure.card.healthHint'), within(m.health_within_buffer))}
        {card('education', t('exposure.card.education'),
          <Value d={displayMetric(m.education_intersecting, lang)} />, t('exposure.card.educationHint'), within(m.education_within_buffer))}
      </div>

      <Notice />

      {pop.value !== null && (
        <p className="muted small" data-testid="pop-note">
          {t('exposure.pop.uncertainty')}
          {pop.simplification?.applied && ` ${t('exposure.pop.simplified', {
            before: pop.simplification.vertices_before, after: pop.simplification.vertices_after,
            change: formatDecimal(pop.simplification.area_change_pct, lang, 2) })}`}
        </p>
      )}

      {res.warnings.length > 0 && (
        <div className="warn-list" data-testid="exposure-warnings">
          {res.warnings.map((w, i) => (
            <div key={i} className="alert warning">
              {tOptional(warningKey(w.code), w.params as Record<string, string | number>) ?? w.message}
            </div>
          ))}
        </div>
      )}
      {a.custom_aoi_note && <div className="alert info">{t('draw.customNote')}</div>}

      <h3>{t('exposure.ctx.title')}</h3>
      <dl className="context">
        <dt>{t('exposure.ctx.event')}</dt><dd>{a.event_date ?? '—'}</dd>
        <dt>{t('exposure.ctx.analysisEnd')}</dt><dd>{a.analysis_end ?? '—'}</dd>
        <dt>{t('exposure.ctx.generated')}</dt><dd>{formatDateTime(a.generated_at, lang)}</dd>
        <dt>{t('exposure.ctx.aoi')}</dt><dd>{formatArea(a.aoi_hectares, lang)} · {formatKm2(a.aoi_hectares, lang)}</dd>
        <dt>{t('exposure.ctx.s2')}</dt>
        <dd>{a.date_windows
          ? `${a.date_windows.pre.start ?? '—'} → ${a.date_windows.post.end ?? '—'}` : '—'}</dd>
        <dt>{t('exposure.ctx.threshold')}</dt>
        <dd>{a.threshold !== null ? `≥ ${a.threshold.toFixed(2)}` : '—'}{a.threshold_label ? ` · ${a.threshold_label}` : ''}</dd>
        <dt>{t('exposure.ctx.buffer')}</dt><dd>{buffer} m</dd>
        <dt>{t('exposure.ctx.popYear')}</dt><dd>{pop.year ?? '—'}{pop.resolution ? ` · ${pop.resolution}` : ''}</dd>
        <dt>{t('exposure.ctx.osm')}</dt>
        <dd>{osm?.status === 'success' ? formatDateTime(String(osm.details.retrieved_at ?? ''), lang) : t('exposure.unavailable')}</dd>
        <dt>{t('exposure.ctx.sources')}</dt>
        <dd>{SOURCES.map((s) => t(`exposure.source.${s}` as 'exposure.source.worldpop')).join(' · ')}</dd>
      </dl>
      <p className="muted small">{t('exposure.ctx.popNote')}</p>

      <details className="definitions">
        <summary>{t('exposure.def.title')}</summary>
        <ul>
          <li>{t('exposure.def.study')}</li>
          <li>{t('exposure.def.affected')}</li>
          <li>{t('exposure.def.geometry')}</li>
          <li>{t('exposure.def.exposed')}</li>
          <li>{t('exposure.def.buffer', { buffer })}</li>
        </ul>
      </details>

      <Details res={res} onFocus={p.onFocus} />

      {res.sensitivity.length > 0 && (
        <>
          <h3>{t('exposure.sens.title')}</h3>
          <BarChart testId="sensitivity-chart" title={t('exposure.sens.title')}
            rows={res.sensitivity.map((r) => ({ key: r.key, label: `≥ ${r.threshold.toFixed(2)}`, value: r.area_ha,
              text: `${formatNumber(r.area_ha, lang)} ha`, highlight: r.selected }))} />
          <div className="table-scroll">
            <table className="results" data-testid="sensitivity">
              <thead><tr>
                <th>{t('exposure.sens.threshold')}</th><th className="num">{t('exposure.sens.area')}</th>
                <th className="num">{t('exposure.sens.buildings')}</th><th className="num">{t('exposure.sens.roads')}</th>
                <th className="num">{t('exposure.sens.health')}</th><th className="num">{t('exposure.sens.education')}</th>
              </tr></thead>
              <tbody>
                {res.sensitivity.map((r) => (
                  <tr key={r.key} className={r.selected ? 'highlight' : ''}>
                    <td>{`≥ ${r.threshold.toFixed(2)}`}</td>
                    <td className="num">{formatNumber(r.area_ha, lang)}</td>
                    <td className="num">{r.buildings_intersecting === null ? '—' : formatNumber(r.buildings_intersecting, lang)}</td>
                    <td className="num">{r.roads_km_intersecting === null ? '—' : formatDecimal(r.roads_km_intersecting, lang, 1)}</td>
                    <td className="num">{r.health_intersecting === null ? '—' : formatNumber(r.health_intersecting, lang)}</td>
                    <td className="num">{r.education_intersecting === null ? '—' : formatNumber(r.education_intersecting, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">{t('exposure.sens.note')} {t('exposure.sens.popNote')}</p>
        </>
      )}

      <h3>{t('exposure.export.title')}</h3>
      <div className="button-row">
        <button type="button" className="btn secondary" data-testid="export-geojson"
                onClick={() => download(exportFileName(res, 'geojson'), JSON.stringify(buildGeoJson(res)), 'application/geo+json')}>
          {t('exposure.export.geojson')}
        </button>
        <button type="button" className="btn secondary" data-testid="export-csv"
                onClick={() => download(exportFileName(res, 'csv'), res.exports.csv, 'text/csv;charset=utf-8')}>
          {t('exposure.export.csv')}
        </button>
        <button type="button" className="btn secondary" data-testid="export-report"
                onClick={() => download(exportFileName(res, 'json'), JSON.stringify(buildReport(res, p.demoRecordedAt ? { recorded_demo_at: p.demoRecordedAt } : {}), null, 2), 'application/json')}>
          {t('exposure.export.report')}
        </button>
      </div>
      <p className="muted small">{t('exposure.export.hint')}</p>
      <p className="attribution small">{t('exposure.attribution')}</p>
    </section>
  );
}

function Notice() {
  const { t } = useI18n();
  return (
    <div className="method-notice" role="note" data-testid="exposure-notice">
      <strong>{t('exposure.notice.title')}</strong>
      <p>{t('exposure.notice.text')}</p>
    </div>
  );
}

function SourceStrip({ res, loading }: { res: ExposureResponse | null; loading: boolean }) {
  const { t } = useI18n();
  return (
    <div className="source-strip" data-testid="source-strip">
      {SOURCES.map((s) => {
        const state = sourceState(res, s, loading);
        const error = res?.sources[s]?.error;
        return (
          <div key={s} className={`source-chip ${state}`} data-testid={`source-${s}`} title={error?.message}>
            <span>{t(`exposure.source.${s}` as 'exposure.source.worldpop')}</span>
            <strong>{t(`exposure.sourceState.${state}` as 'exposure.sourceState.idle')}</strong>
          </div>
        );
      })}
    </div>
  );
}

function Details({ res, onFocus }: { res: ExposureResponse; onFocus?: Props['onFocus'] }) {
  const { lang, t, tOptional } = useI18n();
  const d = res.details;
  const buffer = formatNumber(res.analysis.buffer_m, lang);
  const m = res.metrics;
  const facilities = [
    ...(d.health_facilities ?? []).map((f) => ({ ...f, kind: 'health' })),
    ...(d.education_facilities ?? []).map((f) => ({ ...f, kind: 'education' })),
  ];
  const noFacilityData = d.health_facilities == null && d.education_facilities == null;
  return (
    <>
      <h3>{t('exposure.details.facilities')}</h3>
      {noFacilityData ? <p className="muted">{t('exposure.noOsmData')}</p>
        : facilities.length === 0 ? <p className="muted">{t('exposure.facility.none')}</p> : (
          <table className="results" data-testid="facilities-table">
            <thead><tr><th>{t('exposure.col.name')}</th><th>{t('exposure.col.class')}</th>
              <th className="num">{t('exposure.col.distance')}</th><th>{t('exposure.col.status')}</th></tr></thead>
            <tbody>
              {facilities.map((f) => (
                <tr key={`${f.kind}-${f.osm}`}>
                  <td>{onFocus && f.osm
                    ? <button type="button" className="link-btn" onClick={() => onFocus({ osm: f.osm })}
                              title={t('exposure.viewOnMap')}>{f.name ?? t('exposure.popup.noName')} ⌖</button>
                    : (f.name ?? t('exposure.popup.noName'))}</td>
                  <td>{f.kind === 'health' ? t('exposure.card.health') : t('exposure.card.education')} · {f.class}</td>
                  <td className="num">{formatNumber(f.distance_m, lang)} m</td>
                  <td>{tOptional(`exposure.facility.${f.status}`) ?? f.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

      <details className="more-detail" data-testid="more-detail">
        <summary>{t('exposure.details.more')}</summary>
      <h3>{t('exposure.details.buildings')}
        {onFocus && res.layers?.buildings?.features?.length ? (
          <button type="button" className="link-btn" onClick={() => onFocus({ layer: 'buildings' })}>
            {t('exposure.viewOnMap')} ⌖</button>) : null}
      </h3>
      {d.buildings_by_category ? (
        <>
        <BarChart testId="buildings-chart" title={t('exposure.details.buildings')}
          legend={{ main: t('exposure.col.inside'), total: t('exposure.col.near') }}
          rows={BUILDING_ORDER.filter((c) => d.buildings_by_category![c]
            && (d.buildings_by_category![c].within_buffer > 0 || d.buildings_by_category![c].intersecting > 0))
            .map((c) => ({ key: c, label: tOptional(`exposure.building.${c}`) ?? c,
              value: d.buildings_by_category![c].intersecting, total: d.buildings_by_category![c].within_buffer,
              text: `${formatNumber(d.buildings_by_category![c].intersecting, lang)} / ${formatNumber(d.buildings_by_category![c].within_buffer, lang)}` }))} />
        <details className="table-toggle"><summary>{t('exposure.viewTable')}</summary>
        <table className="results" data-testid="buildings-table">
          <thead><tr><th>{t('exposure.col.category')}</th><th className="num">{t('exposure.col.inside')}</th>
            <th className="num">{t('exposure.col.near')}</th></tr></thead>
          <tbody>
            {BUILDING_ORDER.map((c) => d.buildings_by_category![c] && (
              <tr key={c}><td>{tOptional(`exposure.building.${c}`) ?? c}</td>
                <td className="num">{formatNumber(d.buildings_by_category![c].intersecting, lang)}</td>
                <td className="num">{formatNumber(d.buildings_by_category![c].within_buffer, lang)}</td></tr>
            ))}
          </tbody>
        </table>
        </details>
        </>
      ) : <p className="muted">{m.buildings_intersecting.coverage === 'unavailable' ? t('exposure.unavailable') : t('exposure.noOsmData')}</p>}

      <h3>{t('exposure.details.roads')}</h3>
      {d.roads_km_by_class ? (
        Object.keys(d.roads_km_by_class).length ? (
          <>
          <BarChart testId="roads-chart" title={t('exposure.details.roads')}
            rows={Object.entries(d.roads_km_by_class).sort((a, b) => b[1] - a[1]).map(([c, km]) => ({
              key: c, label: tOptional(`exposure.road.${c}`) ?? c, value: km, text: `${formatDecimal(km, lang, 2)} km` }))} />
          <details className="table-toggle"><summary>{t('exposure.viewTable')}</summary>
          <table className="results" data-testid="roads-table">
            <thead><tr><th>{t('exposure.col.class')}</th><th className="num">{t('exposure.col.km')}</th></tr></thead>
            <tbody>
              {Object.entries(d.roads_km_by_class).map(([c, km]) => (
                <tr key={c}><td>{tOptional(`exposure.road.${c}`) ?? c}</td><td className="num">{formatDecimal(km, lang, 2)}</td></tr>
              ))}
            </tbody>
          </table>
          </details>
          </>
        ) : <p className="muted">0 km</p>
      ) : <p className="muted">{m.roads_km_intersecting.coverage === 'unavailable' ? t('exposure.unavailable') : t('exposure.noOsmData')}</p>}

      <h3>{t('exposure.details.proximity')}</h3>
      {[m.buildings_within_buffer, m.roads_km_within_buffer, m.health_within_buffer, m.education_within_buffer].every((x) => x.value !== null)
        ? <p className="small" data-testid="proximity">{t('exposure.proximity.text', {
          buffer, buildings: formatNumber(m.buildings_within_buffer.value ?? 0, lang),
          roads: formatDecimal(m.roads_km_within_buffer.value ?? 0, lang, 1),
          health: formatNumber(m.health_within_buffer.value ?? 0, lang),
          education: formatNumber(m.education_within_buffer.value ?? 0, lang) })}</p>
        : <p className="muted">{t('exposure.unavailable')}</p>}
      </details>
    </>
  );
}

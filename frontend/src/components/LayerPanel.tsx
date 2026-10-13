import { useState } from 'react';
import { useI18n } from '../i18n/LanguageContext';
import { layerDescription, layerLabel, splitLayers } from '../services/layers';
import { LAYER_COLORS } from '../services/exposure';
import type { ExposureLayerName, LayerInfo, Legend } from '../types/api';

export interface ExposureLayerEntry { name: ExposureLayerName; total: number; shown: number }

interface Props {
  layers: LayerInfo[];
  visible: Record<string, boolean>;
  opacity: Record<string, number>;
  onToggle: (id: string) => void;
  onOpacity: (id: string, value: number) => void;
  /** Exposure & Impact layers (present after an exposure analysis). */
  exposureLayers?: ExposureLayerEntry[];
  exposureVisible?: Record<ExposureLayerName, boolean>;
  onExposureToggle?: (name: ExposureLayerName) => void;
}

function LegendBar({ legend }: { legend: Legend | null }) {
  if (!legend || legend.type === 'rgb') return null;
  if (legend.type === 'solid') {
    return <span className="legend-swatch" style={{ background: legend.colors[0] }} />;
  }
  return (
    <span className="legend-gradient" title={`${legend.min} → ${legend.max}`}
          style={{ background: `linear-gradient(90deg, ${legend.colors.join(',')})` }} />
  );
}

export default function LayerPanel({ layers, visible, opacity, onToggle, onOpacity,
  exposureLayers = [], exposureVisible, onExposureToggle }: Props) {
  const { lang, t } = useI18n();
  // Collapsed by default on phones so the map stays visible.
  const [open, setOpen] = useState(() => typeof window === 'undefined' || window.innerWidth > 820);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const { main, advanced } = splitLayers(layers);

  const renderRow = (l: LayerInfo) => {
    const name = layerLabel(lang, l);
    return (
      <div key={l.id} className="layer-row" title={layerDescription(lang, l)}>
        <label className="layer-check">
          <input type="checkbox" checked={!!visible[l.id]} onChange={() => onToggle(l.id)} />
          <span className="layer-name">{name}</span>
          <LegendBar legend={l.legend} />
        </label>
        {visible[l.id] && (
          <input type="range" min={0.1} max={1} step={0.05} value={opacity[l.id] ?? 0.8}
                 aria-label={t('layers.opacity', { name })}
                 onChange={(e) => onOpacity(l.id, Number(e.target.value))} />
        )}
      </div>
    );
  };

  return (
    <div className={`layer-panel${open ? "" : " collapsed"}`}>
      <button className="layer-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{t('layers.title')}</span><span aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      {open && exposureLayers.length > 0 && (
        <div className="layer-group" data-testid="exposure-layers">
          <div className="layer-group-title">{t('exposure.layers.title')}</div>
          {exposureLayers.map((e) => (
            <div key={e.name} className="layer-row"
                 title={e.shown < e.total ? t('exposure.layer.truncated', { shown: e.shown, total: e.total }) : undefined}>
              <label className="layer-check">
                <input type="checkbox" checked={exposureVisible?.[e.name] ?? true}
                       onChange={() => onExposureToggle?.(e.name)} />
                <span className="layer-name">{t(`exposure.layer.${e.name}` as 'exposure.layer.roads')}</span>
                <span className="legend-swatch" style={{ background: LAYER_COLORS[e.name] }} aria-hidden />
              </label>
              {e.shown < e.total && (
                <small className="muted">{t('exposure.layer.truncated', { shown: e.shown, total: e.total })}</small>
              )}
            </div>
          ))}
        </div>
      )}
      {open && (layers.length === 0
        ? (exposureLayers.length === 0 ? <p className="muted small">{t('layers.empty')}</p> : null)
        : (
          <>
            <div className="layer-group">
              <div className="layer-group-title">{t('layers.group.main')}</div>
              {main.map(renderRow)}
            </div>
            {advanced.length > 0 && (
              <div className="layer-group">
                <button className="layer-group-toggle" onClick={() => setAdvancedOpen(!advancedOpen)}
                        aria-expanded={advancedOpen}>
                  <span>{`${t('layers.group.advanced')} (${advanced.length})`}</span>
                  <span aria-hidden>{advancedOpen ? '▾' : '▸'}</span>
                </button>
                {advancedOpen && advanced.map(renderRow)}
              </div>
            )}
          </>
        ))}
    </div>
  );
}

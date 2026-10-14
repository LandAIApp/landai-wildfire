import { useI18n } from '../i18n/LanguageContext';
import { formatArea, formatKm2, formatNumber } from '../services/format';
import type { AreaLevel } from '../services/geometry';

interface Props {
  hectares: number | null;
  level: AreaLevel;
  maxHectares: number;
  drawing: boolean;
  isPolygon: boolean;
  draftCount: number;
  hasRing: boolean;
  onFinish: () => void;
  onUndo: () => void;
  onClear: () => void;
}

/** Floating live-area readout + drawing buttons on the map (essential on phones, where the map is far from the form). */
export default function DrawBar(p: Props) {
  const { lang, t } = useI18n();
  if (!p.drawing && !p.hasRing) return null;
  return (
    <div className={`draw-bar ${p.level}`} role="toolbar" aria-label={t('area.title')}>
      <span className="draw-bar-area">
        <strong>{p.hectares ? formatArea(p.hectares, lang) : '—'}</strong>
        <small>{p.hectares ? `· ${formatKm2(p.hectares, lang)} ` : ''}/ {formatNumber(p.maxHectares, lang)} ha</small>
      </span>
      {p.drawing && p.isPolygon && (
        <>
          <button type="button" disabled={p.draftCount < 3} onClick={p.onFinish}>{t('draw.finish')}</button>
          <button type="button" disabled={p.draftCount < 1} onClick={p.onUndo}>{t('draw.undo')}</button>
        </>
      )}
      <button type="button" onClick={p.onClear}>{t('draw.clear')}</button>
    </div>
  );
}

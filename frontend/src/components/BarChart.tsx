export interface BarRow {
  key: string;
  label: string;
  /** Main value (solid bar). */
  value: number;
  /** Optional larger reference value drawn as a lighter bar behind (e.g. "nearby" includes "inside"). */
  total?: number;
  text: string;
  highlight?: boolean;
}

interface Props {
  rows: BarRow[];
  /** Accessible description of the chart. */
  title: string;
  legend?: { main: string; total?: string };
  testId?: string;
}

/**
 * Dependency-free horizontal bar chart (plain divs): light enough for a map dashboard and readable by screen readers
 * because every bar carries its value as text. Bars are scaled to the largest value shown.
 */
export default function BarChart({ rows, title, legend, testId }: Props) {
  const max = Math.max(0, ...rows.map((r) => Math.max(r.value, r.total ?? 0)));
  const pct = (v: number) => (max > 0 ? Math.max(v > 0 ? 2 : 0, (v / max) * 100) : 0);
  return (
    <div className="bars" role="group" aria-label={title} data-testid={testId}>
      {legend && (
        <div className="bars-legend" aria-hidden>
          <span><i className="swatch main" />{legend.main}</span>
          {legend.total && <span><i className="swatch total" />{legend.total}</span>}
        </div>
      )}
      {rows.map((r) => (
        <div key={r.key} className={`bar-row${r.highlight ? ' selected' : ''}`}>
          <span className="bar-label">{r.label}</span>
          <span className="bar-track" aria-hidden>
            {r.total !== undefined && <span className="bar total" style={{ width: `${pct(r.total)}%` }} />}
            <span className="bar main" style={{ width: `${pct(r.value)}%` }} />
          </span>
          <span className="bar-value">{r.text}</span>
        </div>
      ))}
    </div>
  );
}

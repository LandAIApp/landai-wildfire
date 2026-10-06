export interface Issue { code: string; message: string }
export interface DateRange { start: string | null; end: string | null }
export interface DateWindows { pre: DateRange; post: DateRange; history: DateRange }

export interface WildfireRequest {
  department: string;
  municipality: string;
  fire_date: string;
  analysis_end: string;
}

export interface PreflightResponse {
  status: 'ok' | 'blocked';
  valid: boolean;
  pre_count: number | null;
  post_count: number | null;
  history_count: number | null;
  date_windows: DateWindows | null;
  aoi_hectares: number | null;
  warnings: Issue[];
  blocking_errors: Issue[];
}

export interface AreaEntry { threshold: number; key: string; label: string; hectares: number }

export interface Legend {
  type: 'gradient' | 'solid' | 'rgb';
  min: number | null;
  max: number | null;
  colors: string[];
}

export interface LayerInfo {
  id: string;
  label: string;
  group: string;
  description: string;
  tile_url: string;
  visible_by_default: boolean;
  legend: Legend | null;
}

export interface AnalyzeResponse {
  status: 'ok';
  metadata: {
    model_version: string;
    equivalence_validated: boolean;
    department: string;
    municipality: string;
    fire_date: string;
    analysis_end: string;
    aoi_hectares: number | null;
    generated_at: string;
    disclaimer: string;
  };
  image_counts: { pre: number; post: number; history: number };
  date_windows: DateWindows;
  training: { positive_samples: number; negative_samples: number; note: string };
  area_statistics: Record<string, number>;
  area_hectares: AreaEntry[];
  layers: LayerInfo[];
  boundary: GeoJSON.Feature;
  bounds: [[number, number], [number, number]];
  warnings: Issue[];
}

export interface ApiErrorBody {
  status: 'error';
  code: string;
  message: string;
  details?: unknown;
}

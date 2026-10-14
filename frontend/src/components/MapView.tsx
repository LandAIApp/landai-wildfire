import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { Language } from '../i18n';
import { useI18n } from '../i18n/LanguageContext';
import { LAYER_COLORS } from '../services/exposure';
import { formatNumber } from '../services/format';
import type { AreaLevel } from '../services/geometry';
import type {
  ExposureLayerName, ExposureResponse, LayerInfo, LngLat, Ring,
} from '../types/api';

export type DrawTool = 'polygon' | 'rectangle';
type Bounds = [[number, number], [number, number]];

interface Props {
  layers: LayerInfo[];
  visible: Record<string, boolean>;
  opacity: Record<string, number>;
  boundary: GeoJSON.Feature | null;
  bounds: Bounds | null;
  // --- custom study area (draw mode) ---
  drawTool?: DrawTool | null;          // active drawing tool (null = not drawing)
  draft?: LngLat[];                    // vertices placed so far
  ring?: Ring | null;                  // finished drawn ring (closed)
  level?: AreaLevel;
  limitChip?: string;
  onPoint?: (p: LngLat) => void;
  onFinish?: () => void;
  onRingChange?: (ring: Ring) => void;
  // --- Exposure & Impact layers ---
  exposure?: ExposureResponse['layers'] | null;
  exposureVisible?: Record<ExposureLayerName, boolean>;
  /** Request to zoom to an exposed feature (by OSM id) or to a whole layer; `seq` makes repeated clicks fire again. */
  focus?: ExposureFocus | null;
}

export interface ExposureFocus { osm?: string; layer?: ExposureLayerName; seq: number }

const COLORS: Record<AreaLevel, string> = {
  none: '#22d8b4', ok: '#22d8b4', warn: '#f5c451', over: '#ff7b7b', small: '#ff7b7b',
};
const toLatLng = (p: LngLat): L.LatLngTuple => [p[1], p[0]];
const toLngLat = (ll: L.LatLng): LngLat => [ll.lng, ll.lat];
const EXPOSURE_ORDER: ExposureLayerName[] = ['aoi', 'buffer', 'footprint', 'roads', 'buildings', 'health', 'education'];

export default function MapView(props: Props) {
  const { layers, visible, opacity, boundary, bounds } = props;
  const { lang, tOptional } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tileRefs = useRef<Record<string, L.TileLayer>>({});
  const boundaryRef = useRef<L.GeoJSON | null>(null);
  const aoiGroup = useRef<L.LayerGroup | null>(null);
  const exposureRefs = useRef<Partial<Record<ExposureLayerName, L.FeatureGroup>>>({});
  const markerByOsm = useRef<Map<string, L.CircleMarker>>(new Map());
  const handlers = useRef(props);
  handlers.current = props;
  const hasResult = layers.length > 0 || !!boundary;
  const drawTool = props.drawTool ?? null;
  const draft = props.draft ?? [];
  const level = props.level ?? 'none';

  // Create the map once. Canvas rendering keeps thousands of OSM features responsive.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, doubleClickZoom: true, preferCanvas: true })
      .setView([4.6, -74.1], 6);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    map.createPane('exposure').style.zIndex = '450';
    aoiGroup.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Rebuild EE tile layers when a new analysis arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    Object.values(tileRefs.current).forEach((tile) => map.removeLayer(tile));
    tileRefs.current = {};
    layers.forEach((l, i) => {
      tileRefs.current[l.id] = L.tileLayer(l.tile_url, { zIndex: 300 + i, maxZoom: 19, opacity: 0.8 });
    });
  }, [layers]);

  // Result boundary and viewport.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    boundaryRef.current?.remove();
    boundaryRef.current = null;
    if (boundary) {
      boundaryRef.current = L.geoJSON(boundary, {
        style: { color: '#ffffff', weight: 3, fill: false, opacity: 1 },
        interactive: false,
      }).addTo(map);
      boundaryRef.current.bringToFront();
    }
    if (bounds) map.fitBounds(bounds, { padding: [30, 30] });
  }, [boundary, bounds]);

  // Visibility and opacity.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    Object.entries(tileRefs.current).forEach(([id, tile]) => {
      tile.setOpacity(opacity[id] ?? 0.8);
      const on = !!visible[id];
      if (on && !map.hasLayer(tile)) tile.addTo(map);
      if (!on && map.hasLayer(tile)) map.removeLayer(tile);
    });
  }, [layers, visible, opacity]);

  // Clicks while a drawing tool is active.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const el = map.getContainer();
    if (!drawTool) { el.style.cursor = ''; return; }
    el.style.cursor = 'crosshair';
    map.doubleClickZoom.disable();
    const onClick = (e: L.LeafletMouseEvent) => handlers.current.onPoint?.(toLngLat(e.latlng));
    const onDbl = () => { if (handlers.current.drawTool === 'polygon') handlers.current.onFinish?.(); };
    map.on('click', onClick);
    map.on('dblclick', onDbl);
    return () => {
      map.off('click', onClick);
      map.off('dblclick', onDbl);
      map.doubleClickZoom.enable();
      el.style.cursor = '';
    };
  }, [drawTool]);

  // Draw the study area: draft vertices and the finished ring (draggable vertices).
  useEffect(() => {
    const map = mapRef.current;
    const group = aoiGroup.current;
    if (!map || !group) return;
    group.clearLayers();
    if (hasResult) return;
    const color = COLORS[level];

    if (drawTool && draft.length > 0) {
      const pts = draft.map(toLatLng);
      L.polyline(pts, { color, weight: 3, dashArray: '6 6' }).addTo(group);
      pts.forEach((pt, i) => {
        const marker = L.circleMarker(pt, {
          radius: i === 0 ? 7 : 5, color: '#071110', weight: 2, fillColor: color, fillOpacity: 1,
        }).addTo(group);
        if (i === 0 && drawTool === 'polygon' && draft.length >= 3) {
          marker.on('click', (ev) => { L.DomEvent.stopPropagation(ev); handlers.current.onFinish?.(); });
        }
      });
      const rubber = L.polyline([], { color, weight: 2, dashArray: '2 8', opacity: 0.8 }).addTo(group);
      const rect = L.rectangle([pts[0], pts[0]], { color, weight: 3, fillOpacity: 0.1 });
      const onMove = (e: L.LeafletMouseEvent) => {
        if (handlers.current.drawTool === 'rectangle') {
          if (!group.hasLayer(rect)) rect.addTo(group);
          rect.setBounds(L.latLngBounds(pts[0], e.latlng));
        } else {
          rubber.setLatLngs([pts[pts.length - 1], e.latlng]);
        }
      };
      map.on('mousemove', onMove);
      return () => { map.off('mousemove', onMove); };
    }

    if (!drawTool && props.ring && props.ring.length >= 4) {
      const open = props.ring.slice(0, -1);
      const polygon = L.polygon(open.map(toLatLng), {
        color, weight: 3, fillColor: color, fillOpacity: 0.15,
      }).addTo(group);
      const current: L.LatLng[] = open.map((p) => L.latLng(p[1], p[0]));
      open.forEach((p, i) => {
        const marker = L.marker(toLatLng(p), {
          draggable: true, keyboard: false,
          icon: L.divIcon({ className: 'vertex-handle', iconSize: [14, 14] }),
        }).addTo(group);
        marker.on('drag', () => {
          current[i] = marker.getLatLng();
          polygon.setLatLngs(current);
        });
        marker.on('dragend', () => {
          const next = current.map(toLngLat);
          handlers.current.onRingChange?.([...next, next[0]]);
        });
      });
    }
    return undefined;
  }, [draft, props.ring, drawTool, level, hasResult]);

  // Exposure layers: rebuilt when a new exposure result arrives (canvas, click-to-inspect).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    Object.values(exposureRefs.current).forEach((l) => l?.remove());
    exposureRefs.current = {};
    markerByOsm.current = new Map();
    const data = props.exposure;
    if (!data) return;
    for (const name of EXPOSURE_ORDER) {
      const fc = data[name];
      if (!fc || !fc.features.length) continue;
      const color = LAYER_COLORS[name];
      const layer = L.geoJSON(fc, {
        pane: 'exposure',
        style: () => name === 'roads'
          ? { color, weight: 3, opacity: 0.95 }
          : name === 'aoi' ? { color, weight: 2, fill: false, opacity: 0.9 }
          : name === 'buffer' ? { color, weight: 1.5, dashArray: '5 5', fillColor: color, fillOpacity: 0.05 }
          : name === 'footprint' ? { color, weight: 1.5, fillColor: color, fillOpacity: 0.35 }
          : { color, weight: 1, fillColor: color, fillOpacity: 0.7 },
        pointToLayer: (f, latlng) => {
          const marker = L.circleMarker(latlng, {
            pane: 'exposure', radius: 6, color: '#071110', weight: 1.5, fillColor: color, fillOpacity: 1,
          });
          const osm = (f.properties as Record<string, unknown> | null)?.osm;
          if (typeof osm === 'string') markerByOsm.current.set(osm, marker);
          return marker;
        },
        interactive: name !== 'aoi' && name !== 'buffer',
        onEachFeature: (feature, l) => {
          if (name === 'aoi' || name === 'buffer') return;
          l.bindPopup(() => popupFor(name, feature, lang, tOptional), { maxWidth: 280 });
        },
      });
      // Buildings and facilities can be a few metres wide: add a fixed-size marker at the centre so they stay visible.
      if (name === 'buildings' || name === 'health' || name === 'education') {
        const group = L.featureGroup([layer]);
        layer.eachLayer((child) => {
          const poly = child as L.Polygon & { feature?: GeoJSON.Feature };
          if (!poly.getBounds || !poly.feature) return;
          const marker = L.circleMarker(poly.getBounds().getCenter(), {
            pane: 'exposure', radius: name === 'buildings' ? 5 : 8, color: '#071110', weight: 1.5,
            fillColor: color, fillOpacity: 1,
          });
          marker.bindPopup(() => popupFor(name, poly.feature as GeoJSON.Feature, lang, tOptional), { maxWidth: 280 });
          const osm = (poly.feature.properties as Record<string, unknown> | null)?.osm;
          if (typeof osm === 'string') markerByOsm.current.set(osm, marker);
          group.addLayer(marker);
        });
        exposureRefs.current[name] = group;
      } else {
        exposureRefs.current[name] = layer;
      }
    }
    const footprint = exposureRefs.current.footprint ?? exposureRefs.current.aoi;
    if (footprint) map.fitBounds(footprint.getBounds(), { padding: [40, 40], maxZoom: 15 });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.exposure, lang]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const name of EXPOSURE_ORDER) {
      const layer = exposureRefs.current[name];
      if (!layer) continue;
      const on = props.exposureVisible?.[name] ?? true;
      if (on && !map.hasLayer(layer)) layer.addTo(map);
      if (!on && map.hasLayer(layer)) map.removeLayer(layer);
    }
  }, [props.exposure, props.exposureVisible, lang]);

  // Zoom to a feature (or a whole layer) when the user clicks it in the exposure panel.
  useEffect(() => {
    const map = mapRef.current;
    const f = props.focus;
    if (!map || !f) return;
    if (f.osm) {
      const marker = markerByOsm.current.get(f.osm);
      if (!marker) return;
      const group = Object.values(exposureRefs.current).find((g) => g?.hasLayer(marker));
      if (group && !map.hasLayer(group)) group.addTo(map);
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 17));
      marker.openPopup();
    } else if (f.layer) {
      const group = exposureRefs.current[f.layer];
      if (!group) return;
      if (!map.hasLayer(group)) group.addTo(map);
      map.fitBounds(group.getBounds(), { padding: [60, 60], maxZoom: 18 });
    }
  }, [props.focus]);

  return (
    <>
      <div ref={containerRef} className="map" data-testid="map" />
      {!hasResult && props.limitChip && <div className="map-chip">{props.limitChip}</div>}
    </>
  );
}

/** Popup content built with DOM text nodes: OpenStreetMap tags are untrusted and never injected as HTML. */
export function popupFor(
  name: ExposureLayerName, feature: GeoJSON.Feature, lang: Language,
  tr: (key: string, params?: Record<string, string | number>) => string | undefined,
): HTMLElement {
  const p = (feature.properties ?? {}) as Record<string, unknown>;
  const label = (key: string, fallback = '') => tr(key) ?? fallback;
  const root = document.createElement('div');
  root.className = 'popup';
  const title = document.createElement('strong');
  title.textContent = label(`exposure.layer.${name}`, name);
  root.appendChild(title);
  const row = (name2: string, value: unknown) => {
    if (value === undefined || value === null || value === '') return;
    const div = document.createElement('div');
    div.textContent = `${name2}: ${typeof value === 'number' ? formatNumber(value, lang) : String(value)}`;
    root.appendChild(div);
  };
  if (name === 'health' || name === 'education') {
    row(label('exposure.col.name'), p.name ?? label('exposure.popup.noName'));
    row(label('exposure.popup.class'), p.class);
    row(label('exposure.popup.distance'), typeof p.distance_m === 'number' ? `${formatNumber(p.distance_m, lang)} m` : undefined);
  } else if (name === 'buildings') {
    row(label('exposure.popup.category'), p.category ? label(`exposure.building.${String(p.category)}`, String(p.category)) : undefined);
    row('building', p.building);
    row(label('exposure.col.name'), p.name);
  } else if (name === 'roads') {
    row(label('exposure.popup.class'), p.class ? label(`exposure.road.${String(p.class)}`, String(p.class)) : undefined);
  } else if (name === 'footprint') {
    row(label('exposure.popup.area'), typeof p.area_ha === 'number' ? `${formatNumber(p.area_ha, lang)} ha` : undefined);
  }
  if (p.osm) row(label('exposure.popup.osm'), p.osm);
  return root;
}

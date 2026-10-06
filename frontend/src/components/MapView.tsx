import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { LayerInfo } from '../types/api';

interface Props {
  layers: LayerInfo[];
  visible: Record<string, boolean>;
  opacity: Record<string, number>;
  boundary: GeoJSON.Feature | null;
  bounds: [[number, number], [number, number]] | null;
}

export default function MapView({ layers, visible, opacity, boundary, bounds }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tileRefs = useRef<Record<string, L.TileLayer>>({});
  const boundaryRef = useRef<L.GeoJSON | null>(null);

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true }).setView([4.6, -74.1], 6);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Rebuild EE tile layers when a new analysis arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    Object.values(tileRefs.current).forEach((t) => map.removeLayer(t));
    tileRefs.current = {};
    layers.forEach((l, i) => {
      tileRefs.current[l.id] = L.tileLayer(l.tile_url, { zIndex: 300 + i, maxZoom: 19, opacity: 0.8 });
    });
  }, [layers]);

  // Municipal boundary and viewport.
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

  return <div ref={containerRef} className="map" />;
}

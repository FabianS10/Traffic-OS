import { useEffect, useRef, useState, useCallback } from "react";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

const NEON = {
  1: "#4ECDC4", 2: "#F7DC6F", 3: "#F0A500", 4: "#FF6B6B",
  bg: "#1A2639", route: "#00F3FF",
};

function flattenCoords(geometry) {
  if (!geometry?.coordinates) return [];
  const { type, coordinates } = geometry;
  if (type === "LineString")      return coordinates;
  if (type === "MultiLineString") return coordinates.flat(1);
  if (type === "GeometryCollection") {
    return (geometry.geometries || []).flatMap(g => flattenCoords(g));
  }
  return [];
}

function cityDistance(a, b) {
  return Math.sqrt((a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2);
}

// Detect city from coordinates
function detectCity(lat) {
  return lat > 10 ? "san_francisco" : "fusagasuga";
}

export default function MapView({
  center, segments, selected, onSelect, onMapClick, API, alternatePath, congestionColor
}) {
  const mapRef        = useRef(null);
  const mapObj        = useRef(null);
  const [loaded, setLoaded] = useState(false);
  const onSelectRef   = useRef(onSelect);
  const prevCenterRef = useRef(center);
  const tileQueueRef  = useRef(new Set()); // track in-flight tiles

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);

  const finalAPI = (API && !API.includes("undefined")) ? API : "http://localhost:8000/api";

  // ── Expose city to window for tile loader ────────────────────────────────
  useEffect(() => {
    window.__trafficos_city__ = detectCity(center.lat);
  }, [center]);

  // ── Tile loader — streams road chunks like open world game ───────────────
  const loadTile = useCallback((lat, lng, map) => {
    const city = detectCity(lat);
    const tileKey = `${city}:${lat.toFixed(3)}:${lng.toFixed(3)}`;

    // Skip if tile already loading or loaded
    if (tileQueueRef.current.has(tileKey)) return;
    tileQueueRef.current.add(tileKey);

    fetch(`${finalAPI}/ingest/trigger/ingest-osm?city=${city}&lat=${lat}&lng=${lng}`, {
      method: "POST"
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.segments_inserted > 0) {
          // New roads loaded — refresh map data
          fetch(`${finalAPI}/traffic/map-data`)
            .then(r => r.json())
            .then(geoData => {
              if (!map || !map.getSource("fusa-roads")) return;
              geoData.features = (geoData.features || []).map((f, i) => ({
                ...f,
                id: typeof f.id === "number" ? f.id : i + 1,
              }));
              map.getSource("fusa-roads").setData(geoData);
            });
        }
      })
      .catch(() => {
        // Remove from queue on failure so it can retry
        tileQueueRef.current.delete(tileKey);
      });
  }, [finalAPI]);

  // ── Map initialisation ───────────────────────────────────────────────────
  const initMap = useCallback((initialCenter) => {
    if (!mapRef.current || !window.mapboxgl) return;

    if (mapObj.current) {
      mapObj.current.remove();
      mapObj.current = null;
    }
    setLoaded(false);
    tileQueueRef.current.clear();

    window.mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new window.mapboxgl.Map({
      container:          mapRef.current,
      style:              "mapbox://styles/mapbox/dark-v11",
      center:             [initialCenter.lng, initialCenter.lat],
      zoom:               14.8,
      pitch:              45,
      bearing:            -10,
      attributionControl: false,
    });

    mapObj.current = map;

    map.on("load", async () => {
      try {
        const res     = await fetch(`${finalAPI}/traffic/map-data`);
        const geoData = res.ok ? await res.json() : { type: "FeatureCollection", features: [] };

        geoData.features = (geoData.features || []).map((f, i) => ({
          ...f,
          id: typeof f.id === "number" ? f.id : i + 1,
        }));

        map.addSource("fusa-roads",   { type: "geojson", data: geoData });
        map.addSource("segment-dots", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addSource("route-path",   { type: "geojson", data: { type: "FeatureCollection", features: [] } });

        map.addLayer({
          id: "roads-glow", type: "line", source: "fusa-roads",
          paint: {
            "line-width":   ["interpolate", ["linear"], ["zoom"], 12, 4, 16, 10],
            "line-blur":    8,
            "line-opacity": 0.45,
            "line-color":   ["case",
              ["==", ["feature-state", "congestion"], null], "transparent",
              ["match", ["feature-state", "congestion"],
                1, NEON[1], 2, NEON[2], 3, NEON[3], 4, NEON[4], "transparent"]
            ],
          },
        });

        map.addLayer({
          id: "roads-line", type: "line", source: "fusa-roads",
          layout: { "line-join": "round", "line-cap": "round" },
          paint: {
            "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4],
            "line-color": ["case",
              ["==", ["feature-state", "congestion"], null], NEON.bg,
              ["match", ["feature-state", "congestion"],
                1, NEON[1], 2, NEON[2], 3, NEON[3], 4, NEON[4], NEON.bg]
            ],
          },
        });

        map.addLayer({
          id: "segment-dots", type: "circle", source: "segment-dots",
          paint: {
            "circle-radius":       ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 7],
            "circle-color":        ["get", "color"],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#080E1A",
          },
        });

        map.addLayer({
          id: "roads-selected", type: "line", source: "fusa-roads",
          paint: { "line-width": 6, "line-color": "#FFFFFF", "line-opacity": 0.4, "line-blur": 2 },
          filter: ["==", [" id"], -1],
        });

        map.addLayer({
          id: "route-glow", type: "line", source: "route-path",
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-width": 14, "line-color": NEON.route, "line-blur": 12, "line-opacity": 0.35 },
        });

        map.addLayer({
          id: "route-line", type: "line", source: "route-path",
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-width": 3.5, "line-color": NEON.route, "line-opacity": 1 },
        });

        // ── Click handlers ──────────────────────────────────────────────────
        map.on("click", "segment-dots", (e) => {
          if (e.features.length > 0) {
            onSelectRef.current(e.features[0].properties.id);
            e.preventDefault();
          }
        });

        map.on("click", "roads-line", (e) => {
          if (e.features.length > 0) {
            onSelectRef.current(e.features[0].id);
            e.preventDefault();
          }
        });

        map.on("click", (e) => {
          const hits = map.queryRenderedFeatures(e.point, { layers: ["roads-line", "segment-dots"] });
          if (hits.length === 0) onMapClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });

          // 🎮 Open world tile streaming — load chunk around click point
          loadTile(e.lngLat.lat, e.lngLat.lng, map);
        });

        // ── Also stream tiles as map moves (pan/drag) ───────────────────────
        let moveTimeout = null;
        map.on("moveend", () => {
          clearTimeout(moveTimeout);
          moveTimeout = setTimeout(() => {
            const c = map.getCenter();
            loadTile(c.lat, c.lng, map);
          }, 800); // debounce 800ms after pan stops
        });

        map.on("mouseenter", "roads-line",    () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "roads-line",    () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseenter", "segment-dots",  () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "segment-dots",  () => { map.getCanvas().style.cursor = ""; });

        setLoaded(true);

        // Load initial tile for the starting center
        loadTile(initialCenter.lat, initialCenter.lng, map);

      } catch (err) {
        console.warn("MapView load error:", err);
        setLoaded(true);
      }
    });
  }, [finalAPI, loadTile]);

  // Initial map load
  useEffect(() => {
    initMap(center);
    return () => {
      if (mapObj.current) { mapObj.current.remove(); mapObj.current = null; }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // City switch: reinitialise map when center jumps far
  useEffect(() => {
    const dist = cityDistance(center, prevCenterRef.current);
    prevCenterRef.current = center;
    if (dist > 0.5 && mapObj.current) {
      initMap(center);
    }
  }, [center, initMap]);

  // ── Sync congestion state + dots ──────────────────────────────────────────
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getSource("fusa-roads")) return;

    segments.forEach(seg => {
      map.setFeatureState(
        { source: "fusa-roads", id: seg.segment_id },
        { congestion: seg.congestion_level }
      );
    });

    const dots = segments
      .filter(s => s.center_lng != null && s.center_lat != null)
      .map(s => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.center_lng, s.center_lat] },
        properties: { id: s.segment_id, color: NEON[s.congestion_level] || NEON[1] },
      }));

    map.getSource("segment-dots")?.setData({ type: "FeatureCollection", features: dots });
  }, [segments, loaded]);

  // ── Render A* route + camera fit ─────────────────────────────────────────
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getSource("route-path")) return;

    const geojson = alternatePath || { type: "FeatureCollection", features: [] };
    map.getSource("route-path").setData(geojson);

    if (!alternatePath || alternatePath.features.length === 0) {
      map.flyTo({ center: [center.lng, center.lat], zoom: 14.8, pitch: 45, bearing: -10, duration: 1000 });
      return;
    }

    const bounds = new window.mapboxgl.LngLatBounds();
    let coordCount = 0;

    alternatePath.features.forEach(feature => {
      flattenCoords(feature.geometry).forEach(coord => {
        if (Array.isArray(coord) && coord.length >= 2 && isFinite(coord[0]) && isFinite(coord[1])) {
          bounds.extend([coord[0], coord[1]]);
          coordCount++;
        }
      });
    });

    if (coordCount > 0) {
      map.fitBounds(bounds, {
        padding: { top: 80, bottom: 120, left: 60, right: 320 },
        duration: 1400,
        pitch: 45,
        bearing: -10,
        maxZoom: 16,
      });
    }
  }, [alternatePath, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Selected segment highlight ────────────────────────────────────────────
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getLayer("roads-selected")) return;
    map.setFilter("roads-selected", ["==", [" id"], selected ?? -1]);
  }, [selected, loaded]);

  // ── Pan to new center (small movements within a city) ────────────────────
  useEffect(() => {
    if (!mapObj.current || !loaded) return;
    const dist = cityDistance(center, prevCenterRef.current);
    if (dist <= 0.5) {
      mapObj.current.easeTo({ center: [center.lng, center.lat], duration: 700 });
    }
  }, [center, loaded]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {!loaded && (
        <div style={overlay}>
          SYNCING NEURAL MAP...
        </div>
      )}
      <div ref={mapRef} style={{ width: "100%", height: "100%" }} />

      <div style={legend}>
        <div style={legendTitle}>CONGESTION</div>
        {[["FREE FLOW", 1], ["LIGHT", 1], ["MODERATE", 2], ["HEAVY", 3], ["JAM", 4]].map(([lbl, lvl]) => (
          <div key={lbl} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: NEON[lvl], boxShadow: `0 0 5px ${NEON[lvl]}60` }} />
            <span style={{ fontSize: 9, color: "rgba(78,205,196,0.6)", letterSpacing: "0.06em" }}>{lbl}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const overlay = {
  position: "absolute", inset: 0, zIndex: 100, display: "flex", alignItems: "center",
  justifyContent: "center", background: "#080E1A", color: "#4ECDC4",
  fontFamily: "'Space Mono',monospace", fontSize: 11,
};

const legend = {
  position: "absolute", top: 16, left: 16, background: "rgba(8,14,26,0.88)",
  border: "1px solid rgba(78,205,196,0.15)", borderRadius: 4, padding: "10px 12px",
  fontFamily: "'Space Mono',monospace", zIndex: 5,
};

const legendTitle = {
  fontSize: 9, color: "rgba(78,205,196,0.4)", letterSpacing: "0.12em", marginBottom: 8,
};
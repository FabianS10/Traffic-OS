import { useEffect, useRef, useState, useCallback } from "react";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

const COLORS = {
  traffic: {
    0: "#102846",
    1: "#173B63",
    2: "#204D78",
    3: "#324A68",
    4: "#543247",
    default: "#173B63",
  },
  dots: {
    0: "#315C7A",
    1: "#3E789B",
    2: "#8A783A",
    3: "#8A5D35",
    4: "#9A3E52",
    default: "#3E789B",
  },
  route: "#00F3FF",
  selected: "#9DEBFF",
  bg: "#102846",
};

function flattenCoords(geometry) {
  if (!geometry?.coordinates) return [];
  const { type, coordinates } = geometry;

  if (type === "LineString") return coordinates;
  if (type === "MultiLineString") return coordinates.flat(1);

  if (type === "GeometryCollection") {
    return (geometry.geometries || []).flatMap((g) => flattenCoords(g));
  }

  return [];
}

function centerOfCoords(coords) {
  if (!coords?.length) return null;

  const mid = coords[Math.floor(coords.length / 2)];

  if (!Array.isArray(mid) || mid.length < 2) return null;

  return {
    lng: Number(mid[0]),
    lat: Number(mid[1]),
  };
}

function cityDistance(a, b) {
  return Math.sqrt((a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2);
}

function detectCity(lat) {
  return lat > 10 ? "san_francisco" : "fusagasuga";
}

function normalizeTrafficGeoJSON(data) {
  const features = (data?.features || []).map((f, i) => {
    const id = Number(f?.properties?.id ?? f?.id ?? i + 1);
    const level = Number(f?.properties?.congestion_level ?? 1);

    return {
      ...f,
      id,
      properties: {
        ...(f.properties || {}),
        id,
        segment_id: Number(f?.properties?.segment_id ?? id),
        congestion_level: level,
      },
    };
  });

  return {
    type: "FeatureCollection",
    features,
  };
}

function buildDotsFromGeoJSON(geojson) {
  return {
    type: "FeatureCollection",
    features: (geojson.features || [])
      .map((feature) => {
        const coords = flattenCoords(feature.geometry);
        const center = centerOfCoords(coords);

        if (!center) return null;

        const level = Number(feature.properties?.congestion_level ?? 1);
        const id = Number(feature.properties?.id ?? feature.id);

        return {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [center.lng, center.lat],
          },
          properties: {
            id,
            segment_id: id,
            congestion_level: level,
            color: COLORS.dots[level] || COLORS.dots.default,
          },
        };
      })
      .filter(Boolean),
  };
}

export default function MapView({
  center,
  segments,
  selected,
  onSelect,
  onMapClick,
  API,
  alternatePath,
}) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);

  const [loaded, setLoaded] = useState(false);

  const onSelectRef = useRef(onSelect);
  const prevCenterRef = useRef(center);
  const cityRef = useRef(detectCity(center.lat));

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const finalAPI =
    API && !API.includes("undefined")
      ? API.replace(/\/$/, "")
      : (import.meta?.env?.VITE_API_URL || "http://localhost:8000/api");

  const refreshTrafficData = useCallback(
    async (map, cityKey) => {
      if (!map?.getSource("fusa-roads")) return;

      try {
        const res = await fetch(
          `${finalAPI}/traffic/map-data?city=${encodeURIComponent(cityKey)}`
        );

        const raw = res.ok
          ? await res.json()
          : { type: "FeatureCollection", features: [] };

        const geoData = normalizeTrafficGeoJSON(raw);
        const dots = buildDotsFromGeoJSON(geoData);

        map.getSource("fusa-roads")?.setData(geoData);
        map.getSource("segment-dots")?.setData(dots);
      } catch (err) {
        console.warn("Traffic data refresh failed:", err);
      }
    },
    [finalAPI]
  );

  const initMap = useCallback(
    (initialCenter) => {
      if (!mapRef.current || !window.mapboxgl) return;

      if (mapObj.current) {
        mapObj.current.remove();
        mapObj.current = null;
      }

      setLoaded(false);

      window.mapboxgl.accessToken = MAPBOX_TOKEN;

      const map = new window.mapboxgl.Map({
        container: mapRef.current,
        style: "mapbox://styles/mapbox/dark-v11",
        center: [initialCenter.lng, initialCenter.lat],
        zoom: 14.8,
        pitch: 45,
        bearing: -10,
        attributionControl: false,
      });

      mapObj.current = map;

      map.on("load", async () => {
        try {
          map.addSource("fusa-roads", {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          });

          map.addSource("segment-dots", {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          });

          map.addSource("route-path", {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          });

          // Dark blue traffic network glow — not neon.
          map.addLayer({
            id: "roads-glow",
            type: "line",
            source: "fusa-roads",
            layout: {
              "line-join": "round",
              "line-cap": "round",
            },
            paint: {
              "line-width": ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 8],
              "line-blur": 4,
              "line-opacity": 0.22,
              "line-color": [
                "match",
                ["to-number", ["get", "congestion_level"]],
                0,
                COLORS.traffic[0],
                1,
                COLORS.traffic[1],
                2,
                COLORS.traffic[2],
                3,
                COLORS.traffic[3],
                4,
                COLORS.traffic[4],
                COLORS.traffic.default,
              ],
            },
          });

          // Main dark blue traffic network line.
          map.addLayer({
            id: "roads-line",
            type: "line",
            source: "fusa-roads",
            layout: {
              "line-join": "round",
              "line-cap": "round",
            },
            paint: {
              "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.4, 16, 3.8],
              "line-opacity": 0.88,
              "line-color": [
                "match",
                ["to-number", ["get", "congestion_level"]],
                0,
                COLORS.traffic[0],
                1,
                COLORS.traffic[1],
                2,
                COLORS.traffic[2],
                3,
                COLORS.traffic[3],
                4,
                COLORS.traffic[4],
                COLORS.traffic.default,
              ],
            },
          });

          map.addLayer({
            id: "roads-selected",
            type: "line",
            source: "fusa-roads",
            layout: {
              "line-join": "round",
              "line-cap": "round",
            },
            paint: {
              "line-width": 6,
              "line-color": COLORS.selected,
              "line-opacity": 0.62,
              "line-blur": 2,
            },
            filter: ["==", ["get", "id"], -1],
          });

          map.addLayer({
            id: "segment-dots",
            type: "circle",
            source: "segment-dots",
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 6],
              "circle-color": ["get", "color"],
              "circle-opacity": 0.95,
              "circle-stroke-width": 1.5,
              "circle-stroke-color": "#080E1A",
            },
          });

          // GPS route glow — neon reserved for mission route.
          map.addLayer({
            id: "route-glow",
            type: "line",
            source: "route-path",
            layout: {
              "line-join": "round",
              "line-cap": "round",
            },
            paint: {
              "line-width": 14,
              "line-color": COLORS.route,
              "line-blur": 12,
              "line-opacity": 0.35,
            },
          });

          map.addLayer({
            id: "route-line",
            type: "line",
            source: "route-path",
            layout: {
              "line-join": "round",
              "line-cap": "round",
            },
            paint: {
              "line-width": 3.8,
              "line-color": COLORS.route,
              "line-opacity": 1,
            },
          });

          map.on("click", "segment-dots", (e) => {
            if (e.features.length > 0) {
              const id = Number(e.features[0].properties?.id);
              onSelectRef.current(id);
              e.preventDefault();
            }
          });

          map.on("click", "roads-line", (e) => {
            if (e.features.length > 0) {
              const id = Number(e.features[0].properties?.id ?? e.features[0].id);
              onSelectRef.current(id);
              e.preventDefault();
            }
          });

          map.on("click", (e) => {
            const hits = map.queryRenderedFeatures(e.point, {
              layers: ["roads-line", "segment-dots"],
            });

            if (hits.length === 0) {
              onMapClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });
            }
          });

          map.on("mouseenter", "roads-line", () => {
            map.getCanvas().style.cursor = "pointer";
          });

          map.on("mouseleave", "roads-line", () => {
            map.getCanvas().style.cursor = "";
          });

          map.on("mouseenter", "segment-dots", () => {
            map.getCanvas().style.cursor = "pointer";
          });

          map.on("mouseleave", "segment-dots", () => {
            map.getCanvas().style.cursor = "";
          });

          setLoaded(true);

          const cityKey = detectCity(initialCenter.lat);
          cityRef.current = cityKey;
          await refreshTrafficData(map, cityKey);
        } catch (err) {
          console.warn("MapView load error:", err);
          setLoaded(true);
        }
      });
    },
    [finalAPI, onMapClick, refreshTrafficData]
  );

  useEffect(() => {
    initMap(center);

    return () => {
      if (mapObj.current) {
        mapObj.current.remove();
        mapObj.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // City switch: reinitialize if center jumps far.
  useEffect(() => {
    const dist = cityDistance(center, prevCenterRef.current);
    prevCenterRef.current = center;

    if (dist > 0.5 && mapObj.current) {
      initMap(center);
    }
  }, [center, initMap]);

  // Refresh TomTom data when city changes without full reload.
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getSource("fusa-roads")) return;

    const cityKey = detectCity(center.lat);

    if (cityKey !== cityRef.current) {
      cityRef.current = cityKey;
      refreshTrafficData(map, cityKey);
    }
  }, [center, loaded, refreshTrafficData]);

  // Render GPS route.
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getSource("route-path")) return;

    const geojson = alternatePath || {
      type: "FeatureCollection",
      features: [],
    };

    map.getSource("route-path").setData(geojson);

    if (!alternatePath || alternatePath.features.length === 0) {
      map.flyTo({
        center: [center.lng, center.lat],
        zoom: 14.8,
        pitch: 45,
        bearing: -10,
        duration: 1000,
      });
      return;
    }

    const bounds = new window.mapboxgl.LngLatBounds();
    let coordCount = 0;

    alternatePath.features.forEach((feature) => {
      flattenCoords(feature.geometry).forEach((coord) => {
        if (
          Array.isArray(coord) &&
          coord.length >= 2 &&
          isFinite(coord[0]) &&
          isFinite(coord[1])
        ) {
          bounds.extend([coord[0], coord[1]]);
          coordCount++;
        }
      });
    });

    if (coordCount > 0) {
      map.fitBounds(bounds, {
        padding: {
          top: 80,
          bottom: 120,
          left: 60,
          right: 320,
        },
        duration: 1400,
        pitch: 45,
        bearing: -10,
        maxZoom: 16,
      });
    }
  }, [alternatePath, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selected segment highlight.
  useEffect(() => {
    const map = mapObj.current;
    if (!loaded || !map?.getLayer("roads-selected")) return;

    map.setFilter("roads-selected", ["==", ["get", "id"], selected ?? -1]);
  }, [selected, loaded]);

  // Pan to center for small movements.
  useEffect(() => {
    if (!mapObj.current || !loaded) return;

    const dist = cityDistance(center, prevCenterRef.current);

    if (dist <= 0.5) {
      mapObj.current.easeTo({
        center: [center.lng, center.lat],
        duration: 700,
      });
    }
  }, [center, loaded]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {!loaded && <div style={overlay}>SYNCING NEURAL MAP...</div>}

      <div ref={mapRef} style={{ width: "100%", height: "100%" }} />

      <div style={legend}>
        <div style={legendTitle}>CONGESTION</div>
        {[
          ["FREE FLOW", 0],
          ["LIGHT", 1],
          ["MODERATE", 2],
          ["HEAVY", 3],
          ["JAM", 4],
        ].map(([lbl, lvl]) => (
          <div
            key={lbl}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 4,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: COLORS.dots[lvl],
                boxShadow: `0 0 5px ${COLORS.dots[lvl]}40`,
              }}
            />
            <span
              style={{
                fontSize: 9,
                color: "rgba(78,205,196,0.6)",
                letterSpacing: "0.06em",
              }}
            >
              {lbl}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const overlay = {
  position: "absolute",
  inset: 0,
  zIndex: 100,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#080E1A",
  color: "#4ECDC4",
  fontFamily: "'Space Mono',monospace",
  fontSize: 11,
};

const legend = {
  position: "absolute",
  top: 16,
  left: 16,
  background: "rgba(8,14,26,0.88)",
  border: "1px solid rgba(78,205,196,0.15)",
  borderRadius: 4,
  padding: "10px 12px",
  fontFamily: "'Space Mono',monospace",
  zIndex: 5,
};

const legendTitle = {
  fontSize: 9,
  color: "rgba(78,205,196,0.4)",
  letterSpacing: "0.12em",
  marginBottom: 8,
};
import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import TimeSlider from "../components/TimeSlider";
import AnalyticsPanel from "../components/AnalyticsPanel";
import SegmentDetail from "../components/SegmentDetail";
import MapView from "../components/MapView";
import Sidebar from "../components/Sidebar";
import ARIAPanel from "../components/ARIAPanel";
import { exportIntelReport } from "../components/PDFExport";

const CITY_PRESETS = {
  fusagasuga:    { name: "Fusagasugá",    lat: 4.3366,  lng: -74.3641 },
  san_francisco: { name: "San Francisco", lat: 37.7749, lng: -122.4194 },
};

export default function Dashboard() {
  const { user, token, logout, API: authAPI, demoMode } = useAuth();
  const API = authAPI?.includes("8000") ? authAPI : "http://localhost:8000/api";

  const [horizon, setHorizon]         = useState(0);
  const [segments, setSegments]       = useState([]);
  const [selected, setSelected]       = useState(null);
  const [loading, setLoading]         = useState(false);
  const [city, setCity]               = useState("fusagasuga");
  const [center, setCenter]           = useState(CITY_PRESETS.fusagasuga);
  const [weatherFactor, setWeather]   = useState(1.0);
  const [savedRoutes, setSavedRoutes] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [analyticsOpen, setAnalytics] = useState(false);
  const [cityMenuOpen, setCityMenu]   = useState(false);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [pdfLoading, setPdfLoading]   = useState(false);

  // ARIA state
  const [ariaMode,   setAriaMode]   = useState("idle");   // idle|segment|route|pulse
  const [ariaOpen,   setAriaOpen]   = useState(false);
  const [ariaRoute,  setAriaRoute]  = useState(null);

  // Routing
  const [alternatePath, setAlternatePath] = useState(null);
  const [originId, setOriginId] = useState(null);
  const [destId,   setDestId]   = useState(null);
  const [routingMode, setRoutingMode] = useState("idle");

  const pollRef = useRef(null);

  // ── City switch ──────────────────────────────────────────────────────────
  const switchCity = useCallback(async (cityId) => {
    const preset = CITY_PRESETS[cityId];
    if (!preset) return;
    setCity(cityId);
    setCenter({ lat: preset.lat, lng: preset.lng });
    setAlternatePath(null); setOriginId(null); setDestId(null);
    setRoutingMode("idle"); setSelected(null); setCityMenu(false);
    setAriaOpen(false);
    setIngestStatus("⟳ LOADING ROAD NETWORK...");
    try {
      const r = await fetch(`${API}/ingest/trigger/ingest-osm?city=${cityId}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
      });
      const d = await r.json();
      setIngestStatus(d.segments_inserted > 0 ? `✓ ${d.segments_inserted} ROADS LOADED` : "✓ NETWORK READY");
    } catch { setIngestStatus("⚠ OSM FETCH FAILED"); }
    setTimeout(() => setIngestStatus(null), 4000);
  }, [API, token]);

  // ── Traffic prediction ───────────────────────────────────────────────────
  const fetchPrediction = useCallback(async (lat, lng, h) => {
    if (!token) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/predict/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ latitude: lat, longitude: lng, radius_m: 2500, horizon_min: h }),
      });
      if (!r.ok) return;
      const data = await r.json();
      setSegments(data.segments || []);
      setWeather(data.weather_factor || 1.0);
    } catch (e) { console.error("Prediction sync error"); }
    finally { setLoading(false); }
  }, [token, API]);

  // ── A* routing ───────────────────────────────────────────────────────────
  const fetchAStarRoute = useCallback(async () => {
    if (!originId || !destId) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/graph/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ origin_node: originId.toString(), dest_node: destId.toString() })
      });
      if (r.ok) {
        const pathData = await r.json();
        if (pathData.status === "success" && pathData.segments) {
          const geojson = {
            type: "FeatureCollection",
            features: pathData.segments.map(s => ({
              type: "Feature",
              properties: { segment_id: s.segment_id },
              geometry: s.geometry
            }))
          };
          setAlternatePath(geojson);

          // Build ARIA route context
          const routeSegs = pathData.segments.map(s => {
            const full = segments.find(seg => seg.segment_id === s.segment_id);
            return full || { name: `Segment ${s.segment_id}`, speed_v: 30, density_k: 80, congestion_level: 1 };
          });
          setAriaRoute({
            origin_name: `Segment ${originId}`,
            dest_name:   `Segment ${destId}`,
            segments:    routeSegs,
          });

          // Auto-open ARIA with mission brief
          setAriaMode("route");
          setAriaOpen(true);
        } else {
          setAlternatePath(null);
        }
      }
    } catch (e) { console.error("A* error", e); }
    finally { setLoading(false); }
  }, [originId, destId, token, API, segments]);

  const handleSegmentSelect = (segmentId) => {
    if (routingMode === "origin") {
      setOriginId(segmentId); setRoutingMode("dest");
    } else if (routingMode === "dest") {
      setDestId(segmentId); setRoutingMode("idle");
    } else {
      setSelected(segmentId);
      // Auto-open ARIA with segment brief
      setAriaMode("segment");
      setAriaOpen(true);
    }
  };

  useEffect(() => {
    fetchPrediction(center.lat, center.lng, horizon);
    if (horizon === 0) {
      pollRef.current = setInterval(() => fetchPrediction(center.lat, center.lng, 0), 30000);
    }
    return () => clearInterval(pollRef.current);
  }, [horizon, center, fetchPrediction]);

  const fetchRoutes = useCallback(async () => {
    if (!token) return;
    try {
      const r = await fetch(`${API}/routes/`, { headers: { Authorization: `Bearer ${token}` } });
      if (r.ok) setSavedRoutes(await r.json());
    } catch {}
  }, [token, API]);

  useEffect(() => { fetchRoutes(); }, [fetchRoutes]);

  const onMapClick = ({ lat, lng }) => {
    setCenter({ lat, lng });
    fetchPrediction(lat, lng, horizon);
    if (routingMode === "idle") setAlternatePath(null);
  };

  const handlePDFExport = async () => {
    setPdfLoading(true);
    try {
      await exportIntelReport({
        city: CITY_PRESETS[city]?.name || city,
        segments,
        route: ariaRoute ? {
          origin: ariaRoute.origin_name,
          dest:   ariaRoute.dest_name,
          segment_count: ariaRoute.segments.length,
        } : null,
        stats: systemStats,
        weatherFactor,
        token,
        API,
      });
    } catch (e) { console.error("PDF export failed:", e); }
    finally { setPdfLoading(false); }
  };

  const congestionColor = (level) =>
    ({ 0:"#4ECDC4", 1:"#4ECDC4", 2:"#F7DC6F", 3:"#F0A500", 4:"#FF6B6B" })[level] ?? "#4ECDC4";

  const systemStats = {
    segments:      segments.length,
    avgSpeed:      segments.length ? Math.round(segments.reduce((a,s) => a+s.speed_v, 0) / segments.length) : "--",
    jams:          segments.filter(s => s.congestion_level >= 3).length,
    weather:       weatherFactor > 1.1 ? "ADVERSE" : "NOMINAL",
    weather_factor: weatherFactor,
  };

  const currentCity = CITY_PRESETS[city];
  const selectedSeg = segments.find(s => s.segment_id === selected);

  return (
    <div style={styles.shell}>
      {/* ── Top bar ── */}
      <header style={styles.topbar}>
        <div style={styles.topLeft}>
          <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="14" stroke="#4ECDC4" strokeWidth="1.5"/>
            <circle cx="16" cy="16" r="3" fill="#4ECDC4"/>
            <path d="M16 8L16 13M16 19L16 24M8 16L13 16M19 16L24 16" stroke="#4ECDC4" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <span style={styles.logoText}>TRAFFICOS</span>

          {demoMode && <span style={styles.demoBadge}>DEMO</span>}

          {/* City selector */}
          <div style={{ position: "relative" }}>
            <button style={styles.cityTag} onClick={() => setCityMenu(v => !v)}>
              {currentCity.name.toUpperCase()} · {horizon === 0 ? "LIVE" : `T+${horizon}MIN`} ▾
            </button>
            {cityMenuOpen && (
              <div style={styles.cityDropdown}>
                {Object.entries(CITY_PRESETS).map(([id, c]) => (
                  <button key={id}
                    style={{ ...styles.cityOption, color: id === city ? "#4ECDC4" : "rgba(78,205,196,0.5)" }}
                    onClick={() => switchCity(id)}>
                    {id === city ? "● " : "○ "}{c.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {ingestStatus && <span style={styles.ingestBadge}>{ingestStatus}</span>}
        </div>

        <div style={styles.statsRow}>
          {[
            ["SEGMENTS", systemStats.segments],
            ["AVG SPEED", `${systemStats.avgSpeed} km/h`],
            ["JAMS",     systemStats.jams],
            ["WEATHER",  systemStats.weather],
          ].map(([k, v]) => (
            <div key={k} style={styles.stat}>
              <span style={styles.statKey}>{k}</span>
              <span style={{ ...styles.statVal,
                color: k==="JAMS" && v>0 ? "#FF6B6B"
                     : k==="WEATHER" && v==="ADVERSE" ? "#F0A500"
                     : "#4ECDC4"
              }}>{v}</span>
            </div>
          ))}
        </div>

        <div style={styles.topRight}>
          {/* City Pulse button */}
          <button style={styles.pulseBtn} onClick={() => { setAriaMode("pulse"); setAriaOpen(true); }}>
            ◈ CITY PULSE
          </button>

          {/* PDF export */}
          <button style={styles.pdfBtn} onClick={handlePDFExport} disabled={pdfLoading}>
            {pdfLoading ? "⟳ GENERATING..." : "⬇ INTEL REPORT"}
          </button>

          <span style={styles.username}>{user?.username || "MISSION_CTRL"}</span>
          {!demoMode && <button style={styles.logoutBtn} onClick={logout}>LOGOUT</button>}
        </div>
      </header>

      {/* ── Body ── */}
      <div style={styles.body}>
        {sidebarOpen && (
          <Sidebar
            segments={segments} savedRoutes={savedRoutes} selected={selected}
            onSelect={handleSegmentSelect} onRefresh={fetchRoutes}
            token={token} API={API} congestionColor={congestionColor}
          />
        )}

        <div style={styles.mapWrap}>
          <MapView
            center={center} segments={segments} selected={selected}
            onSelect={handleSegmentSelect} onMapClick={onMapClick}
            API={API} congestionColor={congestionColor} alternatePath={alternatePath}
          />

          {/* A* Routing Panel */}
          <div style={styles.routingPanel}>
            <div style={styles.routingHeader}>A* DYNAMIC ROUTING</div>
            <div style={{ display:"flex", gap:8, marginBottom:10 }}>
              {[
                { label: originId ? `ORIGIN: ${originId}` : "+ SET ORIGIN", mode:"origin", id: originId },
                { label: destId   ? `DEST: ${destId}`     : "+ SET DEST",   mode:"dest",   id: destId   },
              ].map(btn => (
                <button key={btn.mode}
                  style={{ ...styles.routeBtn,
                    backgroundColor: routingMode===btn.mode ? "#4ECDC4" : "#131C2F",
                    color: routingMode===btn.mode ? "#080E1A" : "#4ECDC4",
                    border: routingMode===btn.mode ? "1px solid #FFF" : "1px solid #4ECDC4"
                  }}
                  onClick={() => setRoutingMode(v => v===btn.mode ? "idle" : btn.mode)}>
                  {btn.label}
                </button>
              ))}
            </div>
            <div style={{ display:"flex", gap:8 }}>
              <button onClick={fetchAStarRoute}
                disabled={!originId || !destId || loading}
                style={{ ...styles.actionBtn,
                  opacity: (!originId||!destId||loading) ? 0.4 : 1,
                  backgroundColor: (originId&&destId) ? "#4ECDC4" : "#F0A500"
                }}>
                {loading ? "CALCULATING..." : "EXECUTE MISSION"}
              </button>
              <button onClick={() => {
                setOriginId(null); setDestId(null); setAlternatePath(null);
                setRoutingMode("idle"); setAriaRoute(null); setAriaOpen(false);
              }} style={styles.clearBtn}>RESET</button>
            </div>
          </div>

          {/* ARIA Intelligence Panel */}
          {ariaOpen && (
            <ARIAPanel
              mode={ariaMode}
              segment={selectedSeg}
              route={ariaRoute}
              cityStats={systemStats}
              city={city}
              token={token}
              API={API}
              onClose={() => setAriaOpen(false)}
            />
          )}

          <div style={styles.sliderOverlay}>
            <TimeSlider value={horizon} onChange={setHorizon} />
          </div>

          <button style={styles.sidebarToggle} onClick={() => setSidebarOpen(v => !v)}>
            {sidebarOpen ? "◀" : "▶"}
          </button>

          <button style={styles.analyticsToggle} onClick={() => setAnalytics(v => !v)}>
            {analyticsOpen ? "▼ ANALYTICS" : "▲ ANALYTICS"}
          </button>
        </div>

        {selected && routingMode === "idle" && (
          <SegmentDetail
            segment={selectedSeg} horizon={horizon}
            onClose={() => setSelected(null)}
            token={token} API={API} congestionColor={congestionColor}
          />
        )}
      </div>

      {analyticsOpen && (
        <AnalyticsPanel
          segment={selectedSeg || segments[0]}
          token={token} API={API}
        />
      )}
    </div>
  );
}

const styles = {
  shell: { height:"100vh", display:"flex", flexDirection:"column", background:"#080E1A", fontFamily:"'Space Mono',monospace", overflow:"hidden" },
  topbar: { height:52, background:"rgba(12,20,36,0.98)", borderBottom:"1px solid rgba(78,205,196,0.15)", display:"flex", alignItems:"center", justifyContent:"space-between", padding:"0 16px", flexShrink:0, gap:16 },
  topLeft: { display:"flex", alignItems:"center", gap:10 },
  logoText: { fontSize:14, fontWeight:700, color:"#4ECDC4", letterSpacing:"0.15em" },
  demoBadge: { fontSize:8, color:"#080E1A", background:"#F0A500", padding:"2px 6px", borderRadius:2, letterSpacing:"0.1em", fontWeight:700 },
  cityTag: { fontSize:10, color:"rgba(78,205,196,0.7)", letterSpacing:"0.1em", marginLeft:6, padding:"3px 10px", border:"1px solid rgba(78,205,196,0.3)", borderRadius:3, background:"transparent", cursor:"pointer", fontFamily:"'Space Mono',monospace" },
  cityDropdown: { position:"absolute", top:"110%", left:6, background:"rgba(12,20,36,0.98)", border:"1px solid rgba(78,205,196,0.25)", borderRadius:4, minWidth:160, zIndex:100, display:"flex", flexDirection:"column" },
  cityOption: { padding:"9px 14px", fontSize:11, letterSpacing:"0.08em", background:"transparent", border:"none", cursor:"pointer", textAlign:"left", fontFamily:"'Space Mono',monospace", borderBottom:"1px solid rgba(78,205,196,0.08)" },
  ingestBadge: { fontSize:9, color:"#4ECDC4", letterSpacing:"0.08em", padding:"2px 8px", background:"rgba(78,205,196,0.1)", borderRadius:3 },
  statsRow: { display:"flex", gap:24, alignItems:"center" },
  stat: { display:"flex", flexDirection:"column", alignItems:"center", gap:1 },
  statKey: { fontSize:9, color:"rgba(78,205,196,0.4)", letterSpacing:"0.1em" },
  statVal: { fontSize:12, fontWeight:700, letterSpacing:"0.06em" },
  topRight: { display:"flex", alignItems:"center", gap:10 },
  pulseBtn: { fontSize:9, letterSpacing:"0.12em", background:"rgba(78,205,196,0.1)", border:"1px solid rgba(78,205,196,0.35)", borderRadius:3, color:"#4ECDC4", padding:"5px 10px", cursor:"pointer", fontFamily:"'Space Mono',monospace", transition:"all 0.15s" },
  pdfBtn: { fontSize:9, letterSpacing:"0.1em", background:"rgba(240,165,0,0.1)", border:"1px solid rgba(240,165,0,0.4)", borderRadius:3, color:"#F0A500", padding:"5px 10px", cursor:"pointer", fontFamily:"'Space Mono',monospace" },
  username: { fontSize:11, color:"rgba(78,205,196,0.5)", letterSpacing:"0.06em" },
  logoutBtn: { fontSize:10, letterSpacing:"0.1em", background:"transparent", border:"1px solid rgba(78,205,196,0.2)", borderRadius:2, color:"rgba(78,205,196,0.5)", padding:"4px 10px", cursor:"pointer", fontFamily:"'Space Mono',monospace" },
  body: { flex:1, display:"flex", overflow:"hidden", position:"relative" },
  mapWrap: { flex:1, position:"relative" },
  sliderOverlay: { position:"absolute", bottom:24, left:"50%", transform:"translateX(-50%)", zIndex:10, width:"min(480px,80%)" },
  routingPanel: { position:"absolute", top:16, right:16, zIndex:20, background:"rgba(12,20,36,0.9)", border:"1px solid rgba(78,205,196,0.3)", borderRadius:6, padding:"12px", width:"280px", boxShadow:"0 4px 20px rgba(0,0,0,0.5)" },
  routingHeader: { color:"#64748B", fontSize:"10px", fontWeight:"bold", letterSpacing:"0.1em", marginBottom:"8px" },
  routeBtn: { flex:1, padding:"8px 4px", fontSize:"10px", fontWeight:"bold", borderRadius:"4px", cursor:"pointer", transition:"all 0.2s", fontFamily:"'Space Mono',monospace" },
  actionBtn: { flex:2, padding:"8px", color:"#080E1A", border:"none", borderRadius:"4px", fontWeight:"bold", fontSize:"11px", cursor:"pointer", fontFamily:"'Space Mono',monospace" },
  clearBtn: { flex:1, padding:"8px", background:"transparent", color:"#FF6B6B", border:"1px solid #FF6B6B", borderRadius:"4px", fontWeight:"bold", fontSize:"11px", cursor:"pointer", fontFamily:"'Space Mono',monospace" },
  sidebarToggle: { position:"absolute", top:"50%", left:0, transform:"translateY(-50%)", background:"rgba(12,20,36,0.9)", border:"1px solid rgba(78,205,196,0.2)", borderLeft:"none", borderRadius:"0 4px 4px 0", color:"#4ECDC4", padding:"10px 6px", cursor:"pointer", fontFamily:"'Space Mono',monospace", fontSize:10, zIndex:10 },
  analyticsToggle: { position:"absolute", bottom:90, right:16, zIndex:10, background:"rgba(12,20,36,0.9)", border:"1px solid rgba(78,205,196,0.2)", borderRadius:3, color:"rgba(78,205,196,0.7)", padding:"6px 12px", cursor:"pointer", fontFamily:"'Space Mono',monospace", fontSize:10, letterSpacing:"0.1em" },
};

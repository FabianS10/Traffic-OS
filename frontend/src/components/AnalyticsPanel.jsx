import { useEffect, useRef, useState } from "react";

export default function AnalyticsPanel({ segment, token, API }) {
  const canvasRef  = useRef(null);
  const chartRef   = useRef(null);
  const [history, setHistory] = useState([]);
  const [metric,  setMetric]  = useState("speed_v");
  const [error, setError]     = useState(null);

  // ── Fetch history whenever segment changes ────────────────────────────────
  useEffect(() => {
    if (!segment || !token) { setHistory([]); return; }
    setError(null);
    const segId = segment.segment_id ?? segment.id;
    if (!segId) { setHistory([]); return; }

    fetch(`${API}/predict/segment/${segId}/history?hours=24`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setHistory(data);
        } else {
          // Backend returned empty — generate synthetic client-side preview
          setHistory(syntheticHistory(segId));
        }
      })
      .catch(e => {
        console.warn("Analytics fetch failed:", e.message);
        setError(e.message);
        setHistory(syntheticHistory(segId ?? 1));
      });
  }, [segment, token, API]);

  // ── Build / rebuild chart whenever history or metric changes ──────────────
  useEffect(() => {
    if (!canvasRef.current) return;

    // Wait for Chart.js to load (it's a CDN script tag in index.html)
    const Chart = window.Chart;
    if (!Chart) {
      console.warn("Chart.js not yet available");
      return;
    }

    // Destroy previous instance
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    if (history.length === 0) return;

    const labels = history.map(h =>
      new Date(h.timestamp ?? Date.now()).toLocaleTimeString("es-CO", { hour:"2-digit", minute:"2-digit" })
    );
    const values = history.map(h => h[metric] ?? 0);

    // Synthetic forecast tail
    const forecastLen = Math.floor(values.length * 0.25) || 3;
    const forecastLabels = [];
    const forecastValues = Array(values.length).fill(null);
    const lastVal = values[values.length - 1] ?? 0;
    for (let i = 0; i < forecastLen; i++) {
      const decay = 1 + (Math.sin(i * 0.8) * 0.05);
      forecastValues.push(+(lastVal * decay).toFixed(2));
      forecastLabels.push(`+${(i + 1) * 5}m`);
    }
    const allLabels = [...labels, ...forecastLabels];
    const historyPad = [...values, ...Array(forecastLen).fill(null)];

    const colorMap = { speed_v:"78,205,196", density_k:"240,165,0", flow_q:"149,224,119" };
    const c = colorMap[metric] || "78,205,196";

    try {
      chartRef.current = new Chart(canvasRef.current, {
        type: "line",
        data: {
          labels: allLabels,
          datasets: [
            {
              label: metricLabel(metric),
              data: historyPad,
              borderColor: `rgba(${c},0.9)`,
              backgroundColor: `rgba(${c},0.06)`,
              borderWidth: 1.5,
              fill: true,
              tension: 0.4,
              pointRadius: 0,
            },
            {
              label: "Forecast",
              data: forecastValues,
              borderColor: `rgba(${c},0.4)`,
              borderWidth: 1.5,
              borderDash: [5, 4],
              fill: false,
              tension: 0.4,
              pointRadius: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 300 },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "rgba(12,20,36,0.95)",
              titleColor: "#4ECDC4",
              bodyColor: "rgba(78,205,196,0.7)",
              borderColor: "rgba(78,205,196,0.2)",
              borderWidth: 1,
              titleFont: { family: "'Space Mono', monospace", size: 11 },
              bodyFont:  { family: "'Space Mono', monospace", size: 10 },
            },
          },
          scales: {
            x: {
              ticks: { color: "rgba(78,205,196,0.35)", font:{ family:"'Space Mono', monospace", size:9 }, maxTicksLimit:8 },
              grid:  { color: "rgba(78,205,196,0.06)" },
            },
            y: {
              ticks: { color: "rgba(78,205,196,0.35)", font:{ family:"'Space Mono', monospace", size:9 } },
              grid:  { color: "rgba(78,205,196,0.06)" },
            },
          },
        },
      });
    } catch (e) {
      console.error("Chart render error:", e);
    }

    return () => {
      if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
    };
  }, [history, metric]);

  const metricLabel = (m) =>
    ({ speed_v:"Speed (km/h)", density_k:"Density (veh/km)", flow_q:"Flow (veh/hr)" })[m] || m;

  const noData = history.length === 0;
  const segName = segment
    ? (segment.name || `SEGMENT ${segment.segment_id ?? segment.id}`)
    : null;

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.title}>
          {segName ? `${segName} · 24h TREND` : "SELECT A SEGMENT"}
          {error && <span style={{ color:"#F0A500", marginLeft:8, fontSize:9 }}>⚠ {error}</span>}
        </span>
        <div style={styles.metricToggle}>
          {["speed_v","density_k","flow_q"].map(m => (
            <button key={m} style={{ ...styles.mBtn, ...(metric===m ? styles.mActive : {}) }}
              onClick={() => setMetric(m)}>
              {metricLabel(m).split(" ")[0].toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.chartWrap}>
        {noData
          ? <div style={styles.noData}>NO DATA — SELECT A SEGMENT ON THE MAP</div>
          : <canvas ref={canvasRef} />
        }
      </div>

      {segment && (
        <div style={styles.kpiRow}>
          {[
            ["CURRENT SPEED", `${(segment.speed_v ?? 0).toFixed(1)} km/h`],
            ["DENSITY",       `${(segment.density_k ?? 0).toFixed(1)} veh/km`],
            ["FLOW",          `${(segment.flow_q ?? 0).toFixed(0)} veh/hr`],
            ["CONFIDENCE",    `${(((segment.confidence ?? 0) * 100)).toFixed(0)}%`],
          ].map(([k, v]) => (
            <div key={k} style={styles.kpi}>
              <span style={styles.kpiKey}>{k}</span>
              <span style={styles.kpiVal}>{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Client-side synthetic history so the chart always has something to show */
function syntheticHistory(segId) {
  const now = Date.now();
  return Array.from({ length: 24 }, (_, i) => {
    const hour = (new Date(now - i * 3600_000)).getHours();
    const base  = 30 + ((segId * 7 + hour) % 20);
    const noise = Math.sin(i * 0.7 + segId) * 5;
    return {
      timestamp:     new Date(now - i * 3600_000).toISOString(),
      speed_v:       Math.max(5, +(base + noise).toFixed(1)),
      density_k:     Math.max(0, +(80 - base / 2 + noise).toFixed(1)),
      flow_q:        Math.max(0, +((base + noise) * 2.5).toFixed(0)),
    };
  }).reverse();
}

const styles = {
  panel: {
    backgroundColor: "rgba(8,14,26,0.98)",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: "rgba(78,205,196,0.15)",
    height: 220,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    fontFamily: "'Space Mono', monospace"
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 16px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: "rgba(78,205,196,0.1)"
  },
  title: { fontSize: 11, color: "rgba(78,205,196,0.7)", letterSpacing: "0.08em" },
  metricToggle: { display: "flex", gap: 4 },
  mBtn: {
    padding: "3px 10px",
    fontSize: 9,
    letterSpacing: "0.1em",
    backgroundColor: "transparent",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(78,205,196,0.15)",
    borderRadius: 2,
    color: "rgba(78,205,196,0.4)",
    cursor: "pointer",
    fontFamily: "'Space Mono', monospace",
    transition: "all 0.15s"
  },
  mActive: { backgroundColor: "rgba(78,205,196,0.12)", color: "#4ECDC4", borderColor: "rgba(78,205,196,0.4)" },
  chartWrap: { flex: 1, padding: "8px 16px", minHeight: 0 },
  noData: { display: "flex", alignItems: "center", justifyContent: "center", height: "100%", fontSize: 10, color: "rgba(78,205,196,0.25)", letterSpacing: "0.08em" },
  kpiRow: {
    display: "flex",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: "rgba(78,205,196,0.1)",
    padding: "6px 16px",
    gap: 32
  },
  kpi: { display: "flex", flexDirection: "column", gap: 2 },
  kpiKey: { fontSize: 9, color: "rgba(78,205,196,0.4)", letterSpacing: "0.1em" },
  kpiVal: { fontSize: 12, color: "#4ECDC4", fontWeight: 700 },
};

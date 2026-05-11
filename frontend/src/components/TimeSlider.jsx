import { useState } from "react";

const PRESETS = [
  { label: "LIVE",  value: 0   },
  { label: "+15m",  value: 15  },
  { label: "+30m",  value: 30  },
  { label: "+1h",   value: 60  },
  { label: "+2h",   value: 120 },
  { label: "+4h",   value: 240 },
  { label: "+8h",   value: 480 },
  { label: "+24h",  value: 1440},
];

export default function TimeSlider({ value, onChange }) {
  const maxMinutes = 1440;

  const sliderChange = (e) => {
    const raw = parseInt(e.target.value);
    // Snap to nearest preset for feel, but allow free drag
    onChange(raw);
  };

  const label = value === 0
    ? "LIVE — real-time data"
    : `T + ${value >= 60 ? `${(value/60).toFixed(1)}h` : `${value}min`} projection`;

  return (
    <div style={styles.wrap}>
      <div style={styles.labelRow}>
        <span style={styles.label}>{label}</span>
        {value > 0 && (
          <span style={styles.eta}>
            {new Date(Date.now() + value * 60000).toLocaleTimeString("es-CO", { hour:"2-digit", minute:"2-digit" })}
          </span>
        )}
      </div>

      {/* Preset buttons */}
      <div style={styles.presets}>
        {PRESETS.map(p => (
          <button key={p.value} style={{ ...styles.preset, ...(value===p.value ? styles.presetActive : {}) }}
            onClick={() => onChange(p.value)}>
            {p.label}
          </button>
        ))}
      </div>

      {/* Range slider */}
      <input
        type="range"
        min={0} max={maxMinutes} step={5}
        value={value}
        onChange={sliderChange}
        style={styles.slider}
      />

      <div style={styles.tickRow}>
        <span style={styles.tick}>NOW</span>
        <span style={styles.tick}>+6h</span>
        <span style={styles.tick}>+12h</span>
        <span style={styles.tick}>+18h</span>
        <span style={styles.tick}>+24h</span>
      </div>
    </div>
  );
}

const styles = {
  wrap: {
    background: "rgba(8,14,26,0.92)",
    border: "1px solid rgba(78,205,196,0.2)",
    borderRadius: 4,
    padding: "12px 16px",
    backdropFilter: "blur(12px)",
  },
  labelRow: { display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 },
  label: { fontSize:11, color:"#4ECDC4", letterSpacing:"0.08em" },
  eta:   { fontSize:11, color:"rgba(78,205,196,0.5)", fontVariantNumeric:"tabular-nums" },
  presets: { display:"flex", gap:4, marginBottom:10, flexWrap:"wrap" },
  preset: {
    padding: "4px 8px",
    fontSize: 10,
    letterSpacing: "0.08em",
    background: "rgba(78,205,196,0.05)",
    border: "1px solid rgba(78,205,196,0.15)",
    borderRadius: 2,
    color: "rgba(78,205,196,0.5)",
    cursor: "pointer",
    fontFamily: "'Space Mono', monospace",
    transition: "all 0.15s",
  },
  presetActive: {
    background: "rgba(78,205,196,0.18)",
    color: "#4ECDC4",
    borderColor: "rgba(78,205,196,0.5)",
  },
  slider: {
    width: "100%",
    accentColor: "#4ECDC4",
    cursor: "pointer",
    height: 3,
  },
  tickRow: { display:"flex", justifyContent:"space-between", marginTop:4 },
  tick: { fontSize:9, color:"rgba(78,205,196,0.3)", letterSpacing:"0.06em" },
};

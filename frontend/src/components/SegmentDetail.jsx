import { useState } from "react";

export default function SegmentDetail({ segment, horizon, onClose, token, API, congestionColor }) {
  const [saving, setSaving]   = useState(false);
  const [saved,  setSaved]    = useState(false);
  const [routeName, setName]  = useState("");
  const [showSave, setShowSave] = useState(false);

  if (!segment) return null;

  const saveRoute = async () => {
    if (!routeName.trim()) return;
    setSaving(true);
    try {
      await fetch(`${API}/routes/`, {
        method: "POST",
        headers: { "Content-Type":"application/json", Authorization:`Bearer ${token}` },
        body: JSON.stringify({
          name: routeName,
          origin_name: segment.name || `Segment ${segment.segment_id}`,
          dest_name: "—",
          origin_lat: 4.3366, origin_lon: -74.3641,
          dest_lat:   4.3366, dest_lon:   -74.3641,
          segment_ids: [segment.segment_id],
        }),
      });
      setSaved(true);
      setShowSave(false);
    } finally {
      setSaving(false);
    }
  };

  const color   = congestionColor(segment.congestion_level);
  const kRatio  = segment.density_k / 120;    // approximate jam density
  const capacity = segment.flow_q / Math.max(1, segment.speed_limit || 50 * 120 / 4);

  return (
    <div style={{ ...styles.wrap, borderLeft:`1px solid ${color}30` }}>
      <div style={styles.header}>
        <div>
          <div style={styles.name}>{segment.name || `SEGMENT ${segment.segment_id}`}</div>
          <div style={{ ...styles.level, color }}>
            {segment.congestion_label}
            {horizon > 0 && <span style={styles.horizonTag}> · T+{horizon}min</span>}
          </div>
        </div>
        <button style={styles.close} onClick={onClose}>×</button>
      </div>

      {/* Greenshields visual */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>GREENSHIELDS MODEL</div>
        <div style={styles.formula}>v = v_f × (1 − k/k_j)</div>
        <div style={styles.kpiGrid}>
          {[
            ["SPEED v",    `${segment.speed_v?.toFixed(1)} km/h`,    color],
            ["DENSITY k",  `${segment.density_k?.toFixed(1)} veh/km`, color],
            ["FLOW q",     `${segment.flow_q?.toFixed(0)} veh/hr`,    color],
            ["k/k_j",      `${(kRatio*100).toFixed(0)}%`,             kRatio > 0.7 ? "#FF6B6B" : "#4ECDC4"],
          ].map(([k,v,c]) => (
            <div key={k} style={styles.kpiCard}>
              <span style={styles.kpiKey}>{k}</span>
              <span style={{ ...styles.kpiVal, color:c }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Density bar */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>ROAD OCCUPANCY</div>
        <div style={styles.barOuter}>
          <div style={{ ...styles.barInner, width:`${Math.min(100,kRatio*100)}%`, background:color, boxShadow:`0 0 8px ${color}40` }} />
        </div>
        <div style={styles.barLabels}>
          <span>FREE</span><span>CAPACITY</span><span>JAM</span>
        </div>
      </div>

      {/* Model info */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>PREDICTION INFO</div>
        <div style={styles.infoRow}><span>Model</span><span>{segment.model_used}</span></div>
        <div style={styles.infoRow}><span>Confidence</span><span>{((segment.confidence||0)*100).toFixed(0)}%</span></div>
        <div style={styles.infoRow}><span>Horizon</span><span>{horizon === 0 ? "Live" : `+${horizon} min`}</span></div>
      </div>

      {/* Save route */}
      <div style={styles.section}>
        {!showSave ? (
          <button style={styles.saveBtn} onClick={() => setShowSave(true)} disabled={saved}>
            {saved ? "ROUTE SAVED" : "SAVE THIS SEGMENT"}
          </button>
        ) : (
          <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
            <input
              style={styles.nameInput}
              placeholder="Route name..."
              value={routeName}
              onChange={e => setName(e.target.value)}
            />
            <div style={{ display:"flex", gap:6 }}>
              <button style={styles.saveBtn} onClick={saveRoute} disabled={saving || !routeName.trim()}>
                {saving ? "SAVING..." : "CONFIRM"}
              </button>
              <button style={{ ...styles.saveBtn, color:"rgba(255,107,107,0.6)", borderColor:"rgba(255,107,107,0.3)" }}
                onClick={() => setShowSave(false)}>
                CANCEL
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  wrap:        { width:240, background:"rgba(10,16,28,0.98)", display:"flex", flexDirection:"column", fontFamily:"'Space Mono', monospace", flexShrink:0 },
  header:      { display:"flex", alignItems:"flex-start", justifyContent:"space-between", padding:"14px 14px 10px", borderBottom:"1px solid rgba(78,205,196,0.1)" },
  name:        { fontSize:12, color:"rgba(78,205,196,0.9)", letterSpacing:"0.06em", marginBottom:4 },
  level:       { fontSize:10, letterSpacing:"0.1em", fontWeight:700 },
  horizonTag:  { fontSize:9, opacity:0.7 },
  close:       { fontSize:18, background:"none", border:"none", color:"rgba(78,205,196,0.4)", cursor:"pointer", lineHeight:1, padding:"0 2px" },
  section:     { padding:"12px 14px", borderBottom:"1px solid rgba(78,205,196,0.07)" },
  sectionTitle:{ fontSize:9, color:"rgba(78,205,196,0.35)", letterSpacing:"0.12em", marginBottom:8 },
  formula:     { fontSize:10, color:"rgba(78,205,196,0.5)", fontStyle:"italic", marginBottom:10, letterSpacing:"0.04em" },
  kpiGrid:     { display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 },
  kpiCard:     { background:"rgba(78,205,196,0.04)", border:"1px solid rgba(78,205,196,0.1)", borderRadius:3, padding:"7px 8px" },
  kpiKey:      { display:"block", fontSize:9, color:"rgba(78,205,196,0.4)", letterSpacing:"0.08em", marginBottom:3 },
  kpiVal:      { display:"block", fontSize:12, fontWeight:700, letterSpacing:"0.04em" },
  barOuter:    { height:6, background:"rgba(78,205,196,0.08)", borderRadius:3, overflow:"hidden", marginBottom:4 },
  barInner:    { height:"100%", borderRadius:3, transition:"width 0.5s, background 0.3s" },
  barLabels:   { display:"flex", justifyContent:"space-between", fontSize:8, color:"rgba(78,205,196,0.25)", letterSpacing:"0.06em" },
  infoRow:     { display:"flex", justifyContent:"space-between", fontSize:10, color:"rgba(78,205,196,0.5)", marginBottom:5 },
  saveBtn:     { width:"100%", padding:"8px 0", background:"rgba(78,205,196,0.08)", border:"1px solid rgba(78,205,196,0.25)", borderRadius:3, color:"rgba(78,205,196,0.7)", fontSize:10, letterSpacing:"0.1em", cursor:"pointer", fontFamily:"'Space Mono', monospace", transition:"all 0.15s" },
  nameInput:   { width:"100%", background:"rgba(78,205,196,0.04)", border:"1px solid rgba(78,205,196,0.2)", borderRadius:3, padding:"7px 10px", color:"#E8F4F4", fontSize:11, fontFamily:"'Space Mono', monospace", outline:"none", boxSizing:"border-box" },
};

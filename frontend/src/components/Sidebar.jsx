import { useState, useEffect } from "react";

export default function Sidebar({ segments, savedRoutes, selected, onSelect, onRefresh, token, API, congestionColor }) {
  const [tab, setTab] = useState("segments");
  const sorted = [...segments].sort((a, b) => b.congestion_level - a.congestion_level);

  // EFECTO CORREGIDO: Auto-scroll suave y sin glitches
  useEffect(() => {
    if (selected && tab === "segments") {
      setTimeout(() => {
        const el = document.getElementById(`seg-card-${selected}`);
        if (el) {
          // "nearest" asegura que solo el sidebar haga scroll, protegiendo el layout
          el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }, 50); // El pequeño retraso permite que React actualice el DOM primero
    }
  }, [selected, tab]);

  return (
    <div style={styles.wrap}>
      <div style={styles.tabs}>
        {[["segments","SEGMENTS"],["routes","MY ROUTES"]].map(([key,label]) => (
          <button 
            key={key} 
            style={{ ...styles.tab, ...(tab===key ? styles.tabActive : {}) }} 
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "segments" ? (
        <SegmentList segments={sorted} selected={selected} onSelect={onSelect} congestionColor={congestionColor} />
      ) : (
        <div style={styles.empty}>COMING SOON</div>
      )}
    </div>
  );
}

function SegmentList({ segments, selected, onSelect, congestionColor }) {
  if (segments.length === 0) return <div style={styles.empty}>NO SEGMENTS IN RANGE</div>;

  return (
    <div style={styles.list}>
      {segments.map(seg => (
        <button 
          key={seg.segment_id}
          id={`seg-card-${seg.segment_id}`}
          style={{ ...styles.segItem, ...(selected===seg.segment_id ? styles.segActive : {}) }}
          onClick={() => onSelect(seg.segment_id)}
        >
          <div style={styles.segTop}>
            <span style={styles.segName}>{seg.name || `SEG ${seg.segment_id}`}</span>
            <div style={{ 
              ...styles.congBadge, 
              backgroundColor: `${congestionColor(seg.congestion_level)}20`, 
              color: congestionColor(seg.congestion_level), 
              borderColor: `${congestionColor(seg.congestion_level)}40` 
            }}>
              {seg.congestion_label || "LIVE"}
            </div>
          </div>
          <div style={styles.segStats}>
            <span>{seg.speed_v?.toFixed(0)} km/h</span>
            <span>{seg.density_k?.toFixed(0)} v/km</span>
          </div>
          <div style={styles.miniBar}>
            <div style={{ 
              width:`${Math.min(100,(seg.density_k||0))}%`, 
              height:"100%", 
              backgroundColor: congestionColor(seg.congestion_level), 
              transition:"width 0.4s" 
            }} />
          </div>
        </button>
      ))}
    </div>
  );
}

const styles = {
  wrap: {
    width: '320px',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: '#080E1A',
    borderRightWidth: '1px',
    borderRightStyle: 'solid',
    borderRightColor: '#1E293B',
    overflow: 'hidden'
  },
  tabs: {
    display: 'flex',
    padding: '10px',
    gap: '10px',
    borderBottomWidth: '1px',
    borderBottomStyle: 'solid',
    borderBottomColor: '#1E293B'
  },
  tab: {
    flex: 1,
    padding: '8px',
    background: 'transparent',
    borderWidth: '1px',
    borderStyle: 'solid',
    borderColor: 'transparent',
    color: '#64748B',
    fontSize: '11px',
    fontWeight: 'bold',
    cursor: 'pointer',
    transition: '0.3s'
  },
  tabActive: {
    color: '#4ECDC4',
    borderColor: 'transparent',
    borderBottomColor: '#4ECDC4',
    borderBottomWidth: '2px'
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '10px'
  },
  segItem: {
    width: '100%',
    padding: '15px',
    marginBottom: '10px',
    backgroundColor: '#0F172A',
    borderWidth: '1px',
    borderStyle: 'solid',
    borderColor: '#1E293B',
    borderRadius: '8px',
    textAlign: 'left',
    cursor: 'pointer',
    transition: '0.2s',
    fontFamily: 'inherit'
  },
  segActive: {
    borderColor: '#4ECDC4',
    backgroundColor: '#131C2F',
    boxShadow: '0 0 15px rgba(78, 205, 196, 0.1)'
  },
  segTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' },
  segName: { color: '#F8FAFC', fontWeight: 'bold', fontSize: '14px' },
  congBadge: {
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '10px',
    fontWeight: 'bold',
    borderWidth: '1px',
    borderStyle: 'solid'
  },
  segStats: { display: 'flex', gap: '15px', color: '#94A3B8', fontSize: '12px', marginBottom: '10px' },
  miniBar: { width: '100%', height: '4px', backgroundColor: '#1E293B', borderRadius: '2px', overflow: 'hidden' },
  empty: { padding: '40px 20px', textAlign: 'center', color: '#475569', fontSize: '12px', letterSpacing: '1px' }
};
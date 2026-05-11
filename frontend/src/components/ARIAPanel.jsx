import { useState, useEffect, useRef, useCallback } from "react";

const TYPING_CHARS = ["▋", "▌", "▍", "▎", "▏", "▎", "▍", "▌"];

export default function ARIAPanel({
  segment, route, cityStats, city, token, API,
  onClose, mode = "idle", // "segment" | "route" | "pulse" | "idle"
}) {
  const [text,    setText]    = useState("");
  const [loading, setLoading] = useState(false);
  const [blink,   setBlink]   = useState(0);
  const [pulse,   setPulse]   = useState(null);
  const scrollRef = useRef(null);
  const abortRef  = useRef(null);

  // Blink cursor while streaming
  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => setBlink(b => (b + 1) % TYPING_CHARS.length), 120);
    return () => clearInterval(t);
  }, [loading]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [text]);

  const streamBrief = useCallback(async (endpoint, body) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    setText("");
    setPulse(null);
    setLoading(true);

    try {
      const resp = await fetch(`${API}/aria/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
        signal: abortRef.current.signal,
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;
          try {
            const parsed = JSON.parse(data);
            accumulated += parsed.text || "";
            setText(accumulated);

            // Extract pulse score if present
            const pulseMatch = accumulated.match(/PULSE:\s*(\d+)\/100/);
            if (pulseMatch) setPulse(parseInt(pulseMatch[1]));
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setText("⚠ ARIA: Connection lost. Intelligence systems temporarily offline.");
      }
    } finally {
      setLoading(false);
    }
  }, [API, token]);

  // Auto-trigger based on mode
  useEffect(() => {
    if (mode === "segment" && segment) {
      streamBrief("segment-brief", {
        segment_name: segment.name || `Segment ${segment.segment_id}`,
        speed_v: segment.speed_v || 0,
        density_k: segment.density_k || 0,
        congestion_level: segment.congestion_level || 0,
        flow_q: segment.flow_q || 0,
        city,
        horizon_min: 0,
      });
    } else if (mode === "route" && route) {
      streamBrief("route-mission", {
        city,
        origin_name: route.origin_name || "Origin",
        dest_name: route.dest_name || "Destination",
        segments: route.segments || [],
        weather_factor: cityStats?.weather_factor || 1.0,
        horizon_min: 0,
      });
    } else if (mode === "pulse") {
      streamBrief("city-pulse", {
        city,
        total_segments: cityStats?.segments || 0,
        jam_count: cityStats?.jams || 0,
        avg_speed: cityStats?.avgSpeed || 0,
        weather_factor: cityStats?.weather_factor || 1.0,
        horizon_min: 0,
      });
    }
  }, [mode, segment, route]); // eslint-disable-line

  const modeTitle = {
    segment: `◈ ${segment?.name || "SEGMENT ANALYSIS"}`,
    route:   "◈ MISSION BRIEFING",
    pulse:   "◈ CITY PULSE",
    idle:    "◈ ARIA READY",
  }[mode];

  // Format text with tactical styling
  const renderText = () => {
    if (!text && !loading) return (
      <div style={styles.idleMsg}>
        ARIA STANDING BY — Select a segment or execute a route mission to receive tactical intelligence.
      </div>
    );

    const lines = text.split("\n").filter((l, i, arr) => !(l === "" && arr[i-1] === ""));
    return lines.map((line, i) => {
      const isBold = /^(ROUTE STATUS|THREAT VECTORS?|ETA ESTIMATE|RECOMMENDED ACTION|PULSE:|PARAGRAPH \d|EXECUTIVE SUMMARY|CRITICAL THREATS|OPERATIONAL REC)/i.test(line.trim());
      const isWarning = /critical|jam|threat|⚠|adverse/i.test(line);
      return (
        <div key={i} style={{
          ...styles.line,
          color: isBold ? "#4ECDC4" : isWarning ? "#F0A500" : "rgba(78,205,196,0.75)",
          fontWeight: isBold ? 700 : 400,
          marginBottom: isBold ? 8 : 2,
          marginTop: isBold ? (i > 0 ? 12 : 0) : 0,
          letterSpacing: isBold ? "0.12em" : "0.04em",
        }}>
          {line}
        </div>
      );
    });
  };

  return (
    <div style={styles.panel}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <div style={{ ...styles.statusDot, background: loading ? "#F0A500" : "#4ECDC4",
            boxShadow: `0 0 8px ${loading ? "#F0A500" : "#4ECDC4"}` }} />
          <span style={styles.ariaBadge}>ARIA</span>
          <span style={styles.modeTitle}>{modeTitle}</span>
        </div>
        <div style={styles.headerRight}>
          {pulse !== null && (
            <div style={styles.pulseBadge}>
              <span style={styles.pulseScore}>{pulse}</span>
              <span style={styles.pulseLabel}>/100</span>
            </div>
          )}
          {loading && (
            <span style={styles.streaming}>
              {TYPING_CHARS[blink]} ANALYZING
            </span>
          )}
          <button style={styles.closeBtn} onClick={onClose}>✕</button>
        </div>
      </div>

      {/* Text output */}
      <div style={styles.body} ref={scrollRef}>
        <div style={styles.textWrap}>
          {renderText()}
          {loading && <span style={{ color: "#4ECDC4", opacity: 0.7 }}>{TYPING_CHARS[blink]}</span>}
        </div>
      </div>

      {/* Action bar */}
      <div style={styles.footer}>
        <button style={styles.footerBtn}
          onClick={() => mode === "pulse"
            ? streamBrief("city-pulse", {
                city, total_segments: cityStats?.segments||0,
                jam_count: cityStats?.jams||0, avg_speed: cityStats?.avgSpeed||0,
                weather_factor: cityStats?.weather_factor||1.0
              })
            : mode === "segment"
            ? streamBrief("segment-brief", {
                segment_name: segment?.name||"Segment",
                speed_v: segment?.speed_v||0, density_k: segment?.density_k||0,
                congestion_level: segment?.congestion_level||0, city
              })
            : streamBrief("route-mission", {
                city, segments: route?.segments||[],
                weather_factor: cityStats?.weather_factor||1.0
              })
          }
          disabled={loading}
        >
          ↺ REANALYZE
        </button>
        <div style={styles.footerTag}>
          POWERED BY GEMINI FLASH · TRAFFICOS NEURAL ENGINE
        </div>
      </div>
    </div>
  );
}

const styles = {
  panel: {
    position: "absolute", bottom: 90, left: 370, right: 310,
    zIndex: 30,
    background: "rgba(6,10,20,0.97)",
    border: "1px solid rgba(78,205,196,0.3)",
    borderRadius: 6,
    display: "flex", flexDirection: "column",
    maxHeight: 280,
    boxShadow: "0 0 40px rgba(78,205,196,0.08), 0 8px 32px rgba(0,0,0,0.6)",
    backdropFilter: "blur(12px)",
    fontFamily: "'Space Mono', monospace",
  },
  header: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "10px 14px",
    borderBottom: "1px solid rgba(78,205,196,0.12)",
    flexShrink: 0,
  },
  headerLeft:  { display: "flex", alignItems: "center", gap: 8 },
  headerRight: { display: "flex", alignItems: "center", gap: 10 },
  statusDot: { width: 7, height: 7, borderRadius: "50%", transition: "all 0.3s" },
  ariaBadge: {
    fontSize: 9, fontWeight: 700, letterSpacing: "0.18em",
    color: "#080E1A", background: "#4ECDC4",
    padding: "2px 6px", borderRadius: 2,
  },
  modeTitle: { fontSize: 10, color: "rgba(78,205,196,0.6)", letterSpacing: "0.1em" },
  pulseBadge: {
    display: "flex", alignItems: "baseline", gap: 1,
    background: "rgba(78,205,196,0.1)", border: "1px solid rgba(78,205,196,0.3)",
    borderRadius: 3, padding: "2px 8px",
  },
  pulseScore: { fontSize: 14, fontWeight: 700, color: "#4ECDC4" },
  pulseLabel: { fontSize: 9,  color: "rgba(78,205,196,0.5)" },
  streaming: { fontSize: 9, color: "#F0A500", letterSpacing: "0.12em", animation: "none" },
  closeBtn: {
    background: "transparent", border: "none", color: "rgba(78,205,196,0.4)",
    cursor: "pointer", fontSize: 12, padding: "2px 4px",
    fontFamily: "'Space Mono', monospace",
  },
  body: { flex: 1, overflowY: "auto", padding: "12px 14px", minHeight: 80 },
  textWrap: { lineHeight: 1.7 },
  line: { fontSize: 11, display: "block" },
  idleMsg: {
    fontSize: 10, color: "rgba(78,205,196,0.25)", letterSpacing: "0.06em",
    lineHeight: 1.8, paddingTop: 8,
  },
  footer: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "8px 14px",
    borderTop: "1px solid rgba(78,205,196,0.1)",
    flexShrink: 0,
  },
  footerBtn: {
    fontSize: 9, letterSpacing: "0.12em", color: "#4ECDC4",
    background: "rgba(78,205,196,0.08)", border: "1px solid rgba(78,205,196,0.2)",
    borderRadius: 2, padding: "4px 10px", cursor: "pointer",
    fontFamily: "'Space Mono', monospace",
  },
  footerTag: { fontSize: 8, color: "rgba(78,205,196,0.2)", letterSpacing: "0.1em" },
};

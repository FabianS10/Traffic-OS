/**
 * TrafficOS · PDF Intel Report Generator
 * Generates a clean declassified-style briefing document using jsPDF.
 *
 * Improved version:
 * - Better contrast/readability
 * - Cleaner typography
 * - No unsupported decorative glyphs
 * - Markdown cleanup for Gemini/ARIA output
 * - Better KPI cards and segment table
 * - Safer page breaks
 */

export async function exportIntelReport({
  city,
  segments = [],
  route,
  stats = {},
  weatherFactor = 1.0,
  token,
  API,
}) {
  // Dynamically load jsPDF from CDN if not present
  if (!window.jspdf) {
    await new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";
      s.onload = res;
      s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({
    orientation: "portrait",
    unit: "mm",
    format: "a4",
  });

  // ─────────────────────────────────────────────────────────────
  // Fetch ARIA-generated report text
  // ─────────────────────────────────────────────────────────────
  let reportText = "Intelligence report unavailable. ARIA fallback mode active.";

  try {
    const headers = {
      "Content-Type": "application/json",
    };

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const resp = await fetch(`${API}/aria/pdf-report`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        city,
        segments,
        route,
        stats,
        weather_factor: weatherFactor,
      }),
    });

    const data = await resp.json();
    reportText = data.report_text || reportText;
    city = data.city || city;
  } catch (e) {
    console.warn("ARIA PDF fetch failed:", e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // Constants
  // ─────────────────────────────────────────────────────────────
  const now = new Date();

  const timestamp =
    now.toISOString().replace("T", " ").slice(0, 19) + " UTC";

  const dateStr = now.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const cityLabel =
    String(city).toLowerCase().includes("francisco")
      ? "San Francisco, CA"
      : city || "Unknown Area";

  const safeCityFile = cityLabel.replace(/[^a-z0-9]/gi, "_");
  const reportId = Math.random().toString(36).slice(2, 10).toUpperCase();

  const W = 210;
  const H = 297;
  const M = 18;
  const CONTENT_W = W - M * 2;

  let y = 0;

  // ─────────────────────────────────────────────────────────────
  // Palette
  // ─────────────────────────────────────────────────────────────
  const C = {
    page: [244, 247, 250],
    panel: [255, 255, 255],
    header: [7, 20, 38],
    card: [11, 27, 43],
    card2: [13, 34, 54],
    border: [202, 212, 224],
    borderDark: [25, 58, 82],

    cyan: [54, 227, 227],
    cyanSoft: [142, 242, 242],
    cyanMuted: [77, 164, 170],

    text: [19, 34, 53],
    muted: [94, 115, 138],
    inverse: [234, 251, 255],

    success: [47, 191, 113],
    warning: [244, 185, 66],
    danger: [239, 91, 91],
    amber: [245, 176, 32],
  };

  const setText = (color) => doc.setTextColor(...color);
  const setFill = (color) => doc.setFillColor(...color);
  const setDraw = (color) => doc.setDrawColor(...color);

  // ─────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────
  function cleanReportText(text) {
    return String(text || "")
      // Remove markdown emphasis
      .replace(/\*\*(.*?)\*\*/g, "$1")
      .replace(/\*(.*?)\*/g, "$1")
      .replace(/#+\s*/g, "")
      // Remove unsupported decorative symbols that caused weird PDF glyphs
      .replace(/[◈◆◇▸▶●■□▪▫]/g, "")
      // Remove Gemini placeholder dates if present
      .replace(/DATE:\s*\[Current Date\/Time\]/gi, "")
      .replace(/\[Current Date\/Time\]/gi, timestamp)
      // Normalize excess whitespace
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function statusLabel(level) {
    return ["FREE FLOW", "LIGHT", "MODERATE", "HEAVY", "JAM"][level] ?? "UNKNOWN";
  }

  function statusColor(level) {
    if (level >= 4) return C.danger;
    if (level === 3) return C.amber;
    if (level === 2) return C.warning;
    if (level === 1) return C.success;
    return C.cyanMuted;
  }

  function drawPageBackground() {
    setFill(C.page);
    doc.rect(0, 0, W, H, "F");
  }

  function drawMiniPageHeader() {
    setFill(C.header);
    doc.rect(0, 0, W, 18, "F");

    doc.setFont("courier", "bold");
    doc.setFontSize(7);
    setText(C.cyanSoft);
    doc.text("TRAFFICOS · INTELLIGENCE CONTINUATION", M, 11);
    doc.text(`TOS-${reportId}`, W - M, 11, { align: "right" });

    setDraw(C.cyan);
    doc.setLineWidth(0.25);
    doc.line(M, 18, W - M, 18);
  }

  function addPageIfNeeded(requiredHeight = 20) {
    if (y + requiredHeight <= 272) return;

    doc.addPage();
    drawPageBackground();
    drawMiniPageHeader();
    y = 28;
  }

  function drawSectionTitle(title) {
    addPageIfNeeded(16);

    doc.setFont("courier", "bold");
    doc.setFontSize(9);
    setText(C.cyanMuted);
    doc.text(title.toUpperCase(), M, y);

    y += 4;
    setDraw(C.cyanMuted);
    doc.setLineWidth(0.25);
    doc.line(M, y, W - M, y);
    y += 8;
  }

  function drawPanel(x, y0, width, height, fill = C.panel, stroke = C.border) {
    setFill(fill);
    setDraw(stroke);
    doc.setLineWidth(0.25);
    doc.roundedRect(x, y0, width, height, 2, 2, "FD");
  }

  function drawParagraph(text, options = {}) {
    const {
      x = M,
      width = CONTENT_W,
      font = "helvetica",
      style = "normal",
      size = 9.5,
      lineHeight = 5.2,
      color = C.text,
      paragraphGap = 3,
    } = options;

    const cleaned = cleanReportText(text);
    const paragraphs = cleaned.split(/\n+/).map((p) => p.trim()).filter(Boolean);

    doc.setFont(font, style);
    doc.setFontSize(size);
    setText(color);

    paragraphs.forEach((p) => {
      addPageIfNeeded(14);

      const isHeader =
        /^(EXECUTIVE SUMMARY|CRITICAL THREATS|OPERATIONAL RECOMMENDATIONS|ROUTE STATUS|THREAT VECTORS|ETA ESTIMATE|RECOMMENDED ACTION|PARAGRAPH\s*\d+)/i.test(
          p
        );

      if (isHeader) {
        doc.setFont("courier", "bold");
        doc.setFontSize(8.5);
        setText(C.cyanMuted);
      } else {
        doc.setFont(font, style);
        doc.setFontSize(size);
        setText(color);
      }

      const lines = doc.splitTextToSize(p, width);

      lines.forEach((line) => {
        addPageIfNeeded(lineHeight + 2);
        doc.text(line, x, y);
        y += lineHeight;
      });

      y += paragraphGap;
    });
  }

  // ─────────────────────────────────────────────────────────────
  // Page 1 background
  // ─────────────────────────────────────────────────────────────
  drawPageBackground();

  // ─────────────────────────────────────────────────────────────
  // Header block
  // ─────────────────────────────────────────────────────────────
  setFill(C.header);
  doc.rect(0, 0, W, 48, "F");

  doc.setFont("courier", "bold");
  doc.setFontSize(7);
  setText(C.cyanSoft);
  doc.text("TRAFFICOS · NEURAL TRAFFIC INTELLIGENCE SYSTEM", M, 10);
  doc.text("CLASSIFICATION: UNCLASSIFIED // DEMO USE ONLY", W - M, 10, {
    align: "right",
  });

  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  setText(C.cyan);
  doc.text("TRAFFIC INTELLIGENCE REPORT", M, 25);

  doc.setFont("courier", "normal");
  doc.setFontSize(8);
  setText(C.inverse);
  doc.text(`AREA OF OPERATIONS: ${cityLabel.toUpperCase()}`, M, 34);
  doc.text(`DTG: ${timestamp}`, M, 41);

  doc.setFont("courier", "bold");
  doc.setFontSize(8);
  setText(C.cyanSoft);
  doc.text(`REPORT ID: TOS-${reportId}`, W - M, 41, { align: "right" });

  setDraw(C.cyan);
  doc.setLineWidth(0.35);
  doc.line(M, 48, W - M, 48);

  y = 58;

  // ─────────────────────────────────────────────────────────────
  // KPI Cards
  // ─────────────────────────────────────────────────────────────
  const avgSpeed = stats.avgSpeed ?? stats.avg_speed ?? "--";
  const segmentCount = stats.segments ?? segments.length ?? 0;
  const jamCount =
    stats.jams ??
    segments.filter((s) => Number(s.congestion_level ?? 0) >= 3).length ??
    0;

  const kpis = [
    ["SEGMENTS", segmentCount],
    ["AVG SPEED", `${avgSpeed} km/h`],
    ["ACTIVE JAMS", jamCount],
    ["WEATHER", weatherFactor > 1.05 ? "ADVERSE" : "NOMINAL"],
  ];

  const cardGap = 3;
  const cardW = (CONTENT_W - cardGap * 3) / 4;
  const cardH = 22;

  kpis.forEach(([label, value], i) => {
    const x = M + i * (cardW + cardGap);

    drawPanel(x, y, cardW, cardH, C.card, C.borderDark);

    doc.setFont("courier", "bold");
    doc.setFontSize(6.7);
    setText(C.cyanSoft);
    doc.text(String(label), x + 4, y + 7);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(13);
    setText(C.inverse);

    const valueColor =
      label === "ACTIVE JAMS" && Number(value) > 0
        ? C.danger
        : label === "WEATHER" && value === "ADVERSE"
        ? C.warning
        : C.inverse;

    setText(valueColor);
    doc.text(String(value), x + 4, y + 16);
  });

  y += cardH + 14;

  // ─────────────────────────────────────────────────────────────
  // ARIA Assessment Panel
  // ─────────────────────────────────────────────────────────────
  drawSectionTitle("ARIA Tactical Assessment");

  const assessmentStartY = y;
  drawPanel(M, y - 5, CONTENT_W, 56, C.panel, C.border);

  doc.setFont("courier", "bold");
  doc.setFontSize(7);
  setText(C.cyanMuted);
  doc.text("ADAPTIVE ROUTE INTELLIGENCE ANALYST", M + 5, y + 2);

  y += 10;

  drawParagraph(reportText, {
    x: M + 5,
    width: CONTENT_W - 10,
    font: "helvetica",
    style: "normal",
    size: 9,
    lineHeight: 4.6,
    color: C.text,
    paragraphGap: 2,
  });

  // If the content exceeded the intended panel, that's okay; continue.
  y = Math.max(y, assessmentStartY + 60);

  // ─────────────────────────────────────────────────────────────
  // Mission Route Summary, if route exists
  // ─────────────────────────────────────────────────────────────
  if (route) {
    addPageIfNeeded(42);
    drawSectionTitle("Mission Route Summary");

    drawPanel(M, y - 4, CONTENT_W, 30, C.panel, C.border);

    doc.setFont("courier", "bold");
    doc.setFontSize(7);
    setText(C.muted);
    doc.text("ACTIVE ROUTE", M + 5, y + 3);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    setText(C.text);

    const origin = route.origin || route.origin_name || "Origin";
    const dest = route.dest || route.destination || route.dest_name || "Destination";
    doc.text(`${origin}  →  ${dest}`, M + 5, y + 13);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(8.5);
    setText(C.muted);

    const routeStats = [
      `Segments: ${route.segment_count ?? route.segments?.length ?? "--"}`,
      `Distance: ${
        route.distance_km
          ? `${route.distance_km} km`
          : route.total_distance_m
          ? `${(route.total_distance_m / 1000).toFixed(2)} km`
          : "--"
      }`,
      `ETA: ${route.eta_min ? `${route.eta_min} min` : "--"}`,
      `Delay Risk: ${route.delay_risk ? `${Math.round(route.delay_risk * 100)}%` : "--"}`,
    ];

    doc.text(routeStats.join("   |   "), M + 5, y + 23);

    y += 38;
  }

  // ─────────────────────────────────────────────────────────────
  // Segment Telemetry Table
  // ─────────────────────────────────────────────────────────────
  addPageIfNeeded(60);
  drawSectionTitle("Segment Telemetry Snapshot");

  const tableX = M;
  const tableW = CONTENT_W;
  const headerH = 8;
  const rowH = 7.4;

  const col = {
    segment: tableX + 4,
    speed: tableX + 88,
    density: tableX + 122,
    status: tableX + 157,
  };

  // Header row
  setFill(C.header);
  doc.rect(tableX, y - 4, tableW, headerH, "F");

  doc.setFont("courier", "bold");
  doc.setFontSize(7);
  setText(C.cyanSoft);
  doc.text("SEGMENT", col.segment, y + 1);
  doc.text("SPEED", col.speed, y + 1);
  doc.text("DENSITY", col.density, y + 1);
  doc.text("STATUS", col.status, y + 1);

  y += headerH;

  const visibleSegments = segments.slice(0, 24);

  visibleSegments.forEach((seg, idx) => {
    addPageIfNeeded(rowH + 8);

    // Redraw table header on new pages if near top after page break
    if (y < 35) {
      setFill(C.header);
      doc.rect(tableX, y - 4, tableW, headerH, "F");

      doc.setFont("courier", "bold");
      doc.setFontSize(7);
      setText(C.cyanSoft);
      doc.text("SEGMENT", col.segment, y + 1);
      doc.text("SPEED", col.speed, y + 1);
      doc.text("DENSITY", col.density, y + 1);
      doc.text("STATUS", col.status, y + 1);

      y += headerH;
    }

    const rowBg = idx % 2 === 0 ? [255, 255, 255] : [238, 245, 248];
    setFill(rowBg);
    doc.rect(tableX, y - 4, tableW, rowH, "F");

    setDraw(C.border);
    doc.setLineWidth(0.1);
    doc.line(tableX, y + rowH - 4, tableX + tableW, y + rowH - 4);

    const level = Number(seg.congestion_level ?? 0);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    setText(C.text);

    const name = String(seg.name || "Unnamed Road").slice(0, 38);
    const speed = Number(seg.speed_v ?? 0).toFixed(1);
    const density = Number(seg.density_k ?? 0).toFixed(1);

    doc.text(name, col.segment, y + 1);
    doc.text(`${speed}`, col.speed, y + 1);
    doc.text(`${density}`, col.density, y + 1);

    doc.setFont("helvetica", "bold");
    setText(statusColor(level));
    doc.text(statusLabel(level), col.status, y + 1);

    y += rowH;
  });

  if (segments.length > visibleSegments.length) {
    y += 4;
    doc.setFont("helvetica", "italic");
    doc.setFontSize(8);
    setText(C.muted);
    doc.text(
      `Showing first ${visibleSegments.length} of ${segments.length} monitored segments.`,
      M,
      y
    );
    y += 8;
  }

  // ─────────────────────────────────────────────────────────────
  // Operational Notes
  // ─────────────────────────────────────────────────────────────
  addPageIfNeeded(36);
  y += 8;
  drawSectionTitle("Operational Notes");

  drawPanel(M, y - 4, CONTENT_W, 26, C.panel, C.border);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  setText(C.text);

  const notes =
    "This report is generated for demonstration and operational simulation purposes. " +
    "TrafficOS combines route telemetry, congestion scoring, weather modifiers, and ARIA-generated tactical summaries. " +
    "Outputs should be interpreted as decision-support intelligence rather than absolute traffic ground truth.";

  const noteLines = doc.splitTextToSize(notes, CONTENT_W - 10);
  noteLines.forEach((line) => {
    doc.text(line, M + 5, y + 3);
    y += 4.5;
  });

  // ─────────────────────────────────────────────────────────────
  // Footer for all pages
  // ─────────────────────────────────────────────────────────────
  const pageCount = doc.getNumberOfPages();

  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);

    setFill(C.header);
    doc.rect(0, 285, W, 12, "F");

    doc.setFont("courier", "normal");
    doc.setFontSize(6.5);
    setText(C.cyanMuted);

    doc.text(`TRAFFICOS · TOS-${reportId} · ${dateStr} · PAGE ${i}/${pageCount}`, M, 292);

    doc.text(
      "GENERATED BY ARIA — ADAPTIVE ROUTE INTELLIGENCE ANALYST",
      W - M,
      292,
      { align: "right" }
    );
  }

  // ─────────────────────────────────────────────────────────────
  // Save
  // ─────────────────────────────────────────────────────────────
  doc.save(`TrafficOS_Intel_${safeCityFile}_${now.toISOString().slice(0, 10)}.pdf`);
}
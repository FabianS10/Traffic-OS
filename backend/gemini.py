"""
TrafficOS · Gemini Flash Intelligence Layer
Tactical traffic briefings, route analysis, city pulse.

Corrected version:
- Uses GEMINI_MODEL from .env, defaulting to gemini-2.5-flash
- Sends API key via x-goog-api-key header instead of URL query string
- Adds safer fallbacks for demo mode
- Keeps streaming responses for ARIA cockpit
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import httpx
import json
import os
import logging

router = APIRouter()
logger = logging.getLogger("trafficos.gemini")

# ── Gemini Configuration ────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

GEMINI_STREAM_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:streamGenerateContent"
)

GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)


SYSTEM_PROMPT = """You are ARIA — Adaptive Route Intelligence Analyst — the AI core of TrafficOS, 
a next-generation urban traffic management system. You speak like a calm, precise mission control 
operator. You analyze real traffic telemetry and deliver tactical briefings.

Rules:
- Be concise but impactful. No fluff.
- Use tactical language: "corridor", "threat", "vector", "nominal", "critical threshold"
- Reference actual data values you are given
- Structure responses with clear sections when doing full briefings
- For quick segment clicks: 2-3 sentences max, sharp and useful
- For route missions: full tactical analysis with threat assessment
- For city pulse: give a score 0-100 and narrative
- Always end route briefings with a recommended action
- You know both Fusagasugá, Colombia and San Francisco, CA — reference local context when relevant
"""


# ── Request Models ───────────────────────────────────────────────
class SegmentBriefRequest(BaseModel):
    segment_name: str
    speed_v: float
    density_k: float
    congestion_level: int
    flow_q: Optional[float] = None
    city: Optional[str] = "fusagasuga"
    horizon_min: Optional[int] = 0


class RouteMissionRequest(BaseModel):
    city: str
    origin_name: Optional[str] = "Origin"
    dest_name: Optional[str] = "Destination"
    segments: List[dict]
    total_distance_m: Optional[float] = None
    weather_factor: Optional[float] = 1.0
    horizon_min: Optional[int] = 0


class CityPulseRequest(BaseModel):
    city: str
    total_segments: int
    jam_count: int
    avg_speed: float
    weather_factor: float
    horizon_min: Optional[int] = 0


class PdfReportRequest(BaseModel):
    city: str
    segments: List[dict]
    route: Optional[dict] = None
    stats: dict
    weather_factor: float


# ── Helpers ──────────────────────────────────────────────────────
def get_city_label(city: Optional[str]) -> str:
    city_normalized = (city or "").lower()
    if city_normalized in ["fusagasuga", "fusagasugá"]:
        return "Fusagasugá, Colombia"
    if city_normalized in ["sf", "san_francisco", "san francisco"]:
        return "San Francisco, CA"
    return city or "Unknown City"


def sse_text(text: str) -> str:
    return f"data: {json.dumps({'text': text})}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


async def fallback_stream(message: str):
    """
    Streams a fallback message character-by-character so the UI still feels alive.
    """
    for char in message:
        yield sse_text(char)
    yield sse_done()


def extract_gemini_text(data: dict, default: str = "Intelligence report unavailable.") -> str:
    """
    Safely extracts text from Gemini response JSON.
    """
    try:
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", default)
        )
    except Exception:
        return default


async def stream_gemini(prompt: str):
    """
    Stream Gemini response token by token using SSE.
    """
    if not GEMINI_API_KEY:
        return fallback_stream(
            "⚠ ARIA OFFLINE — GEMINI_API_KEY not configured. Cached TrafficOS briefing active."
        )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\n\n{prompt}"
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 600,
            "topP": 0.9,
        },
    }

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    "POST",
                    f"{GEMINI_STREAM_URL}?alt=sse",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": GEMINI_API_KEY,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        logger.warning(
                            "Gemini stream failed with status %s using model %s",
                            resp.status_code,
                            GEMINI_MODEL,
                        )
                        yield sse_text(
                            f"⚠ ARIA fallback active — Gemini returned {resp.status_code}. "
                            "Cached TrafficOS briefing online."
                        )
                        yield sse_done()
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        raw = line[6:].strip()

                        if raw == "[DONE]":
                            yield sse_done()
                            return

                        try:
                            chunk = json.loads(raw)
                            text = extract_gemini_text(chunk, default="")
                            if text:
                                yield sse_text(text)
                        except Exception:
                            continue

                    yield sse_done()

        except httpx.TimeoutException:
            logger.exception("Gemini request timed out.")
            yield sse_text("⚠ ARIA timeout — cached TrafficOS briefing active.")
            yield sse_done()

        except Exception:
            logger.exception("Gemini stream crashed.")
            yield sse_text("⚠ ARIA fallback — cached TrafficOS briefing active.")
            yield sse_done()

    return generate()


async def generate_gemini_text(prompt: str, max_tokens: int = 800, temperature: float = 0.6) -> str:
    """
    Non-streaming Gemini call for PDF reports and structured backend tasks.
    """
    if not GEMINI_API_KEY:
        return "ARIA OFFLINE — GEMINI_API_KEY not configured. Cached report unavailable."

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\n\n{prompt}"
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GEMINI_GENERATE_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": GEMINI_API_KEY,
                },
            )

        if resp.status_code != 200:
            logger.warning(
                "Gemini generateContent failed with status %s using model %s",
                resp.status_code,
                GEMINI_MODEL,
            )
            return (
                f"ARIA fallback active — Gemini returned {resp.status_code}. "
                "TrafficOS generated a cached intelligence report."
            )

        data = resp.json()
        return extract_gemini_text(data)

    except httpx.TimeoutException:
        logger.exception("Gemini PDF report request timed out.")
        return "ARIA timeout — cached TrafficOS intelligence report active."

    except Exception:
        logger.exception("Gemini PDF report request crashed.")
        return "ARIA fallback — cached TrafficOS intelligence report active."


# ── Routes ───────────────────────────────────────────────────────
@router.post("/segment-brief")
async def segment_brief(req: SegmentBriefRequest):
    """
    Quick tactical brief when user clicks a segment.
    """
    congestion_labels = {
        0: "FREE FLOW",
        1: "LIGHT",
        2: "MODERATE",
        3: "HEAVY",
        4: "JAM",
    }

    city_label = get_city_label(req.city)

    flow_text = f"{req.flow_q:.0f}" if req.flow_q is not None else "N/A"
    horizon_text = "LIVE" if req.horizon_min == 0 else f"T+{req.horizon_min}min projection"

    prompt = f"""Quick tactical brief for this traffic segment in {city_label}:

Segment: {req.segment_name}
Status: {congestion_labels.get(req.congestion_level, "UNKNOWN")} (Level {req.congestion_level}/4)
Speed: {req.speed_v:.1f} km/h
Density: {req.density_k:.1f} veh/km
Flow: {flow_text} veh/hr
Time horizon: {horizon_text}

Give a 2-3 sentence tactical assessment. Be sharp."""

    gen = await stream_gemini(prompt)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/route-mission")
async def route_mission(req: RouteMissionRequest):
    """
    Full mission briefing after A* route execution.
    """
    city_label = get_city_label(req.city)

    jam_segs = [
        s for s in req.segments
        if s.get("congestion_level", 0) >= 3
    ]

    avg_speed = (
        sum(s.get("speed_v", 30) for s in req.segments)
        / max(len(req.segments), 1)
    )

    seg_summary = "\n".join(
        [
            f"  • {s.get('name', 'Unknown')}: "
            f"{s.get('speed_v', 0):.0f} km/h, "
            f"L{s.get('congestion_level', 0)}"
            for s in req.segments[:12]
        ]
    )

    weather_text = (
        f"ADVERSE (×{req.weather_factor:.2f})"
        if req.weather_factor and req.weather_factor > 1.05
        else "NOMINAL"
    )

    horizon_text = "LIVE" if req.horizon_min == 0 else f"T+{req.horizon_min}min"

    distance_text = (
        f"{req.total_distance_m / 1000:.2f} km"
        if req.total_distance_m is not None
        else "N/A"
    )

    prompt = f"""MISSION BRIEFING — A* Route Analysis
City: {city_label}
Route: {req.origin_name} → {req.dest_name}
Segments traversed: {len(req.segments)}
Total distance: {distance_text}
Average corridor speed: {avg_speed:.1f} km/h
Critical segments (congestion ≥3): {len(jam_segs)}
Weather factor: {weather_text}
Time projection: {horizon_text}

Segment breakdown:
{seg_summary}

Deliver a full tactical mission briefing with:
1. ROUTE STATUS (overall assessment)
2. THREAT VECTORS (specific bottlenecks)
3. ETA ESTIMATE (rough, based on avg speed and segment count)
4. RECOMMENDED ACTION

Keep it under 200 words. Sound like mission control."""

    gen = await stream_gemini(prompt)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/city-pulse")
async def city_pulse(req: CityPulseRequest):
    """
    Live city health score narrated by ARIA.
    """
    city_label = get_city_label(req.city)
    jam_pct = (req.jam_count / max(req.total_segments, 1)) * 100

    weather_text = "ADVERSE" if req.weather_factor > 1.05 else "NOMINAL"
    horizon_text = "LIVE" if req.horizon_min == 0 else f"T+{req.horizon_min}min projection"

    prompt = f"""CITY PULSE REPORT — {city_label}
Active segments: {req.total_segments}
Jam segments: {req.jam_count} ({jam_pct:.1f}% of network)
Network avg speed: {req.avg_speed:.1f} km/h
Weather modifier: {weather_text}
Time: {horizon_text}

First, output exactly this line: PULSE: [score]/100
Where score reflects overall traffic health. 100 means perfect flow. 0 means gridlock.

Then give a 3-sentence city-wide tactical narrative. Reference local landmarks or corridors if relevant."""

    gen = await stream_gemini(prompt)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/pdf-report")
async def generate_pdf_briefing(req: PdfReportRequest):
    """
    Generate full text for the PDF intel report.
    This endpoint returns text. Your PDF generator can consume report_text.
    """
    city_label = get_city_label(req.city)

    jam_count = sum(
        1 for s in req.segments
        if s.get("congestion_level", 0) >= 3
    )

    active_route_text = (
        f"ACTIVE MISSION ROUTE: "
        f"{req.route.get('origin', '?')} → "
        f"{req.route.get('dest', '?')} "
        f"({req.route.get('segment_count', 0)} segments)"
        if req.route
        else "NO ACTIVE ROUTE"
    )

    prompt = f"""Generate a formal TRAFFIC INTELLIGENCE REPORT for {city_label}.
Format it as a declassified operations document.

NETWORK STATUS:
- Total segments monitored: {req.stats.get("segments", 0)}
- Average speed: {req.stats.get("avg_speed", 0)} km/h
- Active jams: {jam_count}
- Weather factor: {req.weather_factor:.2f}

{active_route_text}

Write a 3-paragraph intelligence report with:
PARAGRAPH 1: Executive Summary (network health)
PARAGRAPH 2: Critical Threats (specific corridors at risk)
PARAGRAPH 3: Operational Recommendations

Use formal but tactical language. This will be printed as a PDF briefing document."""

    text = await generate_gemini_text(
        prompt,
        max_tokens=800,
        temperature=0.6,
    )

    return {
        "report_text": text,
        "city": city_label,
        "model": GEMINI_MODEL,
    }


@router.get("/aria-health")
async def aria_health():
    """
    Quick health check for the ARIA/Gemini layer.
    Does not expose the API key.
    """
    return {
        "service": "ARIA",
        "status": "configured" if bool(GEMINI_API_KEY) else "missing_api_key",
        "model": GEMINI_MODEL,
    }
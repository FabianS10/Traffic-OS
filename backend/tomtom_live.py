"""
TomTom live traffic adapter for TrafficOS.

Purpose:
- Fetch real TomTom Traffic Flow data from the backend.
- Never expose TOMTOM_API_KEY to the frontend.
- Generate dense live traffic samples for Fusagasugá and central San Francisco.
- Return both:
  1. GeoJSON FeatureCollection for Mapbox rendering
  2. segments[] for the TrafficOS sidebar/cards
"""

import os
import time
import asyncio
import hashlib
from typing import Any, Dict, List, Tuple

import httpx


# ── Secrets / Config ──────────────────────────────────────────────────────────

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()

CACHE_TTL_SECONDS = int(os.getenv("TOMTOM_CACHE_TTL_SECONDS", "60"))
TOMTOM_CONCURRENCY = int(os.getenv("TOMTOM_CONCURRENCY", "12"))

# Bigger = more TomTom calls. Keep sane for demo/quota.
MAX_POINTS = {
    "fusagasuga": int(os.getenv("TOMTOM_MAX_POINTS_FUSA", "90")),
    "san_francisco": int(os.getenv("TOMTOM_MAX_POINTS_SF", "90")),
}

_CACHE: Dict[str, Dict[str, Any]] = {}


# ── City Sampling Regions ─────────────────────────────────────────────────────
# Format: (lat_min, lat_max, lon_min, lon_max)

CITY_BBOX = {
    # Covers the main Fusagasugá urban area and surrounding corridors.
    "fusagasuga": {
        "bbox": (4.3180, 4.3535, -74.3880, -74.3380),
        "rows": 12,
        "cols": 12,
    },

    # Central SF region matching your screenshot:
    # Fillmore / Civic Center / SoMa / Mission / downtown area.
    "san_francisco": {
        "bbox": (37.7480, 37.7950, -122.4450, -122.3850),
        "rows": 12,
        "cols": 12,
    },
}


# Strategic anchor points so important roads are sampled even if grid misses them.
ANCHOR_POINTS: Dict[str, List[Tuple[float, float, str]]] = {
    "fusagasuga": [
        (4.3379, -74.3649, "Calle 18"),
        (4.3358, -74.3671, "Carrera 7"),
        (4.3441, -74.3705, "Avenida Las Palmas"),
        (4.3319, -74.3668, "Transversal 12"),
        (4.3291, -74.3710, "Fusagasugá - Silvania - Soacha"),
        (4.3402, -74.3595, "Comuna Centro"),
        (4.3428, -74.3620, "Avenida Panamericana"),
        (4.3336, -74.3615, "Carrera 6"),
        (4.3367, -74.3587, "Calle 7A"),
        (4.3395, -74.3568, "Sector Santander"),
        (4.3272, -74.3679, "Hospital San Rafael Corridor"),
        (4.3348, -74.3745, "Universidad de Cundinamarca Corridor"),
        (4.3457, -74.3547, "Comuna Norte"),
        (4.3298, -74.3496, "La Florida"),
        (4.3215, -74.3607, "La Alejandría"),
    ],
    "san_francisco": [
        (37.7749, -122.4194, "Market Street"),
        (37.7840, -122.4075, "Union Square"),
        (37.7890, -122.4010, "Financial District"),
        (37.7812, -122.4112, "Civic Center"),
        (37.7600, -122.4148, "Mission District"),
        (37.7680, -122.4490, "Haight-Ashbury"),
        (37.7765, -122.3910, "Mission Bay"),
        (37.7833, -122.4167, "Tenderloin"),
        (37.7750, -122.4376, "Fillmore"),
        (37.7694, -122.4269, "Duboce Triangle"),
        (37.7642, -122.4320, "Castro"),
        (37.7666, -122.4095, "Potrero / Mission"),
        (37.7822, -122.3930, "SoMa East"),
        (37.7898, -122.4210, "Nob Hill South"),
        (37.7528, -122.4180, "Mission South"),
    ],
}


# ── Utility Functions ─────────────────────────────────────────────────────────

def normalize_city(city: str) -> str:
    value = (city or "fusagasuga").lower().strip()

    if value in {"sf", "san francisco", "san-francisco", "san_francisco"}:
        return "san_francisco"

    if value in {"fusa", "fusagasuga", "fusagasugá"}:
        return "fusagasuga"

    return "fusagasuga"


def generate_grid_points(city_key: str) -> List[Tuple[float, float, str]]:
    """
    Generate a dense lat/lon grid across the selected city bounding box.
    TomTom returns the nearest traffic flow segment for each sampled point.
    """
    cfg = CITY_BBOX[city_key]
    lat_min, lat_max, lon_min, lon_max = cfg["bbox"]
    rows = cfg["rows"]
    cols = cfg["cols"]

    points: List[Tuple[float, float, str]] = []

    for r in range(rows):
        lat = lat_min + (lat_max - lat_min) * (r / max(rows - 1, 1))

        for c in range(cols):
            lon = lon_min + (lon_max - lon_min) * (c / max(cols - 1, 1))
            points.append((lat, lon, f"{city_key.replace('_', ' ').title()} Grid {r + 1}-{c + 1}"))

    return points


def get_city_points(city_key: str) -> List[Tuple[float, float, str]]:
    """
    Combine anchors + generated grid, dedupe nearby identical points, and cap count.
    """
    raw_points = ANCHOR_POINTS.get(city_key, []) + generate_grid_points(city_key)

    seen = set()
    unique: List[Tuple[float, float, str]] = []

    for lat, lon, name in raw_points:
        # Round to avoid duplicate near-identical samples.
        key = (round(lat, 5), round(lon, 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append((lat, lon, name))

    return unique[:MAX_POINTS[city_key]]


def congestion_from_speed(current_speed: float, free_flow_speed: float) -> int:
    """
    Convert real TomTom speed degradation into TrafficOS congestion tier.
    """
    if free_flow_speed <= 0:
        return 0

    ratio = current_speed / free_flow_speed

    if ratio >= 0.85:
        return 0  # Free flow
    if ratio >= 0.65:
        return 1  # Light
    if ratio >= 0.45:
        return 2  # Moderate
    if ratio >= 0.25:
        return 3  # Heavy
    return 4      # Jam


def status_from_level(level: int) -> str:
    return ["Free Flow", "Light", "Moderate", "Heavy", "Jam"][max(0, min(level, 4))]


def estimate_density_from_speed(
    current_speed: float,
    free_flow_speed: float,
    jam_density: float = 120.0,
) -> float:
    """
    TomTom gives speed/travel-time. TrafficOS estimates density through
    speed degradation using a Greenshields-style relationship.
    """
    if free_flow_speed <= 0:
        return 0.0

    density = jam_density * (1.0 - (current_speed / free_flow_speed))
    return max(0.0, min(jam_density, density))


def geometry_signature(coordinates: List[List[float]]) -> str:
    """
    Deduplicate TomTom segments by compressed coordinate signature.
    """
    if not coordinates:
        return ""

    compressed = [
        [round(lon, 4), round(lat, 4)]
        for lon, lat in coordinates[:: max(1, len(coordinates) // 5)]
    ]

    raw = str(compressed).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


# ── TomTom Calls ──────────────────────────────────────────────────────────────

async def fetch_flow_segment(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    lat: float,
    lon: float,
    fallback_name: str,
    idx: int,
) -> Dict[str, Any] | None:
    """
    Calls TomTom Flow Segment Data for one sampled point.
    """
    async with semaphore:
        url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

        params = {
            "point": f"{lat},{lon}",
            "unit": "KMPH",
            "key": TOMTOM_API_KEY,
        }

        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return {
                "error": str(e),
                "fallback_name": fallback_name,
                "lat": lat,
                "lon": lon,
            }

        fsd = data.get("flowSegmentData", {})

        current_speed = float(fsd.get("currentSpeed", 0) or 0)
        free_flow_speed = float(fsd.get("freeFlowSpeed", current_speed or 1) or 1)
        current_travel_time = float(fsd.get("currentTravelTime", 0) or 0)
        free_flow_travel_time = float(fsd.get("freeFlowTravelTime", 0) or 0)
        confidence = float(fsd.get("confidence", 0) or 0)
        road_closure = bool(fsd.get("roadClosure", False))

        coords_raw = fsd.get("coordinates", {}).get("coordinate", [])

        coordinates: List[List[float]] = []

        for c in coords_raw:
            try:
                coordinates.append([float(c["longitude"]), float(c["latitude"])])
            except Exception:
                continue

        # If TomTom does not return a polyline, draw a tiny local line.
        if len(coordinates) < 2:
            coordinates = [
                [lon - 0.00045, lat - 0.00025],
                [lon + 0.00045, lat + 0.00025],
            ]

        level = congestion_from_speed(current_speed, free_flow_speed)

        if road_closure:
            level = 4

        density_k = estimate_density_from_speed(current_speed, free_flow_speed)
        flow_q = density_k * current_speed

        segment = {
            "id": idx,
            "name": fallback_name,
            "speed_v": round(current_speed, 1),
            "free_flow_speed": round(free_flow_speed, 1),
            "density_k": round(density_k, 1),
            "flow_q": round(flow_q, 0),
            "congestion_level": level,
            "status": status_from_level(level),
            "confidence": confidence,
            "current_travel_time": current_travel_time,
            "free_flow_travel_time": free_flow_travel_time,
            "road_closure": road_closure,
            "geometry": coordinates,
            "source": "tomtom_live",
            "is_real_traffic": True,
        }

        feature = {
            "type": "Feature",
            "properties": segment,
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
        }

        return {
            "signature": geometry_signature(coordinates),
            "segment": segment,
            "feature": feature,
        }


async def get_tomtom_live_map_data(city: str = "fusagasuga") -> Dict[str, Any]:
    """
    Fetch real TomTom traffic flow for a dense city sample.

    This is real TomTom traffic data, not simulated traffic.
    """
    city_key = normalize_city(city)
    points = get_city_points(city_key)

    cache_key = f"tomtom-live:{city_key}:{len(points)}"
    now = time.time()

    cached = _CACHE.get(cache_key)
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["payload"]

    if not TOMTOM_API_KEY:
        return {
            "city": city_key,
            "mode": "tomtom-live-missing-key",
            "is_real_traffic": False,
            "error": "TOMTOM_API_KEY missing on backend.",
            "type": "FeatureCollection",
            "features": [],
            "segments": [],
        }

    semaphore = asyncio.Semaphore(TOMTOM_CONCURRENCY)

    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = [
            fetch_flow_segment(
                client=client,
                semaphore=semaphore,
                lat=lat,
                lon=lon,
                fallback_name=name,
                idx=idx + 1,
            )
            for idx, (lat, lon, name) in enumerate(points)
        ]

        results = await asyncio.gather(*tasks)

    segments = []
    features = []
    errors = []
    seen_signatures = set()

    for item in results:
        if not item:
            continue

        if "error" in item:
            errors.append(item)
            continue

        signature = item.get("signature", "")

        # Deduplicate repeated TomTom road fragments returned by nearby samples.
        if signature and signature in seen_signatures:
            continue

        seen_signatures.add(signature)

        segment = item["segment"]
        segment["id"] = len(segments) + 1

        feature = item["feature"]
        feature["properties"]["id"] = segment["id"]

        segments.append(segment)
        features.append(feature)

    avg_speed = (
        round(sum(s["speed_v"] for s in segments) / len(segments), 1)
        if segments
        else 0
    )

    jam_count = sum(1 for s in segments if s["congestion_level"] >= 3)

    payload = {
        "city": city_key,
        "mode": "tomtom-live-dense",
        "source": "TomTom Traffic Flow Segment Data",
        "is_real_traffic": True,
        "sample_points_requested": len(points),
        "type": "FeatureCollection",
        "features": features,
        "segments": segments,
        "stats": {
            "segments": len(segments),
            "avg_speed": avg_speed,
            "jams": jam_count,
            "errors": len(errors),
        },
        "errors": errors[:5],
    }

    _CACHE[cache_key] = {
        "timestamp": now,
        "payload": payload,
    }

    return payload
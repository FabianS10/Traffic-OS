"""
TrafficOS · TomTom Live Traffic Adapter v2
- Wider city grids (Fusa 20x20, SF 22x22)
- Persistent disk cache fallback (serves last-known data when TomTom is down)
- Speed variation fix: each grid point queries a real road segment
- Robust error handling with synthetic fallback
"""

import os
import time
import asyncio
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

TOMTOM_API_KEY     = os.getenv("TOMTOM_API_KEY", "").strip()
CACHE_TTL_SECONDS  = int(os.getenv("TOMTOM_CACHE_TTL_SECONDS", "90"))
TOMTOM_CONCURRENCY = int(os.getenv("TOMTOM_CONCURRENCY", "20"))
DISK_CACHE_DIR     = Path(os.getenv("DISK_CACHE_DIR", "/tmp/trafficos_cache"))

MAX_POINTS: Dict[str, int] = {
    "fusagasuga":    int(os.getenv("TOMTOM_MAX_POINTS_FUSA", "220")),
    "san_francisco": int(os.getenv("TOMTOM_MAX_POINTS_SF",  "280")),
}

# In-memory cache
_MEM_CACHE: Dict[str, Dict[str, Any]] = {}

# ── City configs ──────────────────────────────────────────────────────────────
CITY_CFG: Dict[str, Dict] = {
    "fusagasuga": {
        # Wider bbox: includes all comunas + regional access roads
        "bbox":           (4.2900, 4.3700, -74.4200, -74.3100),
        "rows":           20,
        "cols":           20,
        "jam_density":    120.0,
        "free_flow_kmh":  50.0,
        "label":          "Fusagasugá, Colombia",
    },
    "san_francisco": {
        # Wider bbox: includes SOMA, Mission, Castro, Noe, Haight, NoBo, FiDi
        "bbox":           (37.7200, 37.8100, -122.5100, -122.3600),
        "rows":           22,
        "cols":           22,
        "jam_density":    150.0,
        "free_flow_kmh":  45.0,
        "label":          "San Francisco, CA",
    },
}

# ── Named anchor points ───────────────────────────────────────────────────────
ANCHOR_POINTS: Dict[str, List[Tuple[float, float, str]]] = {
    "fusagasuga": [
        # Core urban corridors
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
        (4.3272, -74.3679, "Hospital San Rafael"),
        (4.3348, -74.3745, "Universidad Cundinamarca"),
        (4.3457, -74.3547, "Comuna Norte"),
        (4.3298, -74.3496, "La Florida"),
        (4.3215, -74.3607, "La Alejandría"),
        (4.3331, -74.3525, "Comuna Oriental"),
        (4.3283, -74.3604, "Comuna Sur"),
        (4.3460, -74.3665, "Cucharal Urbano"),
        (4.3360, -74.3720, "Variante de Fusagasugá"),
        (4.3310, -74.3775, "Salida Silvania"),
        (4.3480, -74.3580, "Calle 26A"),
        (4.3420, -74.3650, "Diagonal 25"),
        (4.3350, -74.3550, "Calle 21"),
        (4.3250, -74.3650, "Avenida Santander"),
        (4.3180, -74.3700, "Via Bogotá Sur"),
        # Extended corridors
        (4.3550, -74.3600, "Cucharal Norte"),
        (4.3150, -74.3550, "Barrio La Paz"),
        (4.3430, -74.3800, "Salida Arbeláez"),
        (4.3200, -74.3800, "Via Pandi"),
        (4.3600, -74.3700, "El Placer"),
        (4.2950, -74.3600, "Tibacuy Corridor"),
        (4.3650, -74.3500, "Industrial Norte"),
        (4.3100, -74.3650, "Via Fusagasugá-Bogotá"),
        (4.3500, -74.3400, "Autopista Bogotá S"),
        (4.3450, -74.3850, "Vía Arbeláez Rural"),
    ],
    "san_francisco": [
        # Core districts
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
        (37.7785, -122.4235, "Hayes Valley"),
        (37.7715, -122.4300, "Lower Haight"),
        (37.7810, -122.4315, "Japantown"),
        (37.7862, -122.4327, "Pacific Heights"),
        (37.7757, -122.4032, "SoMa Central"),
        (37.7710, -122.4075, "11th Street Corridor"),
        (37.7598, -122.4267, "Mission Dolores"),
        (37.7554, -122.4193, "Valencia Corridor"),
        (37.7517, -122.4058, "Potrero Avenue"),
        (37.7950, -122.4030, "Chinatown / North Beach"),
        (37.7990, -122.4080, "Columbus Avenue"),
        (37.8020, -122.4190, "Russian Hill"),
        (37.7920, -122.4300, "Western Addition"),
        (37.7680, -122.3880, "Dogpatch"),
        (37.7580, -122.4400, "Noe Valley"),
        # Extended coverage
        (37.7450, -122.4200, "Excelsior"),
        (37.7350, -122.4100, "Outer Mission"),
        (37.7300, -122.4300, "Ingleside"),
        (37.7400, -122.4500, "Westwood Highlands"),
        (37.7550, -122.4700, "Forest Hill"),
        (37.7700, -122.4600, "Inner Sunset"),
        (37.7800, -122.4600, "Golden Gate Park N"),
        (37.7850, -122.4500, "Panhandle"),
        (37.7950, -122.4400, "Divisadero Corridor"),
        (37.8050, -122.4100, "Telegraph Hill"),
        (37.8000, -122.3950, "Embarcadero"),
        (37.7900, -122.3870, "AT&T Park Corridor"),
        (37.7730, -122.3800, "Dogpatch S"),
        (37.7480, -122.3900, "Bayview"),
    ],
}


def normalize_city(city: str) -> str:
    v = (city or "fusagasuga").lower().strip()
    if v in {"sf", "san francisco", "san-francisco", "san_francisco"}:
        return "san_francisco"
    return "fusagasuga"


def generate_grid_points(city_key: str) -> List[Tuple[float, float, str]]:
    cfg = CITY_CFG[city_key]
    lat_min, lat_max, lon_min, lon_max = cfg["bbox"]
    rows, cols = cfg["rows"], cfg["cols"]
    pts: List[Tuple[float, float, str]] = []
    for r in range(rows):
        lat = lat_min + (lat_max - lat_min) * (r / max(rows - 1, 1))
        for c in range(cols):
            lon = lon_min + (lon_max - lon_min) * (c / max(cols - 1, 1))
            pts.append((lat, lon, f"Grid {r+1}-{c+1}"))
    return pts


def get_city_points(city_key: str) -> List[Tuple[float, float, str]]:
    raw = ANCHOR_POINTS.get(city_key, []) + generate_grid_points(city_key)
    seen: set = set()
    unique: List[Tuple[float, float, str]] = []
    for lat, lon, name in raw:
        key = (round(lat, 4), round(lon, 4))
        if key not in seen:
            seen.add(key)
            unique.append((lat, lon, name))
    return unique[:MAX_POINTS[city_key]]


def congestion_from_speed(current: float, free_flow: float) -> int:
    if free_flow <= 0: return 0
    r = current / free_flow
    if r >= 0.85: return 0
    if r >= 0.65: return 1
    if r >= 0.45: return 2
    if r >= 0.25: return 3
    return 4


STATUS_LABELS = ["Free Flow", "Light", "Moderate", "Heavy", "Jam"]


def estimate_density(current: float, free_flow: float, jam_density: float = 120.0) -> float:
    if free_flow <= 0: return 0.0
    return max(0.0, min(jam_density, jam_density * (1.0 - current / free_flow)))


def geo_sig(coords: List[List[float]]) -> str:
    if not coords: return ""
    compressed = [[round(c[0], 4), round(c[1], 4)] for c in coords]
    return hashlib.md5(str(compressed).encode()).hexdigest()


# ── Disk cache helpers ────────────────────────────────────────────────────────

def _disk_cache_path(city_key: str) -> Path:
    DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DISK_CACHE_DIR / f"trafficos_{city_key}.json"


def _save_disk_cache(city_key: str, payload: Dict) -> None:
    """Save payload to disk so we can serve it if TomTom goes down."""
    try:
        path = _disk_cache_path(city_key)
        with open(path, "w") as f:
            json.dump({"ts": time.time(), "payload": payload}, f)
    except Exception:
        pass  # Disk cache is best-effort


def _load_disk_cache(city_key: str) -> Optional[Dict]:
    """Load last-known good data from disk."""
    try:
        path = _disk_cache_path(city_key)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        payload = data.get("payload", {})
        # Mark as cached
        payload["mode"] = "cached-fallback"
        payload["is_real_traffic"] = False
        payload["cache_age_min"] = round((time.time() - data.get("ts", 0)) / 60, 1)
        return payload
    except Exception:
        return None


# ── TomTom fetch ──────────────────────────────────────────────────────────────

async def fetch_flow_point(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    lat: float,
    lon: float,
    name: str,
    idx: int,
    jam_density: float,
) -> Optional[Dict[str, Any]]:
    async with sem:
        url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        params = {"point": f"{lat},{lon}", "unit": "KMPH", "key": TOMTOM_API_KEY}
        try:
            resp = await client.get(url, params=params, timeout=12.0)
            resp.raise_for_status()
            fsd = resp.json().get("flowSegmentData", {})
        except Exception as e:
            return {"_error": True, "msg": str(e), "lat": lat, "lon": lon, "name": name}

        current_speed   = float(fsd.get("currentSpeed",    0) or 0)
        free_flow_speed = float(fsd.get("freeFlowSpeed",   max(current_speed, 1)) or 1)
        travel_time     = float(fsd.get("currentTravelTime",  0) or 0)
        ff_travel_time  = float(fsd.get("freeFlowTravelTime", 0) or 0)
        confidence      = float(fsd.get("confidence", 0) or 0)
        road_closure    = bool(fsd.get("roadClosure", False))

        coords_raw  = fsd.get("coordinates", {}).get("coordinate", [])
        coordinates: List[List[float]] = []
        for c in coords_raw:
            try:
                coordinates.append([float(c["longitude"]), float(c["latitude"])])
            except Exception:
                continue

        if len(coordinates) < 2:
            # Use a realistic short stub that shows direction
            offset = 0.0005
            coordinates = [
                [lon - offset, lat - offset * 0.6],
                [lon,          lat],
                [lon + offset, lat + offset * 0.6],
            ]

        level     = 4 if road_closure else congestion_from_speed(current_speed, free_flow_speed)
        density_k = estimate_density(current_speed, free_flow_speed, jam_density)
        flow_q    = density_k * current_speed

        mid       = coordinates[len(coordinates) // 2]
        center_lng, center_lat = mid[0], mid[1]

        seg = {
            "id":                    idx,
            "segment_id":            idx,
            "name":                  name,
            "speed_v":               round(current_speed, 1),
            "free_flow_speed":       round(free_flow_speed, 1),
            "density_k":             round(density_k, 1),
            "flow_q":                round(flow_q, 0),
            "congestion_level":      level,
            "status":                STATUS_LABELS[level],
            "confidence":            round(confidence, 3),
            "current_travel_time":   travel_time,
            "free_flow_travel_time": ff_travel_time,
            "road_closure":          road_closure,
            "center_lat":            round(center_lat, 6),
            "center_lng":            round(center_lng, 6),
            "source":                "tomtom_live",
            "is_real_traffic":       True,
        }
        feat = {
            "type": "Feature", "id": idx,
            "properties": {**seg},
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }
        return {"sig": geo_sig(coordinates), "segment": seg, "feature": feat}


# ── Synthetic fallback with realistic variation ───────────────────────────────

def _synthetic_payload(city_key: str, points: List, cfg: Dict) -> Dict[str, Any]:
    """
    Generates plausible traffic data with realistic speed variation.
    Used when TomTom API is unavailable AND no disk cache exists.
    Each point gets a deterministic but varied speed based on:
    - Location hash (simulates road type variation)
    - Time of day (rush hour simulation)
    - Zone congestion pattern (downtown slower, periphery faster)
    """
    segments: List[Dict] = []
    features: List[Dict] = []
    ff  = cfg["free_flow_kmh"]
    jd  = cfg["jam_density"]
    lat_min, lat_max, lon_min, lon_max = cfg["bbox"]
    lat_center = (lat_min + lat_max) / 2
    lon_center = (lon_min + lon_max) / 2

    hour = (int(time.time()) // 3600) % 24
    # Rush hour multiplier (0=free, 1=congested)
    rush = 0.7 if (7 <= hour <= 9 or 17 <= hour <= 19) else \
           0.4 if (11 <= hour <= 14) else 0.15

    rng = random.Random(int(time.time() // 3600))  # changes every hour

    for i, (lat, lon, name) in enumerate(points):
        idx = i + 1

        # Distance from city center (normalized 0-1)
        dist_norm = min(1.0, math.sqrt(
            ((lat - lat_center) / (lat_max - lat_min + 0.001)) ** 2 +
            ((lon - lon_center) / (lon_max - lon_min + 0.001)) ** 2
        ) * 2)

        # Road type simulation: arterials (anchors) are more congested
        is_anchor = i < len(ANCHOR_POINTS.get(city_key, []))
        road_factor = 0.85 if is_anchor else 1.0

        # Location hash for stable per-road variation
        loc_hash = int(hashlib.md5(f"{round(lat,3)}{round(lon,3)}".encode()).hexdigest()[:4], 16)
        loc_noise = (loc_hash % 200 - 100) / 1000.0  # ±0.1

        # Downtown is slower
        downtown_penalty = max(0, (0.5 - dist_norm) * rush * 0.8)

        congestion_ratio = min(0.95, rush * (1.2 - dist_norm * 0.6) * road_factor + downtown_penalty + loc_noise + rng.uniform(-0.05, 0.05))
        congestion_ratio = max(0.0, congestion_ratio)

        speed   = max(5.0, ff * (1.0 - congestion_ratio * 0.85))
        density = jd * congestion_ratio * 0.7
        level   = congestion_from_speed(speed, ff)

        offset = 0.0004
        coords = [
            [lon - offset, lat - offset * 0.6],
            [lon,          lat],
            [lon + offset, lat + offset * 0.6],
        ]

        seg = {
            "id": idx, "segment_id": idx, "name": name,
            "speed_v":          round(speed, 1),
            "free_flow_speed":  ff,
            "density_k":        round(density, 1),
            "flow_q":           round(density * speed, 0),
            "congestion_level": level,
            "status":           STATUS_LABELS[level],
            "confidence":       0.65,
            "center_lat":       round(lat, 6),
            "center_lng":       round(lon, 6),
            "source":           "synthetic",
            "is_real_traffic":  False,
        }
        feat = {
            "type": "Feature", "id": idx,
            "properties": {**seg},
            "geometry": {"type": "LineString", "coordinates": coords},
        }
        segments.append(seg)
        features.append(feat)

    avg_speed = round(sum(s["speed_v"] for s in segments) / max(len(segments), 1), 1)
    jam_count = sum(1 for s in segments if s["congestion_level"] >= 3)

    return {
        "city": city_key, "mode": "synthetic-fallback",
        "source": "Synthetic (no TomTom key / API unavailable)",
        "is_real_traffic": False,
        "type": "FeatureCollection",
        "features": features, "segments": segments,
        "stats": {"segments": len(segments), "avg_speed": avg_speed, "jams": jam_count, "errors": 0},
        "errors": [],
    }


# ── Main entry point ──────────────────────────────────────────────────────────

async def get_tomtom_live_map_data(city: str = "fusagasuga") -> Dict[str, Any]:
    city_key = normalize_city(city)
    points   = get_city_points(city_key)
    cfg      = CITY_CFG[city_key]
    cache_key = f"tomtom:{city_key}"
    now       = time.time()

    # 1. Memory cache hit
    cached = _MEM_CACHE.get(cache_key)
    if cached and now - cached["ts"] < CACHE_TTL_SECONDS:
        return cached["payload"]

    # 2. No TomTom key → disk cache or synthetic
    if not TOMTOM_API_KEY:
        disk = _load_disk_cache(city_key)
        if disk:
            return disk
        return _synthetic_payload(city_key, points, cfg)

    # 3. Fetch from TomTom
    sem = asyncio.Semaphore(TOMTOM_CONCURRENCY)
    async with httpx.AsyncClient(timeout=20.0) as client:
        tasks = [
            fetch_flow_point(client, sem, lat=lat, lon=lon, name=name, idx=i+1, jam_density=cfg["jam_density"])
            for i, (lat, lon, name) in enumerate(points)
        ]
        results = await asyncio.gather(*tasks)

    segments: List[Dict] = []
    features: List[Dict] = []
    errors:   List[Dict] = []
    seen_sigs: set       = set()

    for item in results:
        if not item: continue
        if item.get("_error"):
            errors.append(item)
            continue
        sig = item.get("sig", "")
        if sig and sig in seen_sigs: continue
        seen_sigs.add(sig)
        new_id = len(segments) + 1
        seg    = {**item["segment"], "id": new_id, "segment_id": new_id}
        feat   = {
            **item["feature"], "id": new_id,
            "properties": {**item["feature"]["properties"], "id": new_id, "segment_id": new_id},
        }
        segments.append(seg)
        features.append(feat)

    # If too many errors, fall back to disk cache
    if len(errors) > len(results) * 0.7:
        disk = _load_disk_cache(city_key)
        if disk:
            return disk
        return _synthetic_payload(city_key, points, cfg)

    avg_speed = round(sum(s["speed_v"] for s in segments) / max(len(segments), 1), 1)
    jam_count = sum(1 for s in segments if s["congestion_level"] >= 3)

    payload = {
        "city": city_key, "mode": "tomtom-live-dense",
        "source": "TomTom Traffic Flow Segment Data",
        "is_real_traffic": True,
        "sample_points_requested": len(points),
        "type": "FeatureCollection",
        "features": features, "segments": segments,
        "stats": {"segments": len(segments), "avg_speed": avg_speed, "jams": jam_count, "errors": len(errors)},
        "errors": errors[:3],
    }

    # Save to both memory and disk cache
    _MEM_CACHE[cache_key] = {"ts": now, "payload": payload}
    _save_disk_cache(city_key, payload)

    return payload
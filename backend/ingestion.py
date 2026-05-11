from fastapi import APIRouter, HTTPException
from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
import httpx
import asyncio
import os
import logging
import random
from datetime import datetime, timedelta

from database import engine, TrafficReading, RoadSegment 

log = logging.getLogger("trafficos.ingestion")
router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")

# ── City configs ──────────────────────────────────────────────────────────────
CITIES = {
    "fusagasuga": {
        "name": "Fusagasugá",
        "lat": 4.3366,
        "lon": -74.3641,
        "bbox": "-74.400,4.300,-74.320,4.380",
        "delta": 0.05,
        "default_speed_limit": 50.0,
        "default_jam_density": 120.0,
    },
    "san_francisco": {
        "name": "San Francisco",
        "lat": 37.7749,
        "lon": -122.4194,
        "bbox": "-122.515,37.706,-122.355,37.832",
        "delta": 0.04,
        "default_speed_limit": 50.0,
        "default_jam_density": 150.0,
    },
}

# Legacy constants for backward compat
FUSA_LAT, FUSA_LON = CITIES["fusagasuga"]["lat"], CITIES["fusagasuga"]["lon"]
FUSA_BBOX = CITIES["fusagasuga"]["bbox"]

celery_app = Celery("trafficos", broker=REDIS_URL, backend=REDIS_URL)
TOMTOM_TO_RATIO = {0: 0.1, 1: 0.25, 2: 0.45, 3: 0.75, 4: 1.0}


async def save_traffic_to_db(incidents, source_name="tomtom"):
    async with AsyncSession(engine) as session:
        for inc in incidents:
            geo = inc.get("geometry", {})
            coords = geo.get("coordinates", [])
            if not coords: continue
            wkt = f"POINT({coords[0]} {coords[1]})" if geo.get("type") == "Point" else f"LINESTRING({', '.join([f'{c[0]} {c[1]}' for c in coords])})"
            stmt = select(RoadSegment).order_by(func.ST_Distance(RoadSegment.geometry, func.ST_GeomFromText(wkt, 4326))).limit(1)
            result = await session.execute(stmt)
            seg = result.scalar_one_or_none()
            if seg:
                mag = inc.get("properties", {}).get("magnitudeOfDelay", 0)
                ratio = TOMTOM_TO_RATIO.get(mag, 0.1)
                session.add(TrafficReading(
                    segment_id=seg.id, timestamp=datetime.utcnow(),
                    congestion_level=mag, density_k=seg.jam_density * ratio,
                    speed_v=seg.speed_limit * (1.0 - ratio), source=source_name
                ))
        await session.commit()

@celery_app.task(name="ingest_traffic")
def ingest_traffic():
    url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={TOMTOM_API_KEY}&bbox={FUSA_BBOX}&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay}}}}}}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url)
        if resp.status_code == 200:
            asyncio.run(save_traffic_to_db(resp.json().get("incidents", [])))

# --- ENDPOINTS ---

@router.get("/cities")
async def list_cities():
    """Return available cities for the city selector."""
    return {
        "cities": [
            {"id": k, "name": v["name"], "lat": v["lat"], "lon": v["lon"]}
            for k, v in CITIES.items()
        ]
    }

# Replace the ingest_osm_roads function in ingestion.py with this:

@router.post("/trigger/ingest-osm")
async def ingest_osm_roads(city: str = "fusagasuga", lat: float = None, lng: float = None):
    """
    Streaming tile-based OSM ingest — like open world game chunk loading.
    Fetches a small tile around the given coordinates (or city center).
    Previously loaded tiles are skipped (cached in DB).
    """
    cfg = CITIES.get(city)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Unknown city: {city}")

    # Use provided coords or fall back to city center
    center_lat = lat or cfg["lat"]
    center_lng = lng or cfg["lon"]

    # Small tile size — fast to fetch, like a game chunk
    TILE_DELTA = 0.018  # ~2km x 2km tile

    overpass_query = f"""[out:json][timeout:30];
way["highway"]({center_lat - TILE_DELTA},{center_lng - TILE_DELTA},{center_lat + TILE_DELTA},{center_lng + TILE_DELTA});
out geom;"""

    log.info(f"Loading tile ({center_lat:.4f},{center_lng:.4f}) for {cfg['name']}...")

    resp = None
    for url in [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]:
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post(
                    url,
                    content=f"data={overpass_query}".encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
            if resp.status_code == 200:
                log.info(f"Got response from {url}")
                break
        except Exception as e:
            log.warning(f"Overpass {url} failed: {e}")
            continue

    if not resp or resp.status_code != 200:
        raise HTTPException(status_code=502, detail="All Overpass mirrors unavailable")

    elements = resp.json().get("elements", [])
    log.info(f"Tile returned {len(elements)} ways")

    async with AsyncSession(engine) as session:
        inserted = 0
        skipped = 0
        for el in elements:
            if el["type"] == "way" and "geometry" in el:
                coords = el["geometry"]
                if len(coords) < 2:
                    continue
                wkt = "LINESTRING(" + ", ".join([f"{p['lon']} {p['lat']}" for p in coords]) + ")"
                stmt = pg_insert(RoadSegment).values(
                    osm_id=str(el["id"]),
                    name=el.get("tags", {}).get("name", "Unnamed Road"),
                    highway_type=el.get("tags", {}).get("highway", "residential"),
                    length_m=0.0,
                    speed_limit=cfg["default_speed_limit"],
                    jam_density=cfg["default_jam_density"],
                    geometry=func.ST_GeomFromText(wkt, 4326)
                ).on_conflict_do_nothing()
                result = await session.execute(stmt)
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
        await session.commit()

    log.info(f"Tile done: {inserted} new, {skipped} cached for {cfg['name']}")
    return {
        "status": "success",
        "city": cfg["name"],
        "tile": {"lat": center_lat, "lng": center_lng, "delta": TILE_DELTA},
        "segments_inserted": inserted,
        "segments_cached": skipped,
    }

@router.post("/trigger/mock-traffic")
async def trigger_mock_traffic(count: int = 50):
    async with AsyncSession(engine) as session:
        res = await session.execute(select(RoadSegment))
        segs = res.scalars().all()
        if not segs:
            return {"status": "no_segments"}
        for _ in range(count):
            s = random.choice(segs)
            lvl = random.randint(1, 4)
            ratio = TOMTOM_TO_RATIO[lvl]
            session.add(TrafficReading(
                segment_id=s.id, timestamp=datetime.utcnow(),
                congestion_level=lvl, density_k=120.0 * ratio,
                speed_v=50.0 * (1.0 - ratio), source="mock"
            ))
        await session.commit()
    return {"status": "ok"}

@router.post("/trigger/mock-history")
async def trigger_mock_history(segment_id: int):
    async with AsyncSession(engine) as session:
        now = datetime.utcnow()
        for i in range(24):
            ts = now - timedelta(hours=i)
            lvl = (i % 4) + 1
            ratio = TOMTOM_TO_RATIO[lvl]
            session.add(TrafficReading(
                segment_id=segment_id, timestamp=ts,
                congestion_level=lvl, density_k=120.0 * ratio,
                speed_v=50.0 * (1.0 - ratio), source="history_gen"
            ))
        await session.commit()
    return {"status": "history_generated"}

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from contextlib import asynccontextmanager
import os
import logging

# ── MUST be before any local imports so DATABASE_URL is set before engine init
from dotenv import load_dotenv
load_dotenv()

from auth import router as auth_router
from prediction import router as prediction_router
from routes import router as routes_router
from ingestion import router as ingestion_router, ingest_osm_roads
from graph_api import router as graph_router
from gemini import router as gemini_router
from database import engine, Base, RoadSegment

# Real TomTom live traffic adapter
from tomtom_live import get_tomtom_live_map_data

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trafficos")


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


USE_POSTGIS = env_bool("USE_POSTGIS", "false")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TrafficOS Neural Engine starting...")

    async with engine.begin() as conn:
        if USE_POSTGIS:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                log.info("PostGIS extension checked/enabled.")
            except Exception as e:
                log.error(f"PostGIS extension could not be enabled: {e}")
                raise
        else:
            log.info("USE_POSTGIS=false. Skipping PostGIS extension.")

        await conn.run_sync(Base.metadata.create_all)
        log.info("Database tables checked/created.")

    # Auto-init Fusagasugá only if explicitly enabled.
    # For Railway demo, keep AUTO_INIT_OSM=false.
    auto_init_osm = env_bool("AUTO_INIT_OSM", "false")

    if auto_init_osm:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(select(func.count(RoadSegment.id)))
            segment_count = result.scalar() or 0

            if segment_count == 0:
                log.info("DB empty. Fetching OSM grid for Fusagasugá...")
                try:
                    await ingest_osm_roads(city="fusagasuga")
                    log.info("OSM auto-init completed.")
                except Exception as e:
                    log.error(f"Auto-init failed. Check OSM connection: {e}")
            else:
                log.info(f"Road network already initialized: {segment_count} segments.")
    else:
        log.info("AUTO_INIT_OSM=false. Skipping OSM auto-initialization.")

    yield

    log.info("TrafficOS Neural Engine shutting down...")


app = FastAPI(title="TrafficOS", lifespan=lifespan)


# ── CORS ──────────────────────────────────────────────────────────────────────

FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip()
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").strip()

origins = [
    "http://localhost:5174",
    "http://localhost:5173",
    "http://localhost:8000",
    "https://localhost:5173",
]

if FRONTEND_URL:
    origins.append(FRONTEND_URL)

if CORS_ORIGINS:
    origins.extend(
        origin.strip()
        for origin in CORS_ORIGINS.split(",")
        if origin.strip()
    )

# Remove duplicates while preserving order
origins = list(dict.fromkeys(origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(prediction_router, prefix="/api/predict", tags=["Predict"])
app.include_router(routes_router, prefix="/api/routes", tags=["Routes"])
app.include_router(ingestion_router, prefix="/api/ingest", tags=["Ingest"])
app.include_router(graph_router, prefix="/api/graph", tags=["Graph System"])
app.include_router(gemini_router, prefix="/api/aria", tags=["ARIA Intelligence"])


# ── Health / Root ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "message": "TrafficOS is operational",
        "cities": ["Fusagasugá", "San Francisco"],
        "use_postgis": USE_POSTGIS,
        "traffic_source": "TomTom live traffic",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "message": "TrafficOS is operational",
        "cities": ["Fusagasugá", "San Francisco"],
        "use_postgis": USE_POSTGIS,
        "traffic_source": "TomTom live traffic",
    }


@app.get("/api/traffic/map-data")
async def get_map_traffic(
    city: str = Query(
        default="fusagasuga",
        description="Supported values: fusagasuga, san_francisco",
    )
):
    """
    Real TomTom-powered traffic endpoint.

    Supported:
    - /api/traffic/map-data?city=fusagasuga
    - /api/traffic/map-data?city=san_francisco

    The TomTom key stays on the backend. Netlify never sees it.
    """
    return await get_tomtom_live_map_data(city=city)


@app.get("/api/cities")
async def get_cities():
    return {
        "cities": [
            {
                "id": "fusagasuga",
                "label": "Fusagasugá",
                "country": "Colombia",
                "mode": "tomtom-live",
                "center": [-74.3649, 4.3379],
            },
            {
                "id": "san_francisco",
                "label": "San Francisco",
                "country": "United States",
                "mode": "tomtom-live",
                "center": [-122.4194, 37.7749],
            },
        ]
    }


@app.get("/")
async def root():
    return {
        "message": "Neural Traffic API is running",
        "health_check": "/api/health",
        "traffic_fusagasuga": "/api/traffic/map-data?city=fusagasuga",
        "traffic_san_francisco": "/api/traffic/map-data?city=san_francisco",
    }
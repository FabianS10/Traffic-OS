from fastapi import FastAPI
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
from database_spatial import get_fusa_street_grid_with_traffic

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trafficos")


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TrafficOS Neural Engine starting...")

    # Create PostGIS extension before creating geometry columns.
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            log.info("PostGIS extension checked/enabled.")
        except Exception as e:
            log.error(f"PostGIS extension could not be enabled: {e}")
            raise

        await conn.run_sync(Base.metadata.create_all)
        log.info("Database tables checked/created.")

    # Auto-init Fusagasugá if DB is empty.
    # You can disable this on Railway with AUTO_INIT_OSM=false if startup is slow.
    auto_init_osm = env_bool("AUTO_INIT_OSM", "true")

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
                    # Do not kill the whole deployment if OSM fetch fails.
                    # The app can still serve demo/synthetic endpoints.
                    log.error(f"Auto-init failed. Check OSM connection: {e}")
            else:
                log.info(f"Road network already initialized: {segment_count} segments.")
    else:
        log.info("AUTO_INIT_OSM=false. Skipping OSM auto-initialization.")

    yield

    log.info("TrafficOS Neural Engine shutting down...")


app = FastAPI(title="TrafficOS", lifespan=lifespan)


# ── CORS ──────────────────────────────────────────────────────────────────────

# Supports both:
# FRONTEND_URL=https://your-site.netlify.app
# CORS_ORIGINS=https://site1.netlify.app,https://site2.netlify.app
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
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "message": "TrafficOS is operational",
        "cities": ["Fusagasugá", "San Francisco"],
    }


@app.get("/api/traffic/map-data")
async def get_map_traffic():
    return await get_fusa_street_grid_with_traffic()


@app.get("/")
async def root():
    return {
        "message": "Neural Traffic API is running",
        "health_check": "/api/health",
    }
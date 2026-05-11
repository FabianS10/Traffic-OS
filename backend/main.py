from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TrafficOS Neural Engine starting...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Auto-init Fusagasugá if DB is empty
    async with AsyncSession(engine) as session:
        result = await session.execute(select(func.count(RoadSegment.id)))
        if result.scalar() == 0:
            log.info("DB Empty. Fetching OSM grid for Fusagasugá...")
            try:
                await ingest_osm_roads(city="fusagasuga")
            except Exception as e:
                log.error(f"Auto-init failed (Check OSM connection): {e}")
    yield

app = FastAPI(title="TrafficOS", lifespan=lifespan)

FRONTEND_URL = os.getenv("FRONTEND_URL", "")

origins = [
    "http://localhost:5174",
    "http://localhost:5173",
    "http://localhost:8000",
    "https://localhost:5173",
]
if FRONTEND_URL:
    origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,       prefix="/api/auth",    tags=["Auth"])
app.include_router(prediction_router, prefix="/api/predict", tags=["Predict"])
app.include_router(routes_router,     prefix="/api/routes",  tags=["Routes"])
app.include_router(ingestion_router,  prefix="/api/ingest",  tags=["Ingest"])
app.include_router(graph_router,      prefix="/api/graph",   tags=["Graph System"])
app.include_router(gemini_router,     prefix="/api/aria",    tags=["ARIA Intelligence"])

@app.get("/api/health")
async def health():
    return {"status": "ok", "message": "TrafficOS is operational", "cities": ["Fusagasugá", "San Francisco"]}

@app.get("/api/traffic/map-data")
async def get_map_traffic():
    return await get_fusa_street_grid_with_traffic()

@app.get("/")
async def root():
    return {"message": "Neural Traffic API is running", "health_check": "/api/health"}

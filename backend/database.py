"""
Database models — PostgreSQL + PostGIS
Spatial queries via GeoAlchemy2
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime,
    ForeignKey, Text, JSON, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
from datetime import datetime
import uuid
import os

# ── Database URL — auto-fix common misconfigurations ─────────────────────────
_db_url = os.getenv("DATABASE_URL", "")

# @db is Docker-internal hostname — replace with localhost when running locally
if "@db:" in _db_url:
    _db_url = _db_url.replace("@db:", "@localhost:")

# Some .env files have 'postgres' user but Docker creates 'trafficos'
if "//postgres:" in _db_url:
    _db_url = _db_url.replace("//postgres:", "//trafficos:")

DATABASE_URL = _db_url or "postgresql+asyncpg://trafficos:trafficos123@localhost:5432/trafficos"

print(f"🔌 DATABASE_URL = {DATABASE_URL}")  # ADD THIS LINE

engine = create_async_engine(DATABASE_URL, echo=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session

# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email            = Column(String(255), unique=True, nullable=False, index=True)
    username         = Column(String(100), unique=True, nullable=False)
    hashed_password  = Column(String(255), nullable=True)
    oauth_provider   = Column(String(50), nullable=True)
    oauth_id         = Column(String(255), nullable=True)
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    last_login       = Column(DateTime, nullable=True)

    saved_routes  = relationship("SavedRoute", back_populates="user", cascade="all, delete")
    alerts        = relationship("UserAlert",  back_populates="user", cascade="all, delete")

# ── Road network ───────────────────────────────────────────────────────────────

class RoadSegment(Base):
    __tablename__ = "road_segments"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    osm_id        = Column(String(50), unique=True, index=True)
    name          = Column(String(255), nullable=True)
    highway_type  = Column(String(50))
    length_m      = Column(Float)
    lanes         = Column(Integer, default=2)
    speed_limit   = Column(Float, default=50.0)
    jam_density   = Column(Float, default=120.0)
    geometry      = Column(Geometry("LINESTRING", srid=4326))

    readings      = relationship("TrafficReading", back_populates="segment")

class TrafficReading(Base):
    __tablename__ = "traffic_readings"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    segment_id       = Column(Integer, ForeignKey("road_segments.id"), index=True)
    timestamp        = Column(DateTime, nullable=False, index=True)
    density_k        = Column(Float)
    flow_q           = Column(Float)
    speed_v          = Column(Float)
    congestion_level = Column(Integer)
    source           = Column(String(50))

    segment       = relationship("RoadSegment", back_populates="readings")

class WeatherEvent(Base):
    __tablename__ = "weather_events"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime, nullable=False, index=True)
    temperature   = Column(Float)
    precipitation = Column(Float)
    is_raining    = Column(Boolean, default=False)
    visibility    = Column(Float)
    wind_speed    = Column(Float)
    condition     = Column(String(50))

# ── User data ──────────────────────────────────────────────────────────────────

class SavedRoute(Base):
    __tablename__ = "saved_routes"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name          = Column(String(255))
    origin_name   = Column(String(255))
    dest_name     = Column(String(255))
    origin        = Column(Geometry("POINT", srid=4326))
    destination   = Column(Geometry("POINT", srid=4326))
    waypoints     = Column(JSON, default=list)
    segment_ids   = Column(JSON, default=list)
    created_at    = Column(DateTime, default=datetime.utcnow)

    user          = relationship("User", back_populates="saved_routes")

class UserAlert(Base):
    __tablename__ = "user_alerts"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    route_id      = Column(UUID(as_uuid=True), ForeignKey("saved_routes.id"), nullable=True)
    threshold     = Column(Integer, default=3)
    notify_email  = Column(Boolean, default=True)
    is_active     = Column(Boolean, default=True)

    user          = relationship("User", back_populates="alerts")
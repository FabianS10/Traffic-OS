"""
Database models — PostgreSQL with optional PostGIS support.

Railway-safe mode:
- USE_POSTGIS=false stores geometry-like data as JSON.
- USE_POSTGIS=true uses GeoAlchemy2 Geometry columns and requires PostGIS.
"""

from datetime import datetime
import os
import uuid

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID


# ── Feature flags ─────────────────────────────────────────────────────────────

USE_POSTGIS = os.getenv("USE_POSTGIS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if USE_POSTGIS:
    from geoalchemy2 import Geometry

    def GeoColumn(geom_type: str):
        return Geometry(geom_type, srid=4326)
else:
    def GeoColumn(geom_type: str):
        # Railway fallback: store coordinates/GeoJSON-like payloads as JSON.
        return JSON


# ── Database URL — Railway/local safe configuration ───────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://trafficos:trafficos123@localhost:5432/trafficos",
).strip()

# Railway often provides:
# postgresql://user:password@host:port/db
#
# SQLAlchemy async requires:
# postgresql+asyncpg://user:password@host:port/db
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )

# Some providers use postgres:// instead of postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+asyncpg://",
        1,
    )

# Local development helper:
# If running outside Docker but the URL points to Docker service name "db",
# replace it with localhost.
#
# Do not apply this on Railway.
if "@db:" in DATABASE_URL and not os.getenv("RAILWAY_ENVIRONMENT"):
    DATABASE_URL = DATABASE_URL.replace("@db:", "@localhost:")

# Never print DATABASE_URL. It contains the database password.
print(
    "Database engine configured. "
    f"USE_POSTGIS={USE_POSTGIS}"
)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    saved_routes = relationship(
        "SavedRoute",
        back_populates="user",
        cascade="all, delete",
    )
    alerts = relationship(
        "UserAlert",
        back_populates="user",
        cascade="all, delete",
    )


# ── Road network ───────────────────────────────────────────────────────────────

class RoadSegment(Base):
    __tablename__ = "road_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    osm_id = Column(String(50), unique=True, index=True)
    name = Column(String(255), nullable=True)
    highway_type = Column(String(50))
    length_m = Column(Float)
    lanes = Column(Integer, default=2)
    speed_limit = Column(Float, default=50.0)
    jam_density = Column(Float, default=120.0)

    # PostGIS mode: geometry(LINESTRING, 4326)
    # Railway fallback: JSON
    geometry = Column(GeoColumn("LINESTRING"))

    readings = relationship(
        "TrafficReading",
        back_populates="segment",
        cascade="all, delete",
    )


class TrafficReading(Base):
    __tablename__ = "traffic_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey("road_segments.id"), index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    density_k = Column(Float)
    flow_q = Column(Float)
    speed_v = Column(Float)
    congestion_level = Column(Integer)
    source = Column(String(50))

    segment = relationship(
        "RoadSegment",
        back_populates="readings",
    )


class WeatherEvent(Base):
    __tablename__ = "weather_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    temperature = Column(Float)
    precipitation = Column(Float)
    is_raining = Column(Boolean, default=False)
    visibility = Column(Float)
    wind_speed = Column(Float)
    condition = Column(String(50))


# ── User data ──────────────────────────────────────────────────────────────────

class SavedRoute(Base):
    __tablename__ = "saved_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name = Column(String(255))
    origin_name = Column(String(255))
    dest_name = Column(String(255))

    # PostGIS mode: geometry(POINT, 4326)
    # Railway fallback: JSON
    origin = Column(GeoColumn("POINT"))
    destination = Column(GeoColumn("POINT"))

    waypoints = Column(JSON, default=list)
    segment_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship(
        "User",
        back_populates="saved_routes",
    )


class UserAlert(Base):
    __tablename__ = "user_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    route_id = Column(UUID(as_uuid=True), ForeignKey("saved_routes.id"), nullable=True)
    threshold = Column(Integer, default=3)
    notify_email = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    user = relationship(
        "User",
        back_populates="alerts",
    )
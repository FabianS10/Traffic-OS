"""
Saved Routes API — user route management with PostGIS
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
import uuid

from database import get_db, SavedRoute, User
from auth import get_current_user

router = APIRouter()


class RouteCreate(BaseModel):
    name:       str
    origin_name: str
    dest_name:   str
    origin_lat:  float
    origin_lon:  float
    dest_lat:    float
    dest_lon:    float
    waypoints:   list = []
    segment_ids: list = []

class RouteResponse(BaseModel):
    id:          str
    name:        str
    origin_name: str
    dest_name:   str
    segment_ids: list

    class Config:
        from_attributes = True


@router.get("/")
async def list_routes(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedRoute).where(SavedRoute.user_id == user.id)
    )
    routes = result.scalars().all()
    return [
        {
            "id":          str(r.id),
            "name":        r.name,
            "origin_name": r.origin_name,
            "dest_name":   r.dest_name,
            "segment_ids": r.segment_ids,
        }
        for r in routes
    ]


@router.post("/", status_code=201)
async def create_route(
    body: RouteCreate,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    route = SavedRoute(
        user_id      = user.id,
        name         = body.name,
        origin_name  = body.origin_name,
        dest_name    = body.dest_name,
        origin       = f"SRID=4326;POINT({body.origin_lon} {body.origin_lat})",
        destination  = f"SRID=4326;POINT({body.dest_lon} {body.dest_lat})",
        waypoints    = body.waypoints,
        segment_ids  = body.segment_ids,
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return {"id": str(route.id), "name": route.name}


@router.delete("/{route_id}")
async def delete_route(
    route_id: str,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedRoute).where(
            SavedRoute.id == route_id,
            SavedRoute.user_id == user.id,
        )
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    await db.delete(route)
    await db.commit()
    return {"deleted": route_id}


@router.get("/nearby")
async def nearby_routes(
    lat:      float,
    lon:      float,
    radius_m: float = 500.0,
    db: AsyncSession = Depends(get_db),
):
    """Find saved routes whose origin or destination is within radius_m of (lat, lon)."""
    point = f"SRID=4326;POINT({lon} {lat})"
    result = await db.execute(
        select(SavedRoute).where(
            func.ST_DWithin(
                func.ST_Transform(SavedRoute.origin, 3857),
                func.ST_Transform(func.ST_GeomFromEWKT(point), 3857),
                radius_m,
            )
        ).limit(20)
    )
    routes = result.scalars().all()
    return [{"id": str(r.id), "name": r.name} for r in routes]

"""
graph_api.py — TrafficOS Graph System API

Key fixes vs original:
  - Graph is built ONCE at startup (via lifespan) and held in memory.
    Original rebuilt on every /route request which was expensive and
    prevented lru_cache from working across calls.
  - /refresh endpoint for explicit rebuild (admin use / after OSM ingest).
  - /reroute now passes origin+dest (was missing them, calling a method
    that doesn't exist: get_alternate_path with only avoid_id).
  - All endpoints return consistent {status, ...} shape.
"""

import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from database import get_db, RoadSegment
from navigation import GraphEngine

logger = logging.getLogger("trafficos.graph_api")

router = APIRouter()

# ── Singleton engine — built once, lives in RAM ───────────────────────────────
engine = GraphEngine()
_graph_ready = False


async def _build_from_db(db: AsyncSession) -> dict:
    """Pull all road segments and build the graph. Returns stats."""
    global _graph_ready
    result   = await db.execute(select(RoadSegment))
    segments = result.scalars().all()
    if not segments:
        logger.error("No road segments in DB — cannot build graph")
        return {"nodes": 0, "edges": 0}
    stats = engine.build_graph(segments)
    _graph_ready = True
    return stats


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    origin_node:      str             # segment_id of origin
    dest_node:        str             # segment_id of destination
    avoid_segment_id: Optional[str] = None
    horizon_preds:    Optional[dict] = None   # {segment_id: congestion_level}

class RerouteRequest(BaseModel):
    origin_node:      str
    dest_node:        str
    avoid_segment_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/route")
async def calculate_astar_path(
    request: RouteRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Compute the optimal A* route between two segment IDs.
    Graph is built lazily on first call if not yet initialised.
    """
    global _graph_ready
    if not _graph_ready:
        logger.info("Graph not initialised — lazy build on first /route call")
        await _build_from_db(db)

    result = engine.get_optimal_route_astar(
        origin_id      = request.origin_node,
        dest_id        = request.dest_node,
        horizon_preds  = request.horizon_preds,
    )
    return result


@router.post("/reroute")
async def get_reroute(
    request: RerouteRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Return an alternate route that avoids a specific segment.
    (Original implementation called get_alternate_path(avoid_id) with only
    one argument, which caused an immediate TypeError.)
    """
    global _graph_ready
    if not _graph_ready:
        await _build_from_db(db)

    result = engine.get_alternate_path(
        origin_id        = request.origin_node,
        dest_id          = request.dest_node,
        avoid_segment_id = request.avoid_segment_id,
    )
    return result


@router.post("/refresh")
async def refresh_graph(
    background_tasks: BackgroundTasks,
    db:               AsyncSession = Depends(get_db),
):
    """
    Rebuild the graph from the current DB state.
    Call this after OSM ingest or when the road network changes.
    """
    stats = await _build_from_db(db)
    return {"status": "rebuilt", **stats}


@router.get("/status")
async def graph_status():
    """Return current graph health metrics."""
    return engine.status()

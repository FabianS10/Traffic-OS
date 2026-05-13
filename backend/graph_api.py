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


# ── TomTom Live Graph Builder ─────────────────────────────────────────────────
import math as _math
from tomtom_live import get_tomtom_live_map_data, normalize_city as _norm_city
import networkx as _nx


async def _build_from_tomtom(city: str) -> dict:
    """Build routing graph directly from live TomTom coordinates."""
    global _graph_ready
    data     = await get_tomtom_live_map_data(city=city)
    features = data.get("features", [])
    if not features:
        return {"nodes": 0, "edges": 0}

    g = engine.graph
    g.clear()
    engine._segment_map = {}
    engine._dist.cache_clear()

    for feat in features:
        seg_id = str(feat.get("id") or feat["properties"].get("id", 0))
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        speed = max(5.0, float(feat["properties"].get("speed_v") or feat["properties"].get("free_flow_speed") or 30))

        u = (round(coords[0][0],  5), round(coords[0][1],  5))
        v = (round(coords[-1][0], 5), round(coords[-1][1], 5))

        def hav(a, b):
            R = 6371000
            p1, p2 = _math.radians(a[1]), _math.radians(b[1])
            dp = _math.radians(b[1] - a[1])
            dl = _math.radians(b[0] - a[0])
            aa = _math.sin(dp/2)**2 + _math.cos(p1)*_math.cos(p2)*_math.sin(dl/2)**2
            return 2 * R * _math.asin(_math.sqrt(max(0, aa)))

        length_m = hav(coords[0], coords[-1])
        cost     = length_m / (speed / 3.6)

        for n in (u, v):
            if n not in g:
                g.add_node(n, x=n[0], y=n[1])

        edge_data = {
            "weight":     cost,
            "segment_id": seg_id,
            "length_m":   length_m,
            "geometry":   {"type": "LineString", "coordinates": coords},
        }
        g.add_edge(u, v, **edge_data)
        g.add_edge(v, u, **edge_data)
        if seg_id not in engine._segment_map:
            engine._segment_map[seg_id] = (u, v)

    # Prune islands
    comps      = sorted(_nx.strongly_connected_components(g), key=len, reverse=True)
    main_nodes = comps[0] if comps else set()
    dead       = [n for n in g.nodes if n not in main_nodes]
    g.remove_nodes_from(dead)
    engine._segment_map = {
        sid: (u, v) for sid, (u, v) in engine._segment_map.items()
        if u in g and v in g
    }
    engine._built = True
    _graph_ready  = True

    stats = {
        "nodes":    g.number_of_nodes(),
        "edges":    g.number_of_edges(),
        "routable": len(engine._segment_map),
        "source":   "tomtom_live",
    }
    logger.info(f"✅ TomTom Graph | nodes={stats['nodes']} routable={stats['routable']}")
    return stats


@router.post("/build-tomtom")
async def build_graph_from_tomtom(city: str = "fusagasuga"):
    """Build the A* routing graph from live TomTom segments."""
    stats = await _build_from_tomtom(city=city)
    return {"status": "built", **stats}


@router.post("/route-tomtom")
async def route_with_tomtom(request: RouteRequest):
    """
    Iron-clad A* routing endpoint.
    Auto-builds graph from TomTom live data if not ready.
    Works with or without OSM data in the DB.
    """
    global _graph_ready
    if not _graph_ready or engine.graph.number_of_nodes() < 5:
        # Detect city from origin_node (TomTom IDs are just integers)
        # Default to fusagasuga; frontend passes city hint via horizon_preds
        city = (request.horizon_preds or {}).get("__city__", "fusagasuga")
        logger.info(f"Auto-building TomTom graph for {city}...")
        await _build_from_tomtom(city=city)

    return engine.get_optimal_route_astar(
        origin_id     = request.origin_node,
        dest_id       = request.dest_node,
        horizon_preds = {k: v for k, v in (request.horizon_preds or {}).items() if k != "__city__"},
    )
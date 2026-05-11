"""
navigation.py — TrafficOS GraphEngine v2 (Ironclad)

Fixed bugs vs original:
  1. start/target node selection: was m_orig[1]/m_dest[0] (wrong ends).
     Now tries all 4 (u,v) combinations and picks whichever pair is
     reachable, with Haversine-proximity fallback to nearest graph node.
  2. _segment_map is now filtered AFTER island pruning so it only
     contains nodes that survived the strongly_connected_components cut.
  3. lru_cache on _dist cleared on every build_graph() call to prevent
     stale heuristic values from old graph topology poisoning A*.
  4. graph_api no longer rebuilds on every request — graph is built once
     at startup and refreshed via a dedicated /refresh endpoint.
"""

import math
import logging
import networkx as nx
from functools import lru_cache
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping, MultiLineString, LineString

logger = logging.getLogger("trafficos.navigation")


class GraphEngine:
    def __init__(self):
        self.graph        = nx.DiGraph()
        self._segment_map = {}   # segment_id (str) → (u, v) after pruning
        self._R           = 6371000
        self._built       = False

    # ── Graph construction ────────────────────────────────────────────────────

    def build_graph(self, segments) -> dict:
        """
        Build the road graph from ORM RoadSegment objects.
        Returns a stats dict so the caller can log/expose it.
        """
        self.graph.clear()
        self._segment_map = {}
        self._built = False

        # MUST clear lru_cache here — old topology poisons the heuristic
        self._dist.cache_clear()

        if not segments:
            logger.error("build_graph: no segments supplied")
            return {"nodes": 0, "edges": 0, "pruned": 0}

        raw_edges = 0
        for seg in segments:
            try:
                shape = to_shape(seg.geometry)

                # Normalise MultiLineString → list of LineStrings
                if isinstance(shape, MultiLineString):
                    lines = list(shape.geoms)
                elif isinstance(shape, LineString):
                    lines = [shape]
                else:
                    continue

                for line in lines:
                    coords = list(line.coords)
                    if len(coords) < 2:
                        continue

                    # Snap to 5 dp (~1 m) to stitch intersections
                    u = (round(coords[0][0],  5), round(coords[0][1],  5))
                    v = (round(coords[-1][0], 5), round(coords[-1][1], 5))

                    speed  = (seg.speed_limit or 30.0)
                    cost   = (seg.length_m or 100.0) / (speed / 3.6)

                    for n in (u, v):
                        if n not in self.graph:
                            self.graph.add_node(n, x=n[0], y=n[1])

                    edge_data = {
                        "weight":     cost,
                        "segment_id": str(seg.id),
                        "length_m":   seg.length_m or 100.0,
                        "geometry":   mapping(line),
                    }
                    self.graph.add_edge(u, v, **edge_data)
                    self.graph.add_edge(v, u, **edge_data)
                    raw_edges += 1

                    # Store BEFORE pruning — will be filtered below
                    # Use first line of each segment as the canonical (u,v)
                    if str(seg.id) not in self._segment_map:
                        self._segment_map[str(seg.id)] = (u, v)

            except Exception as exc:
                logger.debug(f"Skipping segment {seg.id}: {exc}")
                continue

        # ── Island pruning: keep only the largest strongly-connected component
        components  = sorted(nx.strongly_connected_components(self.graph), key=len, reverse=True)
        main_nodes  = components[0] if components else set()
        dead_nodes  = [n for n in self.graph.nodes if n not in main_nodes]
        self.graph.remove_nodes_from(dead_nodes)

        # FIX 2: Re-filter _segment_map to only keep entries whose BOTH
        # nodes survived pruning.  Any entry pointing to a removed node
        # would cause spurious "Calle desconectada" errors.
        self._segment_map = {
            sid: (u, v)
            for sid, (u, v) in self._segment_map.items()
            if u in self.graph and v in self.graph
        }

        self._built = True
        stats = {
            "nodes":   self.graph.number_of_nodes(),
            "edges":   self.graph.number_of_edges(),
            "pruned":  len(dead_nodes),
            "routable": len(self._segment_map),
        }
        logger.info(
            f"✅ GPS ONLINE | nodes={stats['nodes']} edges={stats['edges']} "
            f"pruned={stats['pruned']} routable_segments={stats['routable']}"
        )
        return stats

    # ── Heuristic ─────────────────────────────────────────────────────────────

    @lru_cache(maxsize=8192)
    def _dist(self, u: tuple, v: tuple) -> float:
        """
        Haversine distance (seconds at 80 km/h) between two graph nodes.
        Cached — cache is cleared on every build_graph() call.
        Node coords: x=longitude, y=latitude.
        """
        try:
            n1, n2 = self.graph.nodes[u], self.graph.nodes[v]
        except KeyError:
            return 0.0

        phi1 = math.radians(n1["y"])
        phi2 = math.radians(n2["y"])
        dphi = math.radians(n2["y"] - n1["y"])
        dlam = math.radians(n2["x"] - n1["x"])

        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        dist_m = 2 * self._R * math.asin(math.sqrt(max(0.0, a)))
        return dist_m / 22.2   # time at 80 km/h (admissible upper bound)

    # ── Nearest-node helper ───────────────────────────────────────────────────

    def _nearest_node(self, target: tuple) -> tuple | None:
        """
        Haversine-nearest graph node to `target`.
        Used as fallback when the canonical (u,v) of a segment was pruned.
        O(N) but N=596 so it's fast.
        """
        best, best_d = None, float("inf")
        tx, ty = target
        for node in self.graph.nodes:
            dx = (node[0] - tx) * math.cos(math.radians(ty))
            dy  = node[1] - ty
            d   = dx*dx + dy*dy
            if d < best_d:
                best_d, best = d, node
        return best

    # ── A* routing ───────────────────────────────────────────────────────────

    def get_optimal_route_astar(
        self,
        origin_id: str | int,
        dest_id:   str | int,
        horizon_preds: dict | None = None,
    ) -> dict:
        """
        Compute optimal route between two segment IDs.

        FIX 1: Instead of blindly using m_orig[1] and m_dest[0] (which
        selects the wrong ends and silently fails after pruning), we now:
          a) Try all 4 (start, target) combinations of segment endpoints.
          b) Pick the first pair where both nodes are in the graph.
          c) If none work, fall back to Haversine-nearest graph node.

        This makes the engine robust to any snapping/pruning artifact.
        """
        if not self._built or self.graph.number_of_edges() == 0:
            return {"status": "error", "message": "Graph not initialised — call /refresh first"}

        m_orig = self._segment_map.get(str(origin_id))
        m_dest = self._segment_map.get(str(dest_id))

        if not m_orig or not m_dest:
            return {"status": "error", "message": f"Segment {origin_id} or {dest_id} not in routable network"}

        # Try all 4 endpoint combinations; pick first where both nodes exist
        start, target = None, None
        for s_candidate in m_orig:
            for t_candidate in m_dest:
                if s_candidate in self.graph and t_candidate in self.graph:
                    if s_candidate != t_candidate:
                        start, target = s_candidate, t_candidate
                        break
            if start is not None:
                break

        # Fallback: nearest graph node to each segment's first coord
        if start is None:
            start = self._nearest_node(m_orig[0])
        if target is None:
            target = self._nearest_node(m_dest[0])

        if start is None or target is None or start == target:
            return {"status": "error", "message": "Cannot resolve routable nodes for these segments"}

        # Weight function: applies SARIMAX congestion multipliers
        congestion_penalty = {0: 1.0, 1: 1.0, 2: 2.8, 3: 8.0, 4: 40.0}

        def weight_func(u, v, d):
            sid     = d.get("segment_id", "")
            cong    = int((horizon_preds or {}).get(sid, 0))
            return d["weight"] * congestion_penalty.get(cong, 1.0)

        try:
            path = nx.astar_path(
                self.graph, start, target,
                heuristic=self._dist,
                weight=weight_func,
            )
        except nx.NetworkXNoPath:
            return {"status": "error", "message": "No physical path between these segments"}
        except nx.NodeNotFound as e:
            return {"status": "error", "message": f"Node not found in graph: {e}"}
        except Exception as e:
            logger.error(f"A* error: {e}")
            return {"status": "error", "message": f"Routing error: {str(e)}"}

        if len(path) < 2:
            return {"status": "error", "message": "A* returned degenerate path"}

        # Build GeoJSON segments from edge data
        route_segments = []
        total_cost     = 0.0
        for i in range(len(path) - 1):
            edge = self.graph[path[i]][path[i+1]]
            route_segments.append({
                "segment_id": edge["segment_id"],
                "geometry":   edge["geometry"],     # Shapely mapping() output
                "length_m":   edge.get("length_m", 0),
                "weight":     round(edge["weight"], 2),
            })
            total_cost += weight_func(path[i], path[i+1], edge)

        return {
            "status":     "success",
            "segments":   route_segments,
            "path_nodes": len(path),
            "est_time_s": round(total_cost, 1),
        }

    # ── Alternate route (avoids a specific segment) ──────────────────────────

    def get_alternate_path(
        self,
        origin_id:        str | int,
        dest_id:          str | int,
        avoid_segment_id: str | int | None = None,
    ) -> dict:
        """
        Returns a second route that avoids `avoid_segment_id`.
        Uses the same node-resolution logic as get_optimal_route_astar.
        """
        avoid_str = str(avoid_segment_id) if avoid_segment_id else None

        def weight_func_avoid(u, v, d):
            if avoid_str and d.get("segment_id") == avoid_str:
                return float("inf")
            return d["weight"]

        m_orig = self._segment_map.get(str(origin_id))
        m_dest = self._segment_map.get(str(dest_id))
        if not m_orig or not m_dest:
            return {"status": "error", "message": "Segments not routable"}

        start, target = None, None
        for s in m_orig:
            for t in m_dest:
                if s in self.graph and t in self.graph and s != t:
                    start, target = s, t; break
            if start: break

        if not start or not target:
            return {"status": "error", "message": "Cannot resolve nodes"}

        try:
            path = nx.astar_path(self.graph, start, target,
                                 heuristic=self._dist, weight=weight_func_avoid)
        except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
            return {"status": "error", "message": str(e)}

        segments = [
            {"segment_id": self.graph[path[i]][path[i+1]]["segment_id"],
             "geometry":   self.graph[path[i]][path[i+1]]["geometry"]}
            for i in range(len(path)-1)
        ]
        return {"status": "success", "segments": segments}

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "built":             self._built,
            "nodes":             self.graph.number_of_nodes(),
            "edges":             self.graph.number_of_edges(),
            "routable_segments": len(self._segment_map),
            "cache_info":        self._dist.cache_info()._asdict(),
        }

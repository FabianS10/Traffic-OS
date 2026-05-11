from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import engine
import logging

log = logging.getLogger("trafficos.spatial")

async def get_fusa_street_grid_with_traffic():
    """
    Genera un FeatureCollection GeoJSON optimizado directamente en la base de datos.
    Calcula el punto central exacto sobre la calzada para evitar puntos en edificios.
    """
    async with AsyncSession(engine) as session:
        query = text("""
            SELECT jsonb_build_object(
                'type',     'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            )
            FROM (
              SELECT jsonb_build_object(
                'type',       'Feature',
                'id',         s.id,
                'geometry',   ST_AsGeoJSON(s.geometry)::jsonb,
                'properties', jsonb_build_object(
                    'name', s.name,
                    'congestion', COALESCE(t.congestion_level, 1),
                    -- FIX: Punto exacto sobre la línea (0.5 = 50% del trayecto)
                    'center_lng', ST_X(ST_LineInterpolatePoint(s.geometry, 0.5)),
                    'center_lat', ST_Y(ST_LineInterpolatePoint(s.geometry, 0.5))
                )
              ) AS feature
              FROM road_segments s
              LEFT JOIN (
                  SELECT DISTINCT ON (segment_id) segment_id, congestion_level
                  FROM traffic_readings
                  ORDER BY segment_id, timestamp DESC
              ) t ON s.id = t.segment_id
            ) features;
        """)
        
        try:
            result = await session.execute(query)
            return result.scalar()
        except Exception as e:
            log.error(f"Error en consulta espacial (interpolación): {e}")
            return {"type": "FeatureCollection", "features": []}
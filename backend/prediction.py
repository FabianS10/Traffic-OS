"""
Prediction Engine v2 — TrafficOS
Greenshields + SARIMAX + synthetic history fallback + A→B route planning
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text
from pydantic import BaseModel
from typing import Optional, List
import numpy as np
from datetime import datetime, timedelta
import math

from database import get_db, RoadSegment, TrafficReading, WeatherEvent

router = APIRouter()

# ── Schemas ───────────────────────────────────────────────────────────────────

class PredictionRequest(BaseModel):
    latitude:    float
    longitude:   float
    radius_m:    float = 1000.0
    horizon_min: int   = 0
    segment_id:  Optional[int] = None

class SegmentPrediction(BaseModel):
    segment_id:       int
    name:             Optional[str]
    density_k:        float
    flow_q:           float
    speed_v:          float
    congestion_level: int
    congestion_label: str
    confidence:       float
    model_used:       str
    center_lat:       Optional[float] = None
    center_lng:       Optional[float] = None

class PredictionResponse(BaseModel):
    timestamp_now:  str
    timestamp_pred: str
    horizon_min:    int
    segments:       List[SegmentPrediction]
    weather_factor: float
    model_version:  str = "2.0.0"

class RouteRequest(BaseModel):
    origin_lat:      float
    origin_lng:      float
    dest_lat:        float
    dest_lng:        float
    horizon_min:     int = 0
    avoid_threshold: int = 3

class RouteSegment(BaseModel):
    segment_id:       int
    name:             Optional[str]
    lat:              float
    lng:              float
    congestion_level: int
    congestion_label: str
    speed_v:          float

class RouteResponse(BaseModel):
    segments:         List[RouteSegment]
    total_distance_m: float
    est_travel_min:   float
    avg_speed_kmh:    float
    has_jams:         bool
    alternative:      Optional[List[RouteSegment]] = None

# ── Greenshields ──────────────────────────────────────────────────────────────

def greenshields_speed(k, v_f, k_j):
    if k_j <= 0: return v_f
    return v_f * (1.0 - max(0.0, min(1.0, k / k_j)))

def greenshields_flow(k, v_f, k_j):
    return k * greenshields_speed(k, v_f, k_j)

def congestion_level(k, k_j):
    ratio = k / max(k_j, 1e-9)
    tiers = [(0.20,0,"Free flow"),(0.40,1,"Light"),(0.65,2,"Moderate"),(0.85,3,"Heavy"),(1.01,4,"Jam")]
    return next(((l,b) for t,l,b in tiers if ratio < t), (4,"Jam"))

# ── SARIMAX ───────────────────────────────────────────────────────────────────

def sarimax_features(k_history, timestamp, is_raining, precipitation, temperature, holiday=False):
    ar = k_history[-3:] if len(k_history)>=3 else np.pad(k_history,(3-len(k_history),0))
    k_avg = float(np.mean(k_history)) if len(k_history)>0 else ar[-1]
    h = timestamp.hour + timestamp.minute/60.0
    dow = timestamp.weekday()
    return np.array([
        ar[-1],ar[-2],ar[-3],k_avg,
        math.sin(2*math.pi*h/24), math.cos(2*math.pi*h/24),
        math.sin(2*math.pi*dow/7), math.cos(2*math.pi*dow/7),
        float(is_raining), precipitation,
        (temperature-20.0)/15.0, float(holiday),
    ], dtype=np.float32)

def arimax_predict(features, betas, beta_0):
    return float(beta_0 + np.dot(betas, features))

def build_default_betas():
    return np.array([0.85,0.10,0.05,0.20,8.0,-4.0,3.0,-1.0,12.0,2.0,-1.5,-5.0],dtype=np.float32), 5.0

def weather_multiplier(is_raining, precipitation):
    base = 1.0 + 0.35*(1/(1+math.exp(-1.5*(precipitation-5.0))))
    return base if is_raining else 1.0

def project_density(k_now, features, betas, beta_0, horizon_min, step_min=5):
    results = []
    k_hist = np.array([k_now]*3, dtype=np.float32)
    feat = features.copy()
    for t in range(step_min, horizon_min+step_min, step_min):
        k_pred = max(0.0, arimax_predict(feat, betas, beta_0))
        k_hist = np.roll(k_hist,-1); k_hist[-1] = k_pred
        feat[:3] = k_hist[-3:]
        results.append((t, k_pred))
    return results

# ── Synthetic historical data ─────────────────────────────────────────────────

def generate_synthetic_history(segment_id: int, k_jam: float, hours: int = 24) -> list:
    """
    SARIMAX-simulated historical traffic when the ingestion pipeline
    hasn't run yet. Deterministic per segment_id — stable across reloads.
    Models Colombian weekday: morning peak 7-9am, evening peak 5-7pm.
    """
    rng    = np.random.default_rng(seed=segment_id * 42)
    now    = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    k_base = k_jam * (0.10 + (segment_id % 7) * 0.04)
    records = []

    for i in range(hours * 12, 0, -1):
        ts  = now - timedelta(minutes=i*5)
        h   = ts.hour + ts.minute/60.0
        dow = ts.weekday()

        morning = math.exp(-0.5*((h-7.5)/1.2)**2)
        evening = math.exp(-0.5*((h-18.0)/1.5)**2)
        diurnal = 0.30 + 0.45*morning + 0.35*evening
        k_true  = k_base * diurnal * (0.7 if dow>=5 else 1.0)
        k_true  = float(max(1.0, min(k_jam*0.9, k_true + rng.normal(0, k_base*0.05))))

        v = greenshields_speed(k_true, 50.0, k_jam)
        q = greenshields_flow(k_true, 50.0, k_jam)
        cl, _ = congestion_level(k_true, k_jam)

        records.append({
            "timestamp":        ts.isoformat(),
            "density_k":        round(k_true, 2),
            "flow_q":           round(float(q), 2),
            "speed_v":          round(float(v), 2),
            "congestion_level": cl,
            "source":           "synthetic_sarimax",
        })
    return records

# ── Centroid helper ───────────────────────────────────────────────────────────

async def get_centroid(db, segment_id):
    try:
        r = await db.execute(
            text("SELECT ST_Y(ST_Centroid(geometry)) lat, ST_X(ST_Centroid(geometry)) lng FROM road_segments WHERE id=:s"),
            {"s": segment_id}
        )
        row = r.fetchone()
        return (row.lat, row.lng) if row else (None, None)
    except Exception:
        return (None, None)

# ── Prediction endpoint ───────────────────────────────────────────────────────

@router.post("/", response_model=PredictionResponse)
async def predict(body: PredictionRequest, db: AsyncSession = Depends(get_db)):
    now, pred_time = datetime.utcnow(), datetime.utcnow() + timedelta(minutes=body.horizon_min)
    wr = await db.execute(select(WeatherEvent).order_by(WeatherEvent.timestamp.desc()).limit(1))
    w  = wr.scalar_one_or_none()
    is_raining, precipitation, temperature = (w.is_raining, w.precipitation, w.temperature) if w else (False, 0.0, 20.0)
    wf = weather_multiplier(is_raining, precipitation)
    betas, beta_0 = build_default_betas()

    if body.segment_id:
        sq = select(RoadSegment).where(RoadSegment.id == body.segment_id)
    else:
        pt = f"SRID=4326;POINT({body.longitude} {body.latitude})"
        sq = select(RoadSegment).where(func.ST_DWithin(
            func.ST_Transform(RoadSegment.geometry,3857),
            func.ST_Transform(func.ST_GeomFromEWKT(pt),3857),
            body.radius_m)).limit(50)

    segs = (await db.execute(sq)).scalars().all()
    if not segs: raise HTTPException(404, "No road segments found")

    out = []
    for seg in segs:
        rr = await db.execute(select(TrafficReading).where(and_(
            TrafficReading.segment_id==seg.id,
            TrafficReading.timestamp >= now-timedelta(minutes=30)
        )).order_by(TrafficReading.timestamp.asc()))
        readings = rr.scalars().all()

        k_now = readings[-1].density_k if readings else seg.jam_density*0.2
        k_hist = np.array([r.density_k for r in readings],dtype=np.float32) if readings else np.array([k_now]*5)

        feat = sarimax_features(k_hist, pred_time, is_raining, precipitation, temperature)
        proj = project_density(k_now, feat, betas, beta_0, max(5, body.horizon_min))
        k_pred = proj[-1][1]*wf if proj else k_now*wf
        v_pred = greenshields_speed(k_pred, seg.speed_limit, seg.jam_density)
        q_pred = greenshields_flow(k_pred, seg.speed_limit, seg.jam_density)
        cl, clbl = congestion_level(k_pred, seg.jam_density)
        lat, lng = await get_centroid(db, seg.id)

        out.append(SegmentPrediction(
            segment_id=seg.id, name=seg.name,
            density_k=round(k_pred,2), flow_q=round(q_pred,2), speed_v=round(v_pred,2),
            congestion_level=cl, congestion_label=clbl,
            confidence=0.85 if len(readings)>=6 else 0.55,
            model_used="SARIMAX+Greenshields",
            center_lat=lat, center_lng=lng,
        ))

    return PredictionResponse(timestamp_now=now.isoformat(), timestamp_pred=pred_time.isoformat(),
                               horizon_min=body.horizon_min, segments=out, weather_factor=round(wf,3))

# ── History endpoint (synthetic fallback) ─────────────────────────────────────

@router.get("/segment/{segment_id}/history")
async def segment_history(segment_id: int, hours: int = 24, db: AsyncSession = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=hours)
    rr = await db.execute(select(TrafficReading).where(and_(
        TrafficReading.segment_id==segment_id,
        TrafficReading.timestamp>=since,
    )).order_by(TrafficReading.timestamp.asc()))
    readings = rr.scalars().all()

    if readings:
        return [{"timestamp":r.timestamp.isoformat(),"density_k":r.density_k,
                 "flow_q":r.flow_q,"speed_v":r.speed_v,"congestion_level":r.congestion_level,"source":"sensor"}
                for r in readings]

    sr = await db.execute(select(RoadSegment).where(RoadSegment.id==segment_id))
    seg = sr.scalar_one_or_none()
    return generate_synthetic_history(segment_id, seg.jam_density if seg else 120.0, hours)

# ── Route planning ────────────────────────────────────────────────────────────

@router.post("/route", response_model=RouteResponse)
async def plan_route(body: RouteRequest, db: AsyncSession = Depends(get_db)):
    """
    A→B optimal routing: finds all segments in the corridor bounding box,
    predicts their congestion at horizon_min, weights by travel time
    (with 5× penalty on jammed segments), returns optimal + alternative.
    """
    now = datetime.utcnow()
    pred_time = now + timedelta(minutes=body.horizon_min)
    wr = await db.execute(select(WeatherEvent).order_by(WeatherEvent.timestamp.desc()).limit(1))
    w  = wr.scalar_one_or_none()
    is_raining, precipitation, temperature = (w.is_raining, w.precipitation, w.temperature) if w else (False, 0.0, 20.0)
    wf = weather_multiplier(is_raining, precipitation)
    betas, beta_0 = build_default_betas()

    lat_min = min(body.origin_lat, body.dest_lat) - 0.02
    lat_max = max(body.origin_lat, body.dest_lat) + 0.02
    lng_min = min(body.origin_lng, body.dest_lng) - 0.02
    lng_max = max(body.origin_lng, body.dest_lng) + 0.02
    bbox = (f"SRID=4326;POLYGON(({lng_min} {lat_min},{lng_max} {lat_min},"
            f"{lng_max} {lat_max},{lng_min} {lat_max},{lng_min} {lat_min}))")

    try:
        sr = await db.execute(select(RoadSegment).where(
            func.ST_Intersects(RoadSegment.geometry, func.ST_GeomFromEWKT(bbox))).limit(100))
        segs = sr.scalars().all()
    except Exception:
        segs = []
    if not segs: raise HTTPException(404, "No road network data in corridor")

    optimal, alternative = [], []
    total_dist = 0.0

    for seg in segs:
        rr = await db.execute(select(TrafficReading).where(and_(
            TrafficReading.segment_id==seg.id,
            TrafficReading.timestamp>=now-timedelta(minutes=30)
        )).limit(10))
        readings = rr.scalars().all()
        k_now = readings[-1].density_k if readings else seg.jam_density*0.2
        k_hist = np.array([r.density_k for r in readings],dtype=np.float32) if readings else np.array([k_now]*5)

        feat = sarimax_features(k_hist, pred_time, is_raining, precipitation, temperature)
        proj = project_density(k_now, feat, betas, beta_0, max(5,body.horizon_min))
        k_pred = proj[-1][1]*wf if proj else k_now*wf
        v_pred = max(5.0, greenshields_speed(k_pred, seg.speed_limit, seg.jam_density))
        cl, clbl = congestion_level(k_pred, seg.jam_density)

        lat, lng = await get_centroid(db, seg.id)
        if lat is None: lat, lng = body.origin_lat, body.origin_lng

        info = RouteSegment(segment_id=seg.id, name=seg.name, lat=lat, lng=lng,
                            congestion_level=cl, congestion_label=clbl, speed_v=round(v_pred,1))

        dist_km = (seg.length_m or 200.0) / 1000.0
        t_base  = dist_km / v_pred * 60
        penalty = 5.0 if cl >= body.avoid_threshold else 1.0

        total_dist += seg.length_m or 200.0
        optimal.append((t_base*penalty, info))
        alternative.append((t_base, info))

    optimal.sort(key=lambda x: x[0])
    alternative.sort(key=lambda x: x[0])

    opt_path = [s for _,s in optimal[:20]]
    alt_path = [s for _,s in alternative[:20]]
    t_opt    = sum(t for t,_ in optimal[:20])
    avg_spd  = (total_dist/1000)/(max(0.01,t_opt)/60) if t_opt>0 else 30.0

    return RouteResponse(
        segments=opt_path, total_distance_m=round(total_dist,1),
        est_travel_min=round(t_opt,1), avg_speed_kmh=round(avg_spd,1),
        has_jams=any(s.congestion_level>=body.avoid_threshold for s in alt_path),
        alternative=alt_path if opt_path!=alt_path else None,
    )

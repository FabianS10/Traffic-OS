import os
import httpx

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "RcF9O1ynpWUk0IJCaMzNGvXT9aoHbkeQ").strip()

CITY_POINTS = {
    "fusagasuga": [
        (4.3379, -74.3649, "Calle 18"),
        (4.3358, -74.3671, "Carrera 7"),
        (4.3441, -74.3705, "Avenida Las Palmas"),
    ],
    "san_francisco": [
        (37.7749, -122.4194, "Market Street"),
        (37.7840, -122.4075, "Union Square"),
        (37.7890, -122.4010, "Financial District"),
    ],
}


def normalize_city(city: str) -> str:
    city = (city or "fusagasuga").lower().strip()
    if city in {"sf", "san francisco", "san_francisco"}:
        return "san_francisco"
    return "fusagasuga"


def congestion_from_speed(current_speed: float, free_flow_speed: float) -> int:
    if free_flow_speed <= 0:
        return 0

    ratio = current_speed / free_flow_speed

    if ratio >= 0.85:
        return 0
    if ratio >= 0.65:
        return 1
    if ratio >= 0.45:
        return 2
    if ratio >= 0.25:
        return 3
    return 4


def status_from_level(level: int) -> str:
    return ["Free Flow", "Light", "Moderate", "Heavy", "Jam"][max(0, min(level, 4))]


async def get_tomtom_live_map_data(city: str = "fusagasuga"):
    if not TOMTOM_API_KEY:
        return {
            "city": city,
            "mode": "tomtom-live-missing-key",
            "is_real_traffic": False,
            "segments": [],
            "features": [],
            "error": "TOMTOM_API_KEY is missing on backend.",
        }

    city_key = normalize_city(city)
    points = CITY_POINTS[city_key]

    segments = []
    features = []

    async with httpx.AsyncClient(timeout=12.0) as client:
        for idx, (lat, lon, name) in enumerate(points, start=1):
            url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

            params = {
                "point": f"{lat},{lon}",
                "unit": "KMPH",
                "key": TOMTOM_API_KEY,
            }

            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                fsd = data.get("flowSegmentData", {})

                current_speed = float(fsd.get("currentSpeed", 0) or 0)
                free_flow_speed = float(fsd.get("freeFlowSpeed", current_speed or 1) or 1)
                confidence = float(fsd.get("confidence", 0) or 0)

                coords_raw = fsd.get("coordinates", {}).get("coordinate", [])

                coordinates = []
                for c in coords_raw:
                    if "longitude" in c and "latitude" in c:
                        coordinates.append([float(c["longitude"]), float(c["latitude"])])

                if len(coordinates) < 2:
                    coordinates = [
                        [lon - 0.0006, lat - 0.0003],
                        [lon + 0.0006, lat + 0.0003],
                    ]

                level = congestion_from_speed(current_speed, free_flow_speed)

                density_k = max(0.0, 120.0 * (1.0 - current_speed / max(free_flow_speed, 1)))
                flow_q = density_k * current_speed

                segment = {
                    "id": idx,
                    "name": name,
                    "speed_v": round(current_speed, 1),
                    "free_flow_speed": round(free_flow_speed, 1),
                    "density_k": round(density_k, 1),
                    "flow_q": round(flow_q, 0),
                    "congestion_level": level,
                    "status": status_from_level(level),
                    "confidence": confidence,
                    "geometry": coordinates,
                    "source": "tomtom_live",
                    "is_real_traffic": True,
                }

                feature = {
                    "type": "Feature",
                    "properties": segment,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates,
                    },
                }

                segments.append(segment)
                features.append(feature)

            except Exception as e:
                print(f"TomTom fetch failed for {name}: {e}")

    avg_speed = round(sum(s["speed_v"] for s in segments) / len(segments), 1) if segments else 0
    jam_count = sum(1 for s in segments if s["congestion_level"] >= 3)

    return {
        "city": city_key,
        "mode": "tomtom-live",
        "source": "TomTom Traffic Flow Segment Data",
        "is_real_traffic": True,
        "type": "FeatureCollection",
        "features": features,
        "segments": segments,
        "stats": {
            "segments": len(segments),
            "avg_speed": avg_speed,
            "jams": jam_count,
        },
    }
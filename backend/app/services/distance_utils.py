import math
from typing import Optional, Tuple

def get_haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000  # Radius of earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def estimate_drive_time_minutes(lot1, lot2) -> int:
    if not (lot1.lat and lot1.lng and lot2.lat and lot2.lng):
        return 2
    dist_m = get_haversine_distance(lot1.lat, lot1.lng, lot2.lat, lot2.lng)
    speed_mps = 20 * (1000 / 3600)  # 20 km/h in m/s
    time_min = dist_m / speed_mps / 60
    return max(2, int(time_min + 1))

def get_bay_distance_to_building(bay, building) -> float:
    """Straight-line lot -> building distance (metres), inf when unlocated."""
    if not building or not getattr(building, "lat", None) or not getattr(building, "lng", None):
        return float('inf')
    if bay.lot and bay.lot.lat and bay.lot.lng:
        return get_haversine_distance(bay.lot.lat, bay.lot.lng, building.lat, building.lng)
    return float('inf')


# Each grid cell of the SVG bay layout is treated as ~6 m (bay + share of aisle).
# It is an *estimate* for ranking only; the UI labels it as such.
GRID_CELL_METERS = 6.0


def estimate_walk_meters(bay, destination_building=None) -> float:
    """Estimated walking distance from `bay` to a destination building.

    = lot -> building straight line + offset of the bay from the lot entrance
      (entrance assumed at grid cell 0,0).

    Falls back to the bay's own `nearest_building` when no destination was
    given, so ranking still differentiates bays within one lot.
    """
    target = destination_building or getattr(bay, "nearest_building", None)
    base = 0.0
    if target is not None:
        d = get_bay_distance_to_building(bay, target)
        if d != float('inf'):
            base = d
    offset = math.hypot(bay.x or 0, bay.y or 0) * GRID_CELL_METERS
    return base + offset

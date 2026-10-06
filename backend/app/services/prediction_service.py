from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.db.models import Lot, Bay, BayState, Allotment, AllotmentStatus, utcnow

def get_historical_hourly_arrivals(db: Session, lot_id: str, day_of_week: int) -> Dict[int, float]:
    """
    Computes average arrivals per hour (0-23) for a lot on a given weekday (0=Monday, 6=Sunday).
    Computed directly from completed historical allotments.
    """
    # Find all completed allotments for bays belonging to this lot
    # Group by date and hour to get counts per day-hour, then average across distinct days
    allotments = db.query(
        Allotment.arrived_at
    ).join(Bay, Allotment.bay_id == Bay.id).filter(
        Bay.lot_id == lot_id,
        Allotment.arrived_at.isnot(None),
        Allotment.status == AllotmentStatus.completed
    ).all()
    
    # Bucket by (date, hour)
    day_counts: Dict[datetime.date, Dict[int, int]] = {}
    for (arr,) in allotments:
        if arr is None:
            continue
        # Check weekday
        if arr.weekday() == day_of_week:
            dt_date = arr.date()
            hr = arr.hour
            if dt_date not in day_counts:
                day_counts[dt_date] = {h: 0 for h in range(24)}
            day_counts[dt_date][hr] += 1
            
    num_days = len(day_counts)
    hourly_avg: Dict[int, float] = {h: 0.0 for h in range(24)}
    
    if num_days > 0:
        for d_date, hrs in day_counts.items():
            for h, count in hrs.items():
                hourly_avg[h] += count
        for h in range(24):
            hourly_avg[h] = round(hourly_avg[h] / num_days, 2)
    else:
        # If no days match this exact weekday, check all weekdays vs weekends
        is_weekend = day_of_week >= 5
        general_days: Dict[datetime.date, Dict[int, int]] = {}
        for (arr,) in allotments:
            if arr is None:
                continue
            if (arr.weekday() >= 5) == is_weekend:
                dt_date = arr.date()
                hr = arr.hour
                if dt_date not in general_days:
                    general_days[dt_date] = {h: 0 for h in range(24)}
                general_days[dt_date][hr] += 1
        gen_num_days = len(general_days)
        if gen_num_days > 0:
            for d_date, hrs in general_days.items():
                for h, count in hrs.items():
                    hourly_avg[h] += count
            for h in range(24):
                hourly_avg[h] = round(hourly_avg[h] / gen_num_days, 2)
                
    return hourly_avg

def predict_lot_fill_time(
    db: Session,
    lot_id: str,
    current_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Predicts the time when a lot will reach 100% capacity using an empirical
    hourly arrival projection heuristic.
    """
    if current_time is None:
        current_time = utcnow()
        
    lot = db.query(Lot).filter(Lot.id == lot_id).first()
    if not lot:
        return {"error": "Lot not found"}
        
    # Count current occupied + allotted bays
    occupied_or_allotted = db.query(Bay).filter(
        Bay.lot_id == lot_id,
        Bay.state.in_([BayState.occupied, BayState.allotted])
    ).count()
    
    capacity = lot.capacity
    remaining_bays = max(0, capacity - occupied_or_allotted)
    occupancy_pct = round((occupied_or_allotted / capacity) * 100, 1) if capacity > 0 else 100.0
    
    if remaining_bays == 0:
        return {
            "lot_id": lot.id,
            "lot_name": lot.name,
            "capacity": capacity,
            "current_occupancy": occupied_or_allotted,
            "occupancy_pct": occupancy_pct,
            "is_full_now": True,
            "predicted_fill_time": current_time.strftime("%H:%M"),
            "minutes_until_full": 0,
            "warning_message": f"{lot.name} is currently FULL (100% capacity)",
            "confidence": "high",
            "confidence_note": "Observed real-time state: 0 bays remaining",
            "method": "realtime_occupancy_observation",
            "heuristic_label": "Direct Observation (Lot Full)"
        }
        
    # Get hourly arrival rate for this weekday
    day_of_week = current_time.weekday()
    hourly_rate = get_historical_hourly_arrivals(db, lot_id, day_of_week)
    
    # Project forward minute by minute or hour by hour
    curr_hour = current_time.hour
    curr_min = current_time.minute
    
    accumulated_arrivals = 0.0
    minutes_elapsed = 0
    max_projection_hours = 12
    found_fill_time = None
    
    # First, handle the remaining part of current hour
    rem_min_in_hour = 60 - curr_min
    cur_hourly_rate = hourly_rate.get(curr_hour, 0.0)
    cur_rate_per_min = cur_hourly_rate / 60.0
    
    # Check if fills within current hour
    if cur_rate_per_min > 0 and (cur_rate_per_min * rem_min_in_hour) >= remaining_bays:
        mins_needed = int(remaining_bays / cur_rate_per_min)
        target_dt = current_time + timedelta(minutes=mins_needed)
        found_fill_time = target_dt
        minutes_elapsed = mins_needed
    else:
        accumulated_arrivals += (cur_rate_per_min * rem_min_in_hour)
        minutes_elapsed += rem_min_in_hour
        
        # Subsequent hours
        h = (curr_hour + 1) % 24
        hours_checked = 1
        while hours_checked < max_projection_hours and (remaining_bays - accumulated_arrivals) > 0:
            rate = hourly_rate.get(h, 0.0)
            if rate <= 0:
                # Minimal background trickle to avoid infinite loop
                rate = 0.5
            if (accumulated_arrivals + rate) >= remaining_bays:
                rem_needed = remaining_bays - accumulated_arrivals
                rate_per_min = rate / 60.0
                mins_in_h = int(rem_needed / rate_per_min)
                target_dt = current_time + timedelta(minutes=minutes_elapsed + mins_in_h)
                found_fill_time = target_dt
                minutes_elapsed += mins_in_h
                break
            else:
                accumulated_arrivals += rate
                minutes_elapsed += 60
                h = (h + 1) % 24
                hours_checked += 1

    # Confidence calculation:
    # Based on remaining bays and projection horizon
    if minutes_elapsed <= 60:
        confidence = "high"
        conf_note = "High confidence: historical morning rush patterns exhibit low variance within 1 hour."
    elif minutes_elapsed <= 180:
        confidence = "medium"
        conf_note = "Medium confidence: multi-hour projection subject to weather and schedule variation."
    else:
        confidence = "low"
        conf_note = "Low confidence: extended horizon projection with lower sample certainty."
        
    predicted_str = found_fill_time.strftime("%H:%M") if found_fill_time else "Late Afternoon"
    
    return {
        "lot_id": lot.id,
        "lot_name": lot.name,
        "capacity": capacity,
        "current_occupancy": occupied_or_allotted,
        "occupancy_pct": occupancy_pct,
        "is_full_now": False,
        "predicted_fill_time": predicted_str,
        "minutes_until_full": minutes_elapsed if found_fill_time else None,
        "warning_message": f"{lot.name} likely full by {predicted_str}" if found_fill_time and minutes_elapsed <= 120 else f"{lot.name} has ample availability ({remaining_bays} bays free)",
        "confidence": confidence,
        "confidence_note": conf_note,
        "method": "empirical_hourly_arrival_rate_projection",
        "heuristic_label": "Statistical Heuristic (Hourly Historical Average)"
    }

def predict_all_lots(db: Session, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
    lots = db.query(Lot).all()
    results = []
    for lot in lots:
        pred = predict_lot_fill_time(db, lot.id, current_time=current_time)
        results.append(pred)
    return results

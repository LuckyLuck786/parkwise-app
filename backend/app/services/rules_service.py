"""Rules service.

The `rules` table stores tunable policy values. Each row is
`key` + `value` (JSON, usually `{"value": ..., "description": ...}`).

All services read rules through this module so a value edited by an admin
takes effect without a code change, and so tests can run without seeded rules.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Rule

# Default policy values. These mirror scripts/seed.py DEFAULT_RULES.
DEFAULTS: Dict[str, Any] = {
    "tier1_quota_pct": 10,
    "tier2_quota_pct": 15,
    "grace_period_minutes": 10,
    "tier2_cutoff_hour": 10,
    "waitlist_offer_minutes": 5,
    "prediction_warning_minutes": 30,
    "heartbeat_timeout_seconds": 120,
    "accessible_reserved_for_tier1": True,
    "low_confidence_threshold": 0.6,
}

DESCRIPTIONS: Dict[str, str] = {
    "tier1_quota_pct": "Percentage of bays reserved for Tier 1 (accessible)",
    "tier2_quota_pct": "Percentage of bays reserved for Tier 2 until cutoff",
    "grace_period_minutes": "Minutes to arrive after allotment before no-show release",
    "tier2_cutoff_hour": "Hour (24h) after which Tier 2 reserved bays open to all",
    "waitlist_offer_minutes": "Minutes to accept a waitlist offer before it expires",
    "prediction_warning_minutes": "Minutes before predicted full to show warning",
    "heartbeat_timeout_seconds": "Seconds without heartbeat before device marked offline",
    "accessible_reserved_for_tier1": "If true, accessible bays are only allotted to Tier 1 / needs_accessible",
    "low_confidence_threshold": "Confidence below which a bay is shown with a low-confidence badge",
}


def _unwrap(raw: Any, fallback: Any) -> Any:
    """Rules are stored as {"value": x, "description": y}; tolerate a bare value."""
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    if raw is None:
        return fallback
    return raw


def get_rule(db: Session, key: str, default: Optional[Any] = None) -> Any:
    """Fetch a single rule value, falling back to code default."""
    if default is None:
        default = DEFAULTS.get(key)
    row = db.query(Rule).filter(Rule.key == key).first()
    if row is None:
        return default
    return _unwrap(row.value, default)


def get_rules(db: Session) -> Dict[str, Any]:
    """Return every known rule (seeded rows merged over code defaults)."""
    out = dict(DEFAULTS)
    for row in db.query(Rule).all():
        out[row.key] = _unwrap(row.value, DEFAULTS.get(row.key))
    return out


def set_rules(db: Session, updates: Dict[str, Any], actor: str = "admin") -> Dict[str, Any]:
    """Persist rule updates (idempotent), audit-log the change, return new set."""
    for key, value in updates.items():
        row = db.query(Rule).filter(Rule.key == key).first()
        if row is None:
            db.add(
                Rule(
                    key=key,
                    value={"value": value, "description": DESCRIPTIONS.get(key, "")},
                    description=DESCRIPTIONS.get(key, ""),
                )
            )
        else:
            merged = dict(row.value) if isinstance(row.value, dict) else {}
            merged["value"] = value
            row.value = merged
            if not row.description:
                row.description = DESCRIPTIONS.get(key, "")
    db.add(
        AuditLog(
            actor=actor,
            action="rules_updated",
            details={"updates": updates},
        )
    )
    db.commit()
    return get_rules(db)

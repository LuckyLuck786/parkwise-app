"""Notification service.

Interface with one real channel (in-app, persisted) and two clearly-marked
simulated channel stubs (sms, telegram).

The stubs never claim delivery: they log that a real provider would be called.
Wire a provider in `SMSChannel.send` / `TelegramChannel.send` later without
touching callers.
"""
import logging
from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Notification, NotificationChannel, utcnow

logger = logging.getLogger("parkwise.notifications")


class NotificationChannelBase:
    """A channel knows how to deliver one message to one user."""

    name: str = "base"
    simulated: bool = False

    def send(self, db: Session, user_id: str, message: str, ts: Optional[datetime] = None) -> bool:
        raise NotImplementedError


class InAppChannel(NotificationChannelBase):
    """Real channel: persisted row surfaced by GET /api/v1/notifications."""

    name = "in_app"
    simulated = False

    def send(self, db: Session, user_id: str, message: str, ts: Optional[datetime] = None) -> bool:
        db.add(
            Notification(
                user_id=user_id,
                message=message,
                channel=NotificationChannel.in_app,
                ts=ts or utcnow(),
                read=False,
            )
        )
        db.commit()
        return True


class SMSChannel(NotificationChannelBase):
    """SIMULATED stub — no SMS is ever sent. Logs what would be sent."""

    name = "sms"
    simulated = True

    def send(self, db: Session, user_id: str, message: str, ts: Optional[datetime] = None) -> bool:
        logger.warning("[SIMULATED SMS — NOT DELIVERED] user=%s message=%r", user_id, message)
        return True


class TelegramChannel(NotificationChannelBase):
    """SIMULATED stub — no Telegram message is ever sent."""

    name = "telegram"
    simulated = True

    def send(self, db: Session, user_id: str, message: str, ts: Optional[datetime] = None) -> bool:
        logger.warning("[SIMULATED TELEGRAM — NOT DELIVERED] user=%s message=%r", user_id, message)
        return True


CHANNELS = {
    "in_app": InAppChannel(),
    "sms": SMSChannel(),
    "telegram": TelegramChannel(),
}


def notify(
    db: Session,
    user_id: str,
    message: str,
    channels: Iterable[str] = ("in_app",),
    ts: Optional[datetime] = None,
) -> List[str]:
    """Deliver `message` on each requested channel. Returns channel names used.

    Default is the in-app channel only; simulated channels are opt-in and only
    ever log.
    """
    delivered: List[str] = []
    for name in channels:
        channel = CHANNELS.get(name)
        if channel is None:
            logger.warning("Unknown notification channel %r skipped", name)
            continue
        if channel.send(db, user_id, message, ts):
            delivered.append(name)
    return delivered


def list_notifications(db: Session, user_id: str, limit: int = 100) -> List[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.ts.desc())
        .limit(limit)
        .all()
    )


def mark_read(db: Session, user_id: str, notification_id: str) -> bool:
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if note is None:
        return False
    note.read = True
    db.commit()
    return True

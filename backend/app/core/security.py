"""Password hashing, JWT issue/verify and FastAPI auth dependencies."""
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Union

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt

from app.core.config import settings
from app.db.database import get_db
from app.db.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Return the subject (user id) or None when the token is invalid/expired."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        sub = payload.get("sub")
        return str(sub) if sub else None
    except Exception:
        return None


def get_current_user(
    db=Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    """Authenticated user or 401."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    subject = decode_token(token)
    if not subject:
        raise credentials_error
    user = db.query(User).filter(User.id == subject).first()
    if user is None:
        raise credentials_error
    return user


def get_optional_user(
    db=Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    """Authenticated user when a valid token is supplied, else None (public routes)."""
    if not token:
        return None
    subject = decode_token(token)
    if not subject:
        return None
    return db.query(User).filter(User.id == subject).first()


def require_roles(*roles: Union[UserRole, str]):
    """Dependency factory: allow only the given roles."""

    allowed = {r.value if isinstance(r, UserRole) else str(r) for r in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {'/'.join(sorted(allowed))}",
            )
        return user

    return dependency


# Reusable role guards
require_admin = require_roles(UserRole.admin)
require_staff = require_roles(UserRole.admin, UserRole.gate_operator)

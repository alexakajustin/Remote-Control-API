"""
Authentication module for RustDesk API Server.
JWT token creation/validation and password hashing compatible with RustDesk client.
"""

import hashlib
import hmac
import json
import base64
import time
import secrets


# Secret key for JWT signing — generated on first run, persisted in DB config
JWT_SECRET = secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 86400 * 30  # 30 days


def hash_password(password: str) -> str:
    """Hash a password using SHA256 with a random salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, hashed = password_hash.split(":", 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except (ValueError, AttributeError):
        return False


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt(payload: dict, secret: str = None, expiry: int = None) -> str:
    """Create a simple JWT token."""
    secret = secret or JWT_SECRET
    expiry = expiry or JWT_EXPIRY

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    now = time.time()
    payload = {
        **payload,
        "iat": int(now),
        "exp": int(now + expiry),
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{message}.{signature_b64}"


def decode_jwt(token: str, secret: str = None) -> dict:
    """Decode and verify a JWT token. Returns payload dict or None if invalid."""
    secret = secret or JWT_SECRET
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
        actual_sig = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # Decode payload
        payload = json.loads(_base64url_decode(payload_b64))

        # Check expiry
        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


def extract_token_from_header(authorization: str) -> str:
    """Extract token from Authorization header (Bearer <token>)."""
    if not authorization:
        return ""
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return authorization

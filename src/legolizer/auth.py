"""Google sign-in: ID token verification, opaque session tokens and the session cookie."""

from __future__ import annotations

import hashlib
import os
import secrets

GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
SESSION_SECONDS = 30 * 24 * 3600
COOKIE = "lgz_session"
# Browsers accept __Host- cookies only with Secure, Path=/ and no Domain, so a sibling
# subdomain cannot plant one; plain-HTTP loopback development uses the unprefixed name.
SECURE_COOKIE = "__Host-lgz_session"
LOCAL_USER = {"id": "local", "name": "Local workspace", "picture": None}

_certs = None


def mode():
    value = os.getenv("LEGOLIZER_AUTH", "off").lower()
    if value not in ("off", "google"):
        raise RuntimeError("LEGOLIZER_AUTH must be off or google.")
    return value


def client_id():
    return os.getenv("LEGOLIZER_GOOGLE_CLIENT_ID") or None


def is_admin_email(email):
    admins = {
        address.strip().lower()
        for address in os.getenv("LEGOLIZER_ADMIN_EMAILS", "").split(",")
        if address.strip()
    }
    return bool(email) and email.strip().lower() in admins


def configuration_problem():
    try:
        google = mode() == "google"
    except RuntimeError as exc:
        return str(exc)
    if google and not client_id():
        return "LEGOLIZER_AUTH=google needs LEGOLIZER_GOOGLE_CLIENT_ID."
    return None


def verify_google(credential):
    """Return the claims of a valid Google ID token for this app; ValueError otherwise."""
    import jwt

    global _certs
    audience = client_id()
    if not audience:
        raise RuntimeError("Set LEGOLIZER_GOOGLE_CLIENT_ID to enable Google sign-in.")
    if _certs is None:
        _certs = jwt.PyJWKClient(GOOGLE_CERTS, cache_keys=True, timeout=10)
    try:
        key = _certs.get_signing_key_from_jwt(credential)
    except jwt.PyJWKClientConnectionError as exc:
        raise RuntimeError("Google sign-in is unavailable. Try again shortly.") from exc
    except jwt.PyJWTError as exc:
        raise ValueError("Google sign-in could not be verified.") from exc
    try:
        claims = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Google sign-in could not be verified.") from exc
    if claims.get("email_verified") not in (True, "true"):
        raise ValueError("Verify your Google account's email address, then sign in again.")
    return claims


def profile(claims):
    return {
        "id": f"google-{claims['sub']}",
        "email": claims.get("email", ""),
        "name": (claims.get("given_name") or claims.get("name") or "Builder")[:80],
        "picture": claims.get("picture"),
    }


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_name(secure):
    return SECURE_COOKIE if secure else COOKIE


def read_cookie(header, secure):
    # Not http.cookies.SimpleCookie: it stops at the first value it cannot parse, such as
    # the JSON in Google Identity Services' g_state cookie, and drops every later cookie.
    name = cookie_name(secure)
    for part in (header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None


def set_cookie(token, secure):
    attributes = f"Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_SECONDS}"
    return f"{cookie_name(secure)}={token}; {attributes}" + ("; Secure" if secure else "")


def clear_cookie(secure):
    return f"{cookie_name(secure)}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" + (
        "; Secure" if secure else ""
    )

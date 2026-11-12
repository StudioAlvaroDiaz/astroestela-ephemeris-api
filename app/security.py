"""Autenticación por firma HMAC-SHA256.

El secreto nunca viaja por la red: WordPress firma cada petición y la API
comprueba la firma. Una firma solo vale durante `max_clock_skew` segundos.

Cadena firmada (líneas separadas por \\n):
    <timestamp unix>
    <MÉTODO HTTP>
    <ruta con query string, tal como se envía>
    <sha256 hex del cuerpo; cuerpo vacío = sha256 de "">

Cabeceras: X-Astro-Timestamp, X-Astro-Signature (hex en minúsculas).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request


def canonical_string(timestamp: str, method: str, path_qs: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return f"{timestamp}\n{method.upper()}\n{path_qs}\n{body_hash}".encode()


def sign(secret: str, timestamp: str, method: str, path_qs: str, body: bytes) -> str:
    return hmac.new(secret.encode(), canonical_string(timestamp, method, path_qs, body), hashlib.sha256).hexdigest()


def _unauthorized() -> HTTPException:
    # Mismo mensaje para todos los fallos: no damos pistas a quien prueba.
    return HTTPException(status_code=401, detail="Unauthorized")


async def verify_request(request: Request) -> None:
    settings = request.app.state.settings
    ts = request.headers.get("x-astro-timestamp", "")
    signature = request.headers.get("x-astro-signature", "").lower()
    if not ts.isdigit() or not signature:
        raise _unauthorized()
    if abs(time.time() - int(ts)) > settings.max_clock_skew:
        raise _unauthorized()

    path_qs = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    body = await request.body()
    for secret in settings.hmac_secrets:
        expected = sign(secret, ts, request.method, path_qs, body)
        if hmac.compare_digest(expected, signature):
            return
    raise _unauthorized()

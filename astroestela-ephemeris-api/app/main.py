"""API de efemérides y carta natal de astroestela.com.

Copyright (C) 2026 Studio Álvaro Díaz. Publicado bajo GNU AGPL v3 o posterior.
Usa Swiss Ephemeris, Copyright (C) 1997-2021 Astrodienst AG, Suiza (AGPL).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import get_settings
from .engine import HOUSE_SYSTEMS, ChartError, Engine
from .security import verify_request

log = logging.getLogger("ephemeris")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate()
    app.state.settings = settings
    app.state.engine = Engine(str(settings.ephe_path), settings.allow_moshier)
    log.info("Motor listo: %s", app.state.engine.engine_name)
    yield


app = FastAPI(
    title="astroestela ephemeris API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def source_header(request: Request, call_next):
    response = await call_next(request)
    # AGPL §13: quien usa el servicio por red puede obtener su código fuente.
    response.headers["X-Source-Code"] = request.app.state.settings.source_url
    response.headers["Cache-Control"] = "no-store"
    return response


# ------------------------------------------------------------------ errores


@app.exception_handler(ChartError)
async def chart_error_handler(_: Request, exc: ChartError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    fields = [".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": "Datos de entrada no válidos.", "fields": fields}},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    log.exception("Error inesperado", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Error interno."}})


# ------------------------------------------------------------------ modelos


class ChartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datetime_local: Optional[str] = Field(None, max_length=32, description="Hora local sin zona, p. ej. 1990-05-15T14:30:00")
    datetime_utc: Optional[str] = Field(None, max_length=40, description="Hora UTC con zona, p. ej. 1990-05-15T12:30:00Z")
    timezone_name: Optional[str] = Field(None, max_length=64, description="Zona IANA opcional; si falta se detecta por coordenadas")
    fold: Optional[Literal[0, 1]] = Field(None, description="Para horas repetidas por cambio de horario: 0 primera, 1 segunda")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    house_system: Literal[tuple(HOUSE_SYSTEMS)] = "P"  # type: ignore[valid-type]

    @model_validator(mode="after")
    def one_datetime(self):
        if bool(self.datetime_local) == bool(self.datetime_utc):
            raise ValueError("Envía exactamente uno de datetime_local o datetime_utc")
        return self


# ------------------------------------------------------------------ rutas


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "version": request.app.state.settings.version}


@app.get("/source")
def source(request: Request):
    return {
        "source_code": request.app.state.settings.source_url,
        "license": "AGPL-3.0-or-later",
        "third_party": "Swiss Ephemeris (C) Astrodienst AG, AGPL",
    }


@app.get("/v1/positions", dependencies=[Depends(verify_request)])
def positions(request: Request, datetime_utc: str = Query(..., max_length=40)):
    return request.app.state.engine.positions_at(datetime_utc)


@app.post("/v1/chart", dependencies=[Depends(verify_request)])
def chart(request: Request, body: ChartRequest):
    return request.app.state.engine.chart(
        lat=body.lat,
        lon=body.lon,
        house_system=body.house_system,
        datetime_local=body.datetime_local,
        datetime_utc=body.datetime_utc,
        timezone_name=body.timezone_name,
        fold=body.fold,
    )

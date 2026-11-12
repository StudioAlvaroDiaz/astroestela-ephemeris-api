"""Configuración leída de variables de entorno (nunca del código)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_EPHE_FILES = ("sepl_18.se1", "semo_18.se1", "seas_18.se1")


def _csv(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Uno o varios secretos HMAC separados por comas: el primero firma en
    # WordPress; tener dos activos a la vez permite rotar sin cortar servicio.
    hmac_secrets: list[str] = field(default_factory=lambda: _csv("EPHEM_HMAC_SECRETS"))
    # Ventana de validez de una firma (segundos), contra reenvío de peticiones.
    max_clock_skew: int = int(os.environ.get("EPHEM_MAX_CLOCK_SKEW", "300"))
    ephe_path: Path = Path(os.environ.get("EPHEM_DATA_DIR", "/opt/ephemeris/data"))
    # Solo para pruebas locales sin archivos: usa el modelo Moshier (sin Quirón).
    allow_moshier: bool = os.environ.get("EPHEM_ALLOW_MOSHIER", "0") == "1"
    # AGPL §13: URL pública del código fuente que corre en este servicio.
    source_url: str = os.environ.get(
        "EPHEM_SOURCE_URL", "https://github.com/StudioAlvaroDiaz/astroestela-ephemeris-api"
    )
    version: str = os.environ.get("EPHEM_VERSION", "dev")

    def validate(self) -> None:
        """Falla al arrancar en vez de devolver cartas incompletas en silencio."""
        if not self.hmac_secrets:
            raise RuntimeError("EPHEM_HMAC_SECRETS no está definido")
        if any(len(s) < 32 for s in self.hmac_secrets):
            raise RuntimeError("Cada secreto HMAC debe tener al menos 32 caracteres")
        if not self.allow_moshier:
            missing = [f for f in REQUIRED_EPHE_FILES if not (self.ephe_path / f).is_file()]
            if missing:
                raise RuntimeError(
                    f"Faltan archivos de efemérides en {self.ephe_path}: {', '.join(missing)}"
                )


def get_settings() -> Settings:
    return Settings()

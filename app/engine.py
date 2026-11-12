"""Motor de cálculo: efemérides Swiss Ephemeris (derivadas de JPL/NASA), casas,
ángulos y aspectos. Sin E/S de red: todo se lee de archivos locales."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe
from timezonefinder import TimezoneFinder

# Swiss Ephemeris guarda su estado (ruta de archivos, cachés) por hilo: cada
# hilo que atiende peticiones debe inicializarse antes de calcular.
_THREAD = threading.local()
# TimezoneFinder no garantiza ser seguro entre hilos: acceso serializado.
_TF_LOCK = threading.Lock()
_TF = TimezoneFinder()

# Rango cubierto por los archivos *_18.se1.
MIN_DATE = date(1800, 1, 1)
MAX_DATE = date(2399, 12, 31)

SIGNS = (
    "Aries", "Tauro", "Géminis", "Cáncer", "Leo", "Virgo",
    "Libra", "Escorpio", "Sagitario", "Capricornio", "Acuario", "Piscis",
)

BODIES: dict[str, int] = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,
    "true_node": swe.TRUE_NODE,
    "mean_lilith": swe.MEAN_APOG,
    "chiron": swe.CHIRON,
}
# Puntos que no se marcan como "retrógrados" aunque su velocidad sea negativa.
NO_RETRO = {"sun", "moon", "true_node", "south_node", "mean_lilith"}

HOUSE_SYSTEMS = {
    "P": "Placidus",
    "K": "Koch",
    "O": "Porfirio",
    "R": "Regiomontanus",
    "C": "Campanus",
    "E": "Casas iguales",
    "W": "Signos enteros",
}
FALLBACK_HOUSE_SYSTEM = "O"  # funciona en cualquier latitud

ASPECT_RULES = (
    ("Conjunción", 0.0, 8.0),
    ("Oposición", 180.0, 8.0),
    ("Trígono", 120.0, 8.0),
    ("Cuadratura", 90.0, 7.0),
    ("Sextil", 60.0, 6.0),
)


class ChartError(Exception):
    """Error de entrada con código estable, pensado para mostrarse al usuario."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class Engine:
    ephe_path: str
    allow_moshier: bool = False

    def __post_init__(self) -> None:
        self._ensure_thread()
        self.flags = (swe.FLG_MOSEPH if self.allow_moshier else swe.FLG_SWIEPH) | swe.FLG_SPEED

    def _ensure_thread(self) -> None:
        if getattr(_THREAD, "ephe_path", None) != self.ephe_path:
            swe.set_ephe_path(self.ephe_path)
            _THREAD.ephe_path = self.ephe_path

    @property
    def engine_name(self) -> str:
        if self.allow_moshier:
            return "Moshier (solo pruebas)"
        return "Swiss Ephemeris (derivada de JPL/NASA DE431)"

    # ------------------------------------------------------------------ fechas

    def resolve_datetime(
        self,
        lat: float,
        lon: float,
        datetime_local: str | None = None,
        datetime_utc: str | None = None,
        timezone_name: str | None = None,
        fold: int | None = None,
    ) -> tuple[datetime, str, str, list[dict]]:
        """Devuelve (dt_utc, dt_local_iso, zona, avisos).

        Con hora local detecta la zona horaria histórica por coordenadas y
        rechaza horas inexistentes (salto de horario de verano). Las horas
        repetidas se resuelven con `fold` (0 = primera vez, 1 = segunda)."""
        warnings: list[dict] = []

        if datetime_utc:
            dt = _parse_iso(datetime_utc, "datetime_utc")
            if dt.tzinfo is None:
                raise ChartError("invalid_datetime", "datetime_utc debe incluir zona (Z o +00:00).")
            dt_utc = dt.astimezone(timezone.utc)
            _check_range(dt_utc)
            return dt_utc, dt_utc.isoformat(), "UTC", warnings

        naive = _parse_iso(datetime_local or "", "datetime_local")
        if naive.tzinfo is not None:
            raise ChartError("invalid_datetime", "datetime_local no debe incluir zona horaria.")

        if timezone_name:
            tz_name = timezone_name
        else:
            with _TF_LOCK:
                tz_name = _TF.timezone_at(lng=lon, lat=lat)
            if not tz_name:
                raise ChartError(
                    "timezone_not_found",
                    "No se pudo determinar la zona horaria de esas coordenadas; envía timezone_name.",
                )
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ChartError("invalid_timezone", "Zona horaria no válida.") from None

        first = naive.replace(tzinfo=tz, fold=0)
        second = naive.replace(tzinfo=tz, fold=1)
        roundtrip = first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
        if roundtrip != naive:
            raise ChartError(
                "nonexistent_local_time",
                "Esa hora no existió en ese lugar (adelanto de horario de verano). "
                "Confirma la hora de nacimiento.",
            )
        chosen = first
        if first.utcoffset() != second.utcoffset():
            if fold is None:
                warnings.append({
                    "code": "ambiguous_local_time",
                    "message": "Esa hora ocurrió dos veces (atraso de horario de verano); "
                               "se usó la primera. Envía fold=1 para la segunda.",
                })
            elif fold == 1:
                chosen = second

        dt_utc = chosen.astimezone(timezone.utc)
        _check_range(dt_utc)
        return dt_utc, chosen.isoformat(), tz_name, warnings

    # --------------------------------------------------------------- cálculos

    def julian_day(self, dt_utc: datetime) -> float:
        seconds = dt_utc.second + dt_utc.microsecond / 1e6
        _, jd_ut = swe.utc_to_jd(
            dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, seconds, swe.GREG_CAL
        )
        return jd_ut

    def positions(self, jd_ut: float) -> tuple[dict, list[dict]]:
        result: dict[str, dict] = {}
        warnings: list[dict] = []
        self._ensure_thread()
        for name, code in BODIES.items():
            if name == "chiron" and self.allow_moshier:
                warnings.append({"code": "body_unavailable", "message": "Quirón no disponible en modo Moshier."})
                continue
            values, retflag = swe.calc_ut(jd_ut, code, self.flags)
            if not self.allow_moshier and retflag & swe.FLG_MOSEPH:
                # Swiss Ephemeris cae a Moshier si no encuentra los archivos:
                # preferimos fallar a devolver menos precisión sin avisar.
                raise RuntimeError(f"Archivo de efemérides no disponible para {name}")
            lon, lat, _, speed = values[0], values[1], values[2], values[3]
            result[name] = point_info(lon, lat, speed, retro_allowed=name not in NO_RETRO)
        node = result["true_node"]
        result["south_node"] = point_info(
            (node["longitude"] + 180.0) % 360.0, -node["latitude"], node["speed"], retro_allowed=False
        )
        return result, warnings

    def houses(self, jd_ut: float, lat: float, lon: float, system: str) -> tuple[list[float], dict, str, list[dict]]:
        warnings: list[dict] = []
        used = system
        self._ensure_thread()
        try:
            cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, system.encode())
        except swe.Error:
            used = FALLBACK_HOUSE_SYSTEM
            cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, used.encode())
            warnings.append({
                "code": "house_system_fallback",
                "message": f"{HOUSE_SYSTEMS[system]} no se puede calcular a esta latitud; "
                           f"se usó {HOUSE_SYSTEMS[used]}.",
            })
        cusp_list = [c % 360.0 for c in list(cusps)[:12]]
        asc, mc, armc, vertex = ascmc[0], ascmc[1], ascmc[2], ascmc[3]
        angles = {
            "ascendant": point_info(asc),
            "mc": point_info(mc),
            "descendant": point_info((asc + 180.0) % 360.0),
            "ic": point_info((mc + 180.0) % 360.0),
            "vertex": point_info(vertex),
            "armc": round(armc, 6),
        }
        return cusp_list, angles, used, warnings

    def chart(
        self,
        lat: float,
        lon: float,
        house_system: str = "P",
        datetime_local: str | None = None,
        datetime_utc: str | None = None,
        timezone_name: str | None = None,
        fold: int | None = None,
    ) -> dict:
        dt_utc, dt_local, tz_name, warnings = self.resolve_datetime(
            lat, lon, datetime_local, datetime_utc, timezone_name, fold
        )
        jd = self.julian_day(dt_utc)
        positions, w_pos = self.positions(jd)
        cusps, angles, used, w_house = self.houses(jd, lat, lon, house_system)
        warnings += w_pos + w_house

        for body in positions.values():
            body["house"] = house_of(body["longitude"], cusps)

        houses = {
            f"house_{i + 1}": {"number": i + 1, **point_info(c)} for i, c in enumerate(cusps)
        }
        return {
            "metadata": {
                "datetime_local": dt_local,
                "datetime_utc": dt_utc.isoformat(),
                "timezone": tz_name,
                "julian_day_ut": round(jd, 6),
                "coordinates": {"lat": lat, "lon": lon},
                "house_system_requested": house_system,
                "house_system": used,
                "zodiac": "tropical",
                "ephemeris": self.engine_name,
            },
            "angles": angles,
            "houses": houses,
            "positions": positions,
            "aspects": aspects(positions, angles),
            "warnings": warnings,
        }

    def positions_at(self, datetime_utc: str) -> dict:
        dt_utc, _, _, _ = self.resolve_datetime(0.0, 0.0, datetime_utc=datetime_utc)
        jd = self.julian_day(dt_utc)
        positions, warnings = self.positions(jd)
        return {
            "datetime_utc": dt_utc.isoformat(),
            "ephemeris": self.engine_name,
            "positions": positions,
            "warnings": warnings,
        }


# ---------------------------------------------------------------- utilidades


def _parse_iso(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ChartError("invalid_datetime", f"{field} no es una fecha ISO 8601 válida.") from None


def _check_range(dt_utc: datetime) -> None:
    if not (MIN_DATE <= dt_utc.date() <= MAX_DATE):
        raise ChartError(
            "date_out_of_range",
            f"Fecha fuera del rango soportado ({MIN_DATE.year}–{MAX_DATE.year}).",
        )


def format_dms(deg: float) -> str:
    total = round(deg * 3600)
    d, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{d:02d}°{m:02d}'{s:02d}\""


def point_info(lon: float, lat: float = 0.0, speed: float | None = None, retro_allowed: bool = False) -> dict:
    lon %= 360.0
    sign_index = int(lon // 30) % 12
    deg_in_sign = lon - sign_index * 30
    info = {
        "longitude": round(lon, 6),
        "latitude": round(lat, 6),
        "sign": SIGNS[sign_index],
        "sign_index": sign_index,
        "degree_in_sign": round(deg_in_sign, 6),
        "formatted": format_dms(deg_in_sign),
    }
    if speed is not None:
        info["speed"] = round(speed, 6)
        info["retrograde"] = bool(retro_allowed and speed < 0)
    return info


def house_of(lon: float, cusps: list[float]) -> int:
    lon %= 360.0
    for i in range(12):
        start, end = cusps[i], cusps[(i + 1) % 12]
        if start <= end:
            if start <= lon < end:
                return i + 1
        elif lon >= start or lon < end:
            return i + 1
    return 1


def _separation(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def aspects(positions: dict, angles: dict) -> list[dict]:
    points = {k: (v["longitude"], v.get("speed", 0.0)) for k, v in positions.items()}
    points["ascendant"] = (angles["ascendant"]["longitude"], 0.0)
    points["mc"] = (angles["mc"]["longitude"], 0.0)

    keys = list(points)
    found = []
    step = 1.0 / 1440.0  # un minuto, en días
    for i, p1 in enumerate(keys):
        for p2 in keys[i + 1:]:
            if {p1, p2} == {"true_node", "south_node"}:
                continue
            (l1, s1), (l2, s2) = points[p1], points[p2]
            sep = _separation(l1, l2)
            for name, angle, max_orb in ASPECT_RULES:
                orb = abs(sep - angle)
                if orb <= max_orb:
                    if s1 == 0.0 and s2 == 0.0:
                        phase = None
                    else:
                        later = abs(_separation(l1 + s1 * step, l2 + s2 * step) - angle)
                        phase = "applying" if later < orb else "separating"
                    found.append({
                        "point_1": p1,
                        "point_2": p2,
                        "aspect": name,
                        "exact_angle": angle,
                        "orb": round(orb, 4),
                        "phase": phase,
                    })
                    break
    return sorted(found, key=lambda a: a["orb"])

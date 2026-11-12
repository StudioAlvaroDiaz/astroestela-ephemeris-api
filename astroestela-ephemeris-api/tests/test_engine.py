"""Validación del motor contra cartas de referencia y casos límite.

Los casos de referencia son anonimizados: solo lugar, fecha y hora. Los valores
esperados vienen de cartas Placidus externas con precisión de 1 minuto de arco.
"""

import pytest

from app.engine import SIGNS, ChartError

SIGN_ALIASES = {"Geminis": "Géminis", "Cancer": "Cáncer"}
NAMES = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto")
TOLERANCE_ARCMIN = 1.5

TULUA = (4 + 6 / 60, -(76 + 12 / 60))

REFERENCE_CASES = {
    "caso_1_tulua_1993": (TULUA, "1993-03-20T15:45:00", "1993-03-20T20:45", {
        "sun": "0°15' Aries", "moon": "3°44' Piscis", "mercury": "10°26' Piscis", "venus": "18°11' Aries",
        "mars": "14°31' Cancer", "saturn": "25°28' Acuario", "uranus": "21°38' Capricornio",
        "neptune": "20°51' Capricornio", "pluto": "25°22' Escorpio", "mc": "25°46' Tauro",
    }),
    "caso_2_tulua_2015": (TULUA, "2015-12-01T17:30:00", "2015-12-01T22:30", {
        "sun": "9°24' Sagitario", "mercury": "17°21' Sagitario", "venus": "26°13' Libra",
        "mars": "11°19' Libra", "saturn": "7°40' Sagitario", "uranus": "16°48' Aries",
        "ascendant": "5°16' Geminis", "mc": "29°39' Acuario",
    }),
    "caso_3_tulua_1989": (TULUA, "1989-05-26T11:30:00", "1989-05-26T16:30", {
        "sun": "5°23' Geminis", "moon": "16°29' Acuario", "venus": "18°56' Geminis",
        "jupiter": "15°20' Geminis", "uranus": "4°27' Capricornio", "neptune": "11°55' Capricornio",
        "pluto": "13°11' Escorpio", "ascendant": "24°11' Leo", "mc": "27°47' Tauro",
    }),
    "caso_4_tulua_2004": (TULUA, "2004-05-05T20:08:00", "2004-05-06T01:08", {
        "sun": "15°51' Tauro", "moon": "2°30' Sagitario", "mercury": "22°18' Aries",
        "venus": "23°35' Geminis", "jupiter": "8°54' Virgo", "saturn": "9°18' Cancer",
        "uranus": "6°17' Piscis", "neptune": "15°21' Acuario", "pluto": "21°47' Sagitario",
        "ascendant": "14°38' Sagitario", "mc": "13°45' Virgo",
    }),
}


def to_lon(text: str) -> float:
    deg, rest = text.split("°")
    minutes, sign = rest.split("'")
    sign = SIGN_ALIASES.get(sign.strip(), sign.strip())
    return SIGNS.index(sign) * 30 + int(deg) + int(minutes) / 60


def arcmin(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180) * 60


@pytest.mark.parametrize("case", REFERENCE_CASES)
def test_reference_chart(engine, case):
    (lat, lon), local, utc, expected = REFERENCE_CASES[case]
    chart = engine.chart(lat=lat, lon=lon, datetime_local=local)
    assert chart["metadata"]["timezone"] == "America/Bogota"
    assert chart["metadata"]["datetime_utc"].startswith(utc)
    for key, value in expected.items():
        src = chart["angles"] if key in ("ascendant", "mc") else chart["positions"]
        diff = arcmin(src[key]["longitude"], to_lon(value))
        assert diff <= TOLERANCE_ARCMIN, f"{case} {key}: {diff:.2f}' de diferencia"


def test_summer_time_is_applied_in_spain(engine):
    # Barcelona, mayo de 2025: horario de verano UTC+2.
    chart = engine.chart(lat=41.3833, lon=2.1667, datetime_local="2025-05-21T19:20:00")
    assert chart["metadata"]["timezone"] == "Europe/Madrid"
    assert chart["metadata"]["datetime_utc"].startswith("2025-05-21T17:20")


def test_colombia_1992_daylight_saving(engine):
    chart = engine.chart(lat=4.711, lon=-74.0721, datetime_local="1992-06-01T12:00:00")
    assert chart["metadata"]["datetime_utc"].startswith("1992-06-01T16:00")


def test_nonexistent_local_time_is_rejected(engine):
    with pytest.raises(ChartError) as err:
        engine.chart(lat=40.4168, lon=-3.7038, datetime_local="2021-03-28T02:30:00")
    assert err.value.code == "nonexistent_local_time"


def test_ambiguous_local_time_warns_and_honours_fold(engine):
    first = engine.chart(lat=40.4168, lon=-3.7038, datetime_local="2021-10-31T02:30:00")
    assert first["metadata"]["datetime_utc"].startswith("2021-10-31T00:30")
    assert first["warnings"][0]["code"] == "ambiguous_local_time"
    second = engine.chart(lat=40.4168, lon=-3.7038, datetime_local="2021-10-31T02:30:00", fold=1)
    assert second["metadata"]["datetime_utc"].startswith("2021-10-31T01:30")


def test_high_latitude_falls_back_to_porphyry(engine):
    chart = engine.chart(lat=69.65, lon=18.96, datetime_local="1995-06-21T12:00:00")
    assert chart["metadata"]["house_system"] == "O"
    assert any(w["code"] == "house_system_fallback" for w in chart["warnings"])
    assert len(chart["houses"]) == 12


def test_out_of_range_date(engine):
    with pytest.raises(ChartError) as err:
        engine.chart(lat=0, lon=0, datetime_utc="1700-01-01T00:00:00Z")
    assert err.value.code == "date_out_of_range"


def test_chart_shape(engine):
    chart = engine.chart(lat=40.4168, lon=-3.7038, datetime_utc="1990-05-15T12:30:00Z")
    assert set(chart) == {"metadata", "angles", "houses", "positions", "aspects", "warnings"}
    assert {"south_node", "true_node", "mean_lilith"} <= set(chart["positions"])
    for body in chart["positions"].values():
        assert 1 <= body["house"] <= 12
    assert all(a["phase"] in ("applying", "separating", None) for a in chart["aspects"])
    assert not any({a["point_1"], a["point_2"]} == {"true_node", "south_node"} for a in chart["aspects"])


def test_parallel_threads_give_identical_results(engine):
    # Swiss Ephemeris guarda estado por hilo; el servidor atiende en varios.
    from concurrent.futures import ThreadPoolExecutor

    def run(_):
        c = engine.chart(lat=4.1, lon=-76.2, datetime_local="1993-03-20T15:45:00")
        return c["positions"]["moon"]["longitude"], c["angles"]["ascendant"]["longitude"], c["warnings"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(32)))
    assert len(set((m, a) for m, a, _ in results)) == 1

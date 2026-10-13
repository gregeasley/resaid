"""
Shared helpers for ARIES export tests: synthetic data, a parser for the fixed-width
ARIES text, and an independent model of the expected decline line per phase.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from resaid.dca import decline_curve

LINE_WIDTH = 93
PHASE_LABEL = {"OIL": "OIL", "GAS": "GAS", "WATER": "WTR"}

_PHASE = r"^  (OIL|GAS|WTR)\s+(\S+) X (?:B/M|M/M) "
_HYPERBOLIC = re.compile(_PHASE + r"(\S+) EXP B/(\S+) (\S+)$")
_EXPONENTIAL = re.compile(_PHASE + r"99 YRS EXP (\S+)$")
_FLAT = re.compile(_PHASE + r"1 YRS FLAT 0$")
_CONTINUATION = re.compile(r'^  "\s+X X (?:B/M|M/M) 99 YRS EXP (\S+)$')
_START = re.compile(r"^  START\s+(\d\d/\d{4})$")


def make_production(seed=42, n_wells=4, months=18, shut_in_well=None):
    """Declining oil wells with gas/water; ``shut_in_well`` has zero last-3-month volumes."""
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_wells):
        q0 = 400 + 600 * w
        d = 0.05 + 0.04 * w
        uid = f"ARIES_WELL_{w:03d}"
        for t in range(months):
            q = q0 * np.exp(-d * t) * rng.lognormal(0, 0.05)
            if uid == shut_in_well and t >= months - 3:
                q = 0.0
            rows.append(
                {
                    "API_UWI": uid,
                    "MAJOR": "OIL",
                    "ProducingMonth": pd.Timestamp("2023-01-01") + pd.DateOffset(months=t),
                    "LateralLength_FT": 5000,
                    "LiquidsProd_BBL": q,
                    "GasProd_MCF": q * rng.uniform(0.8, 1.2) * 1.5,
                    "WaterProd_BBL": q * rng.uniform(0.4, 0.6),
                }
            )
    return pd.DataFrame(rows)


def fit(df, three_phase, verbose=False, **attrs):
    dca = decline_curve()
    dca.STAT_FILE = None
    dca.dataframe = df
    dca.date_col = "ProducingMonth"
    dca.uid_col = "API_UWI"
    dca.oil_col = "LiquidsProd_BBL"
    dca.gas_col = "GasProd_MCF"
    dca.water_col = "WaterProd_BBL"
    dca.phase_col = "MAJOR"
    dca.length_col = "LateralLength_FT"
    dca.backup_decline = True
    dca.three_phase_mode = three_phase
    for k, v in attrs.items():
        setattr(dca, k, v)
    dca.run_DCA(_verbose=verbose)
    dca.generate_oneline(denormalize=True)
    return dca


def parse_aries(path, scenario):
    """Return {uid: {"start": "mm/YYYY", "phases": {label: line_info}}}; asserts layout."""
    wells = {}
    current = None
    last_phase = None
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines, "ARIES export is empty"
    for line in lines:
        assert len(line) == LINE_WIDTH, f"bad width {len(line)}: {line!r}"
        if not line.startswith(" "):
            current = wells.setdefault(line.strip(), {"start": None, "phases": {}})
            last_phase = None
            continue
        if line.strip() == "PRODUCTION":
            continue
        assert line.endswith(scenario), f"missing scenario: {line!r}"
        body = line[: LINE_WIDTH - len(scenario)].rstrip()
        if m := _START.match(body):
            current["start"] = m.group(1)
        elif m := _HYPERBOLIC.match(body):
            last_phase = m.group(1)
            current["phases"][last_phase] = {
                "kind": "hyperbolic",
                "volume": float(m.group(2)),
                "dmin": float(m.group(3)),
                "b": float(m.group(4)),
                "de": float(m.group(5)),
                "continuation": None,
            }
        elif m := _EXPONENTIAL.match(body):
            last_phase = m.group(1)
            current["phases"][last_phase] = {
                "kind": "exponential",
                "volume": float(m.group(2)),
                "de": float(m.group(3)),
            }
        elif m := _FLAT.match(body):
            last_phase = m.group(1)
            current["phases"][last_phase] = {"kind": "flat", "volume": float(m.group(2))}
        elif m := _CONTINUATION.match(body):
            assert last_phase is not None
            assert current["phases"][last_phase]["kind"] == "hyperbolic"
            current["phases"][last_phase]["continuation"] = float(m.group(1))
        else:
            raise AssertionError(f"unrecognised ARIES line: {line!r}")
    return wells


def _month_diff(a, b):
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return 12 * (a.year - b.year) + (a.month - b.month)


def revised_aries_de(de, b, dt):
    """Secant-effective annual decline (%) after advancing ``dt`` months along Arps."""
    ai = de / (1 + b * de * dt)
    return (1 - np.power((ai * 12) * b + 1, -1 / b)) * 100


def expected_aries(dca, dmin, write_water):
    """
    Independent model of what ``generate_aries_export`` should write: START is the last actual
    month, each phase starts at its fitted curve's rate at START (the curve passes through the
    last-three-month average at the midpoint of those months, one month earlier), and a phase
    whose last three months are all zero is FLAT.
    """
    raw = dca.dataframe
    raw = raw.assign(**{dca.date_col: pd.to_datetime(raw[dca.date_col])})
    one = dca.oneline_dataframe.set_index("UID")
    expected = {}
    for uid, g in raw.groupby(dca.uid_col):
        last3 = g.sort_values(dca.date_col).tail(3)
        start = last3[dca.date_col].max()
        o = one.loc[uid]
        dt = _month_diff(start, o["T0_DATE"])
        phases = {}
        for phase, vol_col in (
            ("OIL", dca.oil_col),
            ("GAS", dca.gas_col),
            ("WATER", dca.water_col),
        ):
            if phase == "WATER" and not write_water:
                continue
            if dca.three_phase_mode:
                ip, de, b = (o[c] for c in {"OIL": ("IPO", "DO", "BO"), "GAS": ("IPG", "DG", "BG"), "WATER": ("IPW", "DW", "BW")}[phase])
                active = ip > 0
            else:
                de, b = o["DE"], o["B"]
                ratio = {"OIL": 1.0, "GAS": o["MINOR_RATIO"], "WATER": o["WATER_RATIO"]}[phase]
                ip = o["IPO"] * ratio
                active = o["IPO"] > 0 and ratio > 0
            if not active:
                continue
            if float(last3[vol_col].mean()) > 0:
                rate = float(dca.arps_decline(float(dt), float(ip), float(de), float(b), 0.0))
            else:
                rate = 0.0                                   # shut in: last three months all zero
            volume = round(rate, 0)
            rev = round(revised_aries_de(float(de), float(b), dt), 2)
            if b > 0.05 and rev > dmin and volume > 0:
                info = {"kind": "hyperbolic", "volume": volume, "dmin": dmin, "b": round(float(b), 2), "de": rev, "continuation": dmin}
            elif volume > 0 and rev > dmin:
                info = {"kind": "exponential", "volume": volume, "de": rev}
            elif volume > 0:
                info = {"kind": "exponential", "volume": volume, "de": dmin}
            else:
                info = {"kind": "flat", "volume": volume}
            phases[PHASE_LABEL[phase]] = info
        expected[uid] = {"start": start.strftime("%m/%Y"), "phases": phases, "dt": dt}
    return expected

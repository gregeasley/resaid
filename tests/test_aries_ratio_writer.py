"""``aries_eco_gen`` (ratio-mode ARIES writer) writes the minor-phase ratio line."""

from __future__ import annotations

import pandas as pd
import pytest

from resaid.dca import decline_curve


@pytest.fixture
def ratio_dca():
    rows = []
    for w, gor in enumerate([0.5, 8.0]):  # W0 oil-major, W1 gas-major
        for t in range(24):
            q = (1000 if w == 0 else 300) * (1 + 0.1 * t) ** -1
            rows.append({"UID": f"W{w}", "DATE": pd.Timestamp("2022-01-01") + pd.DateOffset(months=t),
                         "OIL": q, "GAS": q * gor, "WATER": q * 0.4})
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = pd.DataFrame(rows)
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    d.run_DCA()
    d.generate_oneline(denormalize=True)
    return d


def _wells(path):
    wells, current = {}, None
    for line in path.read_text().splitlines():
        if not line.startswith(" "):
            current = wells.setdefault(line.strip(), [])
        else:
            assert current is not None, f"forecast line before any well: {line!r}"
            current.append(line[:80].strip())
    return wells


@pytest.mark.parametrize("write_water", [True, False])
def test_minor_ratio_line_written(ratio_dca, tmp_path, write_water):
    path = tmp_path / "aries.txt"
    ratio_dca.aries_eco_gen(file_path=str(path), write_water=write_water)
    wells = _wells(path)
    one = ratio_dca.oneline_dataframe.set_index("UID")

    oil = wells["W0"]
    assert any(line.startswith("GAS/OIL") and "X M/B TO LIFE LIN TIME" in line for line in oil)
    assert f"{round(one.loc['W0', 'MINOR_RATIO'], 3)} X M/B" in next(l for l in oil if l.startswith("GAS/OIL"))

    gas = wells["W1"]
    assert any(line.startswith("OIL/GAS") and "X B/M TO LIFE LIN TIME" in line for line in gas)

    # Order: major phase (and continuation), then minor ratio, then water ratio.
    for lines in (oil, gas):
        minor_idx = next(i for i, l in enumerate(lines) if l.startswith(("GAS/OIL", "OIL/GAS")))
        major_idx = next(i for i, l in enumerate(lines) if l.startswith(("OIL ", "GAS ")))
        assert major_idx < minor_idx
        has_water = any(l.startswith("WTR/") for l in lines)
        assert has_water is write_water
        if has_water:
            assert minor_idx < next(i for i, l in enumerate(lines) if l.startswith("WTR/"))

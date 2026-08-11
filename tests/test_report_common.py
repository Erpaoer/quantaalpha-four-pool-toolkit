from pathlib import Path
import csv
import json

import pytest

from generators.report_common import (
    POOL_LABELS,
    ReportInputError,
    ReportInputs,
    build_report,
    validate_plot_data,
)


def _write_csv(path: Path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_inputs(tmp_path: Path, pool="CSI500") -> ReportInputs:
    plot = tmp_path / f"plot_data_{pool}.json"
    plot.write_text(
        json.dumps(
            {
                "main": {
                    "dates": ["20240102", "20240103", "20240104"],
                    "strat": [1.0, 1.02, 1.01],
                    "bench": [1.0, 1.0, 0.99],
                },
                "proxy": {
                    "dates": ["20240102", "20240103", "20240104"],
                    "strat": [1.0, 1.01, 1.0],
                    "bench": [1.0, 1.0, 0.99],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = tmp_path / f"report_data_{pool}.json"
    report.write_text(
        json.dumps({"loo": [{"label": "全部", "excess": 0.02}]}),
        encoding="utf-8",
    )
    index_returns = tmp_path / "index_returns.csv"
    _write_csv(
        index_returns,
        ["pool", "trade_date", "return"],
        [
            {"pool": pool, "trade_date": "20240103", "return": "0.0"},
            {"pool": pool, "trade_date": "20240104", "return": "-0.01"},
        ],
    )
    nav = tmp_path / f"nav_{pool}_selected_icir_dedup.csv"
    _write_csv(
        nav,
        ["trade_date", "nav", "num_holdings"],
        [
            {"trade_date": "20240103", "nav": "1.02", "num_holdings": "50"},
            {"trade_date": "20240104", "nav": "1.01", "num_holdings": "49"},
        ],
    )
    target = tmp_path / f"target_portfolio_{pool}_20240104.csv"
    _write_csv(
        target,
        ["ts_code", "target_weight"],
        [
            {"ts_code": "600000.SH", "target_weight": "0.5"},
            {"ts_code": "000001.SZ", "target_weight": "0.5"},
        ],
    )
    factors = tmp_path / f"factors_{pool}.txt"
    factors.write_text("Factor_A\nFactor_B\n", encoding="utf-8")
    return ReportInputs(
        plot_data=plot,
        report_data=report,
        index_returns=index_returns,
        nav=nav,
        target_portfolio=target,
        factor_list=factors,
        output=tmp_path / f"{pool}_report.html",
    )


def test_build_report_uses_pool_metadata_and_factor_file(tmp_path):
    inputs = _fixture_inputs(tmp_path)
    output = build_report("CSI500", inputs)
    document = output.read_text(encoding="utf-8")
    assert output == inputs.output
    assert POOL_LABELS["CSI500"] in document
    assert "2 因子" in document
    assert "Factor_A" in document
    assert "Factor_B" in document
    assert "目标持仓 2 只" in document
    assert "固定宣传结论" not in document
    assert str(tmp_path) not in document
    assert "plot_data_CSI500.json" in document


def test_missing_inputs_are_listed_before_output_is_written(tmp_path):
    inputs = _fixture_inputs(tmp_path)
    inputs.report_data.unlink()
    inputs.nav.unlink()
    with pytest.raises(ReportInputError) as caught:
        build_report("CSI500", inputs)
    message = str(caught.value)
    assert "report_data_CSI500.json" in message
    assert "nav_CSI500_selected_icir_dedup.csv" in message
    assert not inputs.output.exists()


def test_plot_data_requires_equal_finite_strictly_sorted_series():
    with pytest.raises(ReportInputError, match="等长"):
        validate_plot_data(
            {
                "main": {
                    "dates": ["20240102"],
                    "strat": [1.0, 1.1],
                    "bench": [1.0],
                }
            },
            source=Path("bad.json"),
        )
    with pytest.raises(ReportInputError, match="严格递增"):
        validate_plot_data(
            {
                "main": {
                    "dates": ["20240103", "20240102"],
                    "strat": [1.0, 1.1],
                    "bench": [1.0, 1.0],
                }
            },
            source=Path("bad.json"),
        )

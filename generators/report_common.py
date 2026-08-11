from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from toolkit_paths import ConfigurationError, load_factor_names


POOL_LABELS = {
    "CSI300": "沪深300",
    "CSI500": "中证500",
    "CSI1000": "中证1000",
    "CSI2000": "中证2000",
}


class ReportInputError(ValueError):
    """Raised before report output when an input is missing or invalid."""


@dataclass(frozen=True)
class ReportInputs:
    plot_data: Path
    report_data: Path
    index_returns: Path
    nav: Path
    target_portfolio: Path | None
    factor_list: Path
    output: Path


def _resolve(raw: str | Path | None, default: Path) -> Path:
    value = Path(raw).expanduser() if raw else default
    return value.resolve()


def resolve_report_inputs(pool: str, args) -> ReportInputs:
    input_dir = _resolve(args.input_dir, REPO_ROOT / "outputs")
    matches = sorted(input_dir.glob(f"target_portfolio_{pool}_*.csv"))
    if args.target_portfolio:
        target = _resolve(
            args.target_portfolio,
            input_dir / f"target_portfolio_{pool}.csv",
        )
    elif matches:
        target = matches[-1].resolve()
    else:
        target = None
    return ReportInputs(
        plot_data=_resolve(
            args.plot_data,
            REPO_ROOT / "data" / f"plot_data_{pool}.json",
        ),
        report_data=_resolve(
            args.report_data,
            input_dir / f"report_data_{pool}.json",
        ),
        index_returns=_resolve(
            args.index_returns,
            input_dir / "index_returns.csv",
        ),
        nav=_resolve(
            args.nav,
            input_dir / f"nav_{pool}_selected_icir_dedup.csv",
        ),
        target_portfolio=target,
        factor_list=_resolve(
            args.factor_list,
            REPO_ROOT / "data" / f"factors_{pool}.txt",
        ),
        output=_resolve(
            args.output,
            input_dir / f"{pool}_factor_report.html",
        ),
    )


def missing_inputs(pool: str, inputs: ReportInputs) -> list[str]:
    required = {
        "plot_data": inputs.plot_data,
        "report_data": inputs.report_data,
        "index_returns": inputs.index_returns,
        "nav": inputs.nav,
        "factor_list": inputs.factor_list,
    }
    missing = [
        f"{name}: {path}"
        for name, path in required.items()
        if not path.is_file()
    ]
    if inputs.target_portfolio is None:
        missing.append(f"target_portfolio: target_portfolio_{pool}_*.csv")
    elif not inputs.target_portfolio.is_file():
        missing.append(f"target_portfolio: {inputs.target_portfolio}")
    return missing


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"JSON 无法读取: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportInputError(f"JSON 顶层必须是对象: {path}")
    return value


def _read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = required_columns - columns
            if missing:
                raise ReportInputError(f"CSV 缺少列 {sorted(missing)}: {path}")
            rows = list(reader)
    except OSError as exc:
        raise ReportInputError(f"CSV 无法读取: {path}: {exc}") from exc
    if not rows:
        raise ReportInputError(f"CSV 没有数据行: {path}")
    return rows


def validate_plot_data(
    payload: dict[str, Any],
    *,
    source: Path,
) -> dict[str, list[Any]]:
    main = payload.get("main")
    if not isinstance(main, dict):
        raise ReportInputError(f"plot_data 缺少 main 对象: {source}")
    dates = main.get("dates")
    strategy = main.get("strat")
    benchmark = main.get("bench")
    if not all(isinstance(item, list) for item in (dates, strategy, benchmark)):
        raise ReportInputError(
            f"plot_data 的 dates/strat/bench 必须是数组: {source}"
        )
    if not dates or len(dates) != len(strategy) or len(dates) != len(benchmark):
        raise ReportInputError(
            f"plot_data 的 dates/strat/bench 必须非空且等长: {source}"
        )
    if any(str(left) >= str(right) for left, right in zip(dates, dates[1:])):
        raise ReportInputError(f"plot_data 日期必须唯一且严格递增: {source}")
    numeric = [*strategy, *benchmark]
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in numeric
    ):
        raise ReportInputError(f"plot_data 净值必须全部是有限数值: {source}")
    return {
        "dates": [str(item) for item in dates],
        "strat": strategy,
        "bench": benchmark,
    }


def _returns(values: Sequence[float]) -> list[float]:
    return [
        right / left - 1.0
        for left, right in zip(values, values[1:])
        if left != 0
    ]


def _metrics(values: Sequence[float]) -> dict[str, float]:
    returns = _returns(values)
    periods = max(len(returns), 1)
    total = values[-1] / values[0] - 1.0
    annual = (values[-1] / values[0]) ** (252 / periods) - 1.0
    std = statistics.stdev(returns) if len(returns) > 1 else 0.0
    sharpe = statistics.mean(returns) / std * math.sqrt(252) if std else 0.0
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    return {
        "total_return": total,
        "annual_return": annual,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
    }


def _information_ratio(
    strategy: Sequence[float],
    benchmark: Sequence[float],
) -> float:
    excess = [s - b for s, b in zip(_returns(strategy), _returns(benchmark))]
    std = statistics.stdev(excess) if len(excess) > 1 else 0.0
    return statistics.mean(excess) / std * math.sqrt(252) if std else 0.0


def line_chart(
    series: Sequence[Sequence[float]],
    labels: Sequence[str],
    colors: Sequence[str],
    dates: Sequence[str],
    *,
    width: int = 760,
    height: int = 320,
) -> str:
    padding = 48
    flat = [value for values in series for value in values]
    low, high = min(flat), max(flat)
    span = high - low or 1.0
    low -= span * 0.05
    high += span * 0.08
    span = high - low

    def x_at(index: int) -> float:
        return padding + (width - padding - 10) * index / max(len(dates) - 1, 1)

    def y_at(value: float) -> float:
        return height - padding - (height - padding - 24) * (value - low) / span

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%">']
    for tick in range(5):
        value = low + span * tick / 4
        y = y_at(value)
        parts.append(
            f'<line x1="{padding}" y1="{y:.1f}" x2="{width-10}" '
            f'y2="{y:.1f}" stroke="#e2e8f0"/>'
        )
        parts.append(
            f'<text x="{padding-6}" y="{y+3:.1f}" font-size="10" '
            f'text-anchor="end">{value:.2f}</text>'
        )
    step = max(len(dates) // 6, 1)
    for index in range(0, len(dates), step):
        parts.append(
            f'<text x="{x_at(index):.1f}" y="{height-padding+16}" '
            f'font-size="9" text-anchor="middle">'
            f'{html.escape(dates[index][:6])}</text>'
        )
    for values, color in zip(series, colors):
        points = " ".join(
            f"{x_at(index):.1f},{y_at(value):.1f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" '
            f'stroke="{color}" stroke-width="2"/>'
        )
    legend_x = padding
    for label, color in zip(labels, colors):
        safe = html.escape(label)
        parts.append(
            f'<rect x="{legend_x}" y="8" width="12" height="12" '
            f'fill="{color}"/>'
        )
        parts.append(
            f'<text x="{legend_x+16}" y="18" font-size="11">{safe}</text>'
        )
        legend_x += len(label) * 13 + 42
    parts.append("</svg>")
    return "".join(parts)


def _factor_rows(names: Sequence[str]) -> str:
    return "".join(
        f"<tr><td>{index}</td><td>{html.escape(name)}</td></tr>"
        for index, name in enumerate(names, start=1)
    )


def _render_report(
    pool: str,
    plot: dict[str, list[Any]],
    report_data: dict[str, Any],
    index_rows: list[dict[str, str]],
    nav_rows: list[dict[str, str]],
    target_rows: list[dict[str, str]],
    factors: list[str],
    inputs: ReportInputs,
) -> str:
    label = POOL_LABELS[pool]
    strategy_metrics = _metrics(plot["strat"])
    benchmark_metrics = _metrics(plot["bench"])
    excess = strategy_metrics["annual_return"] - benchmark_metrics["annual_return"]
    information_ratio = _information_ratio(plot["strat"], plot["bench"])
    direction = "正" if excess >= 0 else "负"
    chart = line_chart(
        [plot["strat"], plot["bench"]],
        [f"{len(factors)} 因子策略", f"{label}基准"],
        ["#2E5496", "#94a3b8"],
        plot["dates"],
    )
    latest_nav_date = max(row["trade_date"] for row in nav_rows)
    report_keys = ", ".join(sorted(report_data)) or "无扩展字段"
    source_rows = "".join(
        f"<tr><td>{html.escape(name)}</td>"
        f"<td><code>{html.escape(str(path))}</code></td></tr>"
        for name, path in (
            ("plot_data", inputs.plot_data),
            ("report_data", inputs.report_data),
            ("index_returns", inputs.index_returns),
            ("nav", inputs.nav),
            ("target_portfolio", inputs.target_portfolio),
            ("factor_list", inputs.factor_list),
        )
    )

    def pct(value: float) -> str:
        return f"{value * 100:.2f}%"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{label} {len(factors)}因子策略报告</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Microsoft YaHei',sans-serif;margin:0;background:#f1f5f9;color:#1e293b;line-height:1.6}}
.wrap{{max-width:920px;margin:auto;background:#fff}}header{{padding:30px 38px;background:#1f3864;color:#fff}}
section{{padding:24px 38px;border-bottom:1px solid #e2e8f0}}h2{{color:#1f3864}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px;border:1px solid #e2e8f0;text-align:left}}th{{background:#2e5496;color:#fff}}code{{word-break:break-all}}
.note{{background:#f8fafc;border-left:4px solid #94a3b8;padding:10px 12px}}.chart{{overflow-x:auto}}
</style></head><body><div class="wrap">
<header><h1>{label} · {len(factors)}因子策略</h1><p>由输入数据自动计算；区间 {plot['dates'][0]} 至 {plot['dates'][-1]}</p></header>
<section><h2>摘要</h2><table>
<tr><th>指标</th><th>策略</th><th>基准</th></tr>
<tr><td>累计收益</td><td>{pct(strategy_metrics['total_return'])}</td><td>{pct(benchmark_metrics['total_return'])}</td></tr>
<tr><td>年化收益</td><td>{pct(strategy_metrics['annual_return'])}</td><td>{pct(benchmark_metrics['annual_return'])}</td></tr>
<tr><td>最大回撤</td><td>{pct(strategy_metrics['max_drawdown'])}</td><td>{pct(benchmark_metrics['max_drawdown'])}</td></tr>
<tr><td>夏普</td><td>{strategy_metrics['sharpe']:.2f}</td><td>{benchmark_metrics['sharpe']:.2f}</td></tr>
</table><p>策略相对基准为{direction}超额：{pct(excess)}；日频信息比率：{information_ratio:.2f}。</p></section>
<section><h2>累计净值</h2><div class="chart">{chart}</div></section>
<section><h2>因子清单</h2><p>共 {len(factors)} 因子。</p><table><tr><th>#</th><th>因子名</th></tr>{_factor_rows(factors)}</table></section>
<section><h2>运行数据概览</h2><ul>
<li>报告扩展数据字段：{html.escape(report_keys)}</li>
<li>指数收益输入中 {pool} 记录：{len(index_rows)} 行</li>
<li>NAV 最新日期：{html.escape(latest_nav_date)}</li>
<li>目标持仓 {len(target_rows)} 只</li>
</ul></section>
<section><h2>输入证据</h2><table><tr><th>角色</th><th>文件</th></tr>{source_rows}</table></section>
<section><h2>边界与风险</h2><div class="note">本报告只复述和计算传入文件中的数据。预计算展示 JSON 不能替代对外部 QuantaAlpha、Quant-Project、调度表与 HDF5 的完整复跑；历史结果不代表未来表现。仅用于研究与复现，不构成投资建议。</div></section>
</div></body></html>"""


def build_report(pool: str, inputs: ReportInputs) -> Path:
    if pool not in POOL_LABELS:
        raise ReportInputError(f"不支持的股票池: {pool}")
    missing = missing_inputs(pool, inputs)
    if missing:
        raise ReportInputError(
            "报告输入缺失:\n" + "\n".join(f"  - {item}" for item in missing)
        )
    plot = validate_plot_data(_read_json(inputs.plot_data), source=inputs.plot_data)
    report_data = _read_json(inputs.report_data)
    index_rows = [
        row
        for row in _read_csv(
            inputs.index_returns,
            {"pool", "trade_date", "return"},
        )
        if row["pool"] == pool
    ]
    if not index_rows:
        raise ReportInputError(
            f"index_returns.csv 没有 {pool} 记录: {inputs.index_returns}"
        )
    nav_rows = _read_csv(inputs.nav, {"trade_date"})
    if inputs.target_portfolio is None:
        raise ReportInputError(
            f"target_portfolio: target_portfolio_{pool}_*.csv"
        )
    target_rows = _read_csv(inputs.target_portfolio, {"ts_code"})
    try:
        factors = load_factor_names(
            inputs.factor_list,
            strip_copy_suffix=pool == "CSI2000",
        )
    except ConfigurationError as exc:
        raise ReportInputError(str(exc)) from exc
    document = _render_report(
        pool,
        plot,
        report_data,
        index_rows,
        nav_rows,
        target_rows,
        factors,
        inputs,
    )
    inputs.output.parent.mkdir(parents=True, exist_ok=True)
    inputs.output.write_text(document, encoding="utf-8")
    return inputs.output


def build_parser(pool: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"生成 {POOL_LABELS[pool]} 因子策略 HTML 报告"
    )
    parser.add_argument("--input-dir", help="回测结果与报告数据所在目录")
    parser.add_argument("--plot-data")
    parser.add_argument("--report-data")
    parser.add_argument("--index-returns")
    parser.add_argument("--nav")
    parser.add_argument("--target-portfolio")
    parser.add_argument("--factor-list")
    parser.add_argument("--output")
    return parser


def main(pool: str, argv: Sequence[str] | None = None) -> int:
    parser = build_parser(pool)
    args = parser.parse_args(argv)
    try:
        output = build_report(pool, resolve_report_inputs(pool, args))
    except ReportInputError as exc:
        parser.error(str(exc))
    print(f"SAVED: {output}")
    return 0

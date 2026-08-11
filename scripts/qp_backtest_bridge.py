#!/usr/bin/env python3
"""
桥接：QuantaAlpha → Quant-Project A股真实回测

在生成单因子报告时，用 Quant-Project 的回测引擎（含 T+1、涨跌停、整手、
成本等 A 股交易规则）替代简单的等权分组净值曲线，产出可交易的 NAV 曲线。
"""
import importlib
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = REPO_ROOT
QP_ROOT: Path | None = None
INDUSTRY_PATH = QA_ROOT / "data/industry_map.csv"
_qp_runner = None


def configure_paths(qa_root, qp_root):
    global QA_ROOT, QP_ROOT, INDUSTRY_PATH, _qp_runner
    QA_ROOT = Path(qa_root).expanduser().resolve()
    QP_ROOT = Path(qp_root).expanduser().resolve()
    INDUSTRY_PATH = QA_ROOT / "data/industry_map.csv"
    _qp_runner = None


def get_qp_runner():
    global _qp_runner
    if _qp_runner is not None:
        return _qp_runner
    if QP_ROOT is None:
        raise RuntimeError("尚未配置 Quant-Project 根目录")
    entrypoint = (
        QP_ROOT
        / "backtest/ashare/ashare_sse_szse_n_day_factor_backtest.py"
    )
    if not entrypoint.is_file():
        raise RuntimeError(f"Quant-Project 回测入口不存在: {entrypoint}")
    qp_text = str(QP_ROOT)
    if qp_text not in sys.path:
        sys.path.insert(0, qp_text)
    module = importlib.import_module(
        "backtest.ashare.ashare_sse_szse_n_day_factor_backtest"
    )
    _qp_runner = module.run_ashare_sse_szse_n_day_factor_backtest
    return _qp_runner


def load_industry_map(path=None):
    industry_path = Path(path).resolve() if path else INDUSTRY_PATH
    if not industry_path.is_file():
        return {}
    frame = pd.read_csv(industry_path, dtype=str)
    required = {"instrument", "industry"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"行业映射缺少列 {sorted(missing)}: {industry_path}")
    return dict(zip(frame["instrument"], frame["industry"]))

# Cache: pre-built date index for MV and vol data (same for all factors)
_mv_date_cache = None
_vol_date_cache = None


def compute_factor_score_for_backtest(df, factor_expression, pool_mask, factor_name):
    """
    重新计算因子原始值，构建 Quant-Project 格式的 factor_score 表。
    """
    spec = importlib.util.spec_from_file_location(
        "ep", str(QA_ROOT / "quantaalpha/factors/coder/expr_parser.py")
    )
    ep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ep)
    spec2 = importlib.util.spec_from_file_location(
        "fl", str(QA_ROOT / "quantaalpha/factors/coder/function_lib.py")
    )
    fl = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(fl)
    for n in dir(ep): globals()[n] = getattr(ep, n)
    for n in dir(fl):
        if not n.startswith('_'): globals()[n] = getattr(fl, n)

    df_univ = df  # already filtered to pool stocks
    _avail_cols = sorted(df_univ.columns.tolist(), key=lambda x: -len(x))

    try:
        ee = factor_expression
        ee = ep.parse_symbol(ee, df_univ.columns)
        ee = ep.parse_expression(ee)
        for col in _avail_cols:
            bare = col[1:]
            ee = re.sub(r'\b' + re.escape(bare) + r'\b', f"df_univ['{col}']", ee)
        # Compatibility boundary: expressions must come from a trusted local
        # QuantaAlpha factor library. Never evaluate untrusted user input here.
        result = eval(ee)
        if isinstance(result, pd.DataFrame):
            result = result.iloc[:, 0]
        result = pd.Series(result, index=df_univ.index).astype(np.float64)
    except Exception:
        return None

    if result.isna().all():
        return None

    rows = []
    for (instrument, dt), val in result.dropna().items():
        # Convert qlib format to Tushare format
        ts_code = re.sub(r"^(SH|SZ)(\d+)", r"\2.\1", instrument)
        rows.append({
            "ts_code": ts_code,
            "trade_date": pd.Timestamp(dt).strftime("%Y%m%d"),
            "signal_score": float(val),
            "strategy_id": factor_name,
        })
    return pd.DataFrame(rows)


def build_backtest_base_from_hdf5(df, pool_mask):
    """从 HDF5 构建 Quant-Project 格式的回测底表。"""
    pool_stocks = set(df.index.get_level_values("instrument")[pool_mask].unique())
    uni_mask = np.where(np.array(df.index.get_level_values("instrument").map(lambda x: x in pool_stocks)))[0]
    df_univ = df.iloc[uni_mask]

    # Convert qlib format (SH600000) to Tushare format (600000.SH)
    raw_codes = df_univ.index.get_level_values("instrument")
    ts_codes = pd.Series(raw_codes).str.replace(r"^(SH|SZ)(\d+)", r"\2.\1", regex=True)

    base = pd.DataFrame({
        "ts_code": ts_codes,
        "trade_date": pd.to_datetime(df_univ.index.get_level_values("datetime")).strftime("%Y%m%d"),
    })

    for col, name in [("$open", "open"), ("$close", "close"), ("$high", "high"), ("$low", "low")]:
        if col in df_univ.columns:
            v = df_univ[col]
            base[name] = v.values if hasattr(v, 'values') else v
        else:
            base[name] = np.nan

    base["adj_factor"] = 1.0  # 已是后复权价格

    # ==== 涨跌停 & 停牌检测（板块自适应 + 数据字段优先，代码前缀兜底）====
    inst = df_univ.index.get_level_values("instrument")

    def _board_pct(code):
        """按代码前缀推断涨跌停幅度（数据无 limit_pct 时兜底；ST 需名称，缺失时按板块）。"""
        c = str(code)
        if c.startswith("BJ") or c.startswith("SH92") or c.startswith("SZ92"):
            return 0.30  # 北交所 ±30%
        if c.startswith("SH688"):
            return 0.20  # 科创板 ±20%
        if c.startswith("SZ300") or c.startswith("SZ301"):
            return 0.20  # 创业板 ±20%
        return 0.10      # 主板/中小板 ±10%（ST=±5% 需名称，此处缺失按板块）

    # 每股涨/跌停幅度：优先用数据自带（已含板块+ST），否则按代码前缀
    if "$limit_up_pct" in df_univ.columns:
        up_pct = pd.Series(df_univ["$limit_up_pct"]).astype(float).values
    else:
        up_pct = np.array([_board_pct(x) for x in inst], dtype=float)
    if "$limit_dn_pct" in df_univ.columns:
        dn_pct = pd.Series(df_univ["$limit_dn_pct"]).astype(float).values
    else:
        dn_pct = up_pct.copy()
    # 单位归一：有的数据把 10% 存成 10（而非 0.10）
    up_pct = np.where(up_pct > 1.0, up_pct / 100.0, up_pct)
    dn_pct = np.where(dn_pct > 1.0, dn_pct / 100.0, dn_pct)
    up_pct = np.nan_to_num(up_pct, nan=0.10)
    dn_pct = np.nan_to_num(dn_pct, nan=0.10)

    ret = df_univ.get("$return", pd.Series(0, index=df_univ.index))
    ret_vals = pd.Series(ret).astype(float).values
    open_vals = base["open"].values.astype(float)
    close_vals = base["close"].values.astype(float)
    eps = 1e-3

    # 收盘涨跌停：优先数据自带布尔标志，否则收益率 vs 板块幅度
    if "$is_limit_up" in df_univ.columns:
        base["is_close_limit_up"] = pd.Series(df_univ["$is_limit_up"]).astype(bool).values
    else:
        base["is_close_limit_up"] = ret_vals >= (up_pct - 0.005)
    if "$is_limit_down" in df_univ.columns:
        base["is_close_limit_down"] = pd.Series(df_univ["$is_limit_down"]).astype(bool).values
    else:
        base["is_close_limit_down"] = ret_vals <= -(dn_pct - 0.005)

    # 开盘涨跌停（执行环节真正用到）：prev_close = close/(1+ret) 反推，看 open 是否封在涨/跌停价
    with np.errstate(divide="ignore", invalid="ignore"):
        prev_close = close_vals / (1.0 + ret_vals)
    up_price = prev_close * (1.0 + up_pct)
    dn_price = prev_close * (1.0 - dn_pct)
    base["is_open_limit_up"] = open_vals >= up_price * (1.0 - eps)
    base["is_open_limit_down"] = open_vals <= dn_price * (1.0 + eps)

    # 停牌：成交量缺失或为 0
    if "$volume" in df_univ.columns:
        vol_vals = pd.Series(df_univ["$volume"]).astype(float).values
        base["is_suspended"] = np.isnan(vol_vals) | (vol_vals <= 0)
    else:
        base["is_suspended"] = False

    base["can_buy_open"] = (~base["is_open_limit_up"]) & (~base["is_suspended"])
    base["can_sell_open"] = (~base["is_open_limit_down"]) & (~base["is_suspended"])

    base = base.dropna(subset=["open", "close"])
    return base.reset_index(drop=True)


def run_qp_backtest(df, pool_mask, factor_expression, factor_name, rebalance_interval=5,
                    max_holdings=50, initial_cash=1_000_000, hold_threshold=2.0,
                    date_filter=None, market_filter=None, pool_name="CSI2000",
                    orthogonalize_vol=False, neutralize_mv=False, neutralize_ind=False):
    """一键跑 Quant-Project 回测。neutralize_mv=False 市值中性化, neutralize_vol=True 波动率正交。"""
    base = build_backtest_base_from_hdf5(df, pool_mask)
    score = compute_factor_score_for_backtest(df, factor_expression, pool_mask, factor_name)

    # Market cap neutralization: daily regression signal ~ log(mv)
    if neutralize_mv and score is not None and not score.empty:
        print("    Neutralizing market cap...")
        global _mv_date_cache
        if _mv_date_cache is None:
            print("    Building MV date index (once)...")
            mv = np.log(df["$circ_mv"].abs() + 1)
            mv_total = np.log(df["$total_mv"].abs() + 1)
            orig_nan = mv.isna().sum()
            mv = mv.fillna(mv_total)
            after_nan = mv.isna().sum()
            print(f"    MV source stats: $circ_mv NaN={orig_nan} -> after total_mv fillna NaN={after_nan} (total rows={len(mv)})")
            mv_dates = mv.index.get_level_values("datetime")
            _mv_date_cache = {}
            for i, d in enumerate(mv_dates):
                key = str(d)[:10].replace("-", "")
                if key not in _mv_date_cache: _mv_date_cache[key] = []
                _mv_date_cache[key].append(i)
            for key in _mv_date_cache:
                _mv_date_cache[key] = mv.iloc[_mv_date_cache[key]]
        mv_date_map = _mv_date_cache
        score["trade_date_dt"] = pd.to_datetime(score["trade_date"])
        # Filter to only SH/SZ stocks (MV data doesn't cover BJ/NQ)
        n_before = len(score)
        score = score[score["ts_code"].str.endswith((".SH", ".SZ"), na=False)].copy()
        if len(score) < n_before:
            print(f"    Filtered out {n_before - len(score)} non-SH/SZ stocks (BJ/NQ etc.)")

        new_scores = []
        n_ok, n_nan, n_fail, n_tiny = 0, 0, 0, 0
        ok_dates, nan_dates = [], []
        for dt, group in score.groupby("trade_date_dt"):
            if len(group) < 50: n_tiny += 1; continue
            dt_str3 = dt.strftime("%Y%m%d")
            mv_day = mv_date_map.get(dt_str3, pd.Series(dtype=float))
            if len(mv_day) < 50: n_tiny += 1; continue
            group = group.copy()
            mv_map2 = dict(zip(mv_day.index.get_level_values("instrument"), mv_day.values))
            mv_tushare = {}
            for k, v in mv_map2.items():
                new_k = re.sub(r'^(SZ|SH)(\d+)', r'\2.\1', k)
                mv_tushare[new_k] = v
            group["mv_val"] = group["ts_code"].map(mv_tushare)
            n_mapped = group["mv_val"].notna().sum()
            if n_mapped < 30:
                nan_dates.append(dt_str3)
                n_nan += 1; continue
            ok_dates.append(dt_str3)
            x = group["mv_val"].values; y = group["signal_score"].values
            ok = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
            if ok.sum() < 30: n_nan += 1; continue
            try:
                coef = np.polyfit(x[ok], y[ok], 1)
            except np.linalg.LinAlgError:
                n_fail += 1; continue
            group.loc[ok, "signal_score"] = y[ok] - np.polyval(coef, x[ok]) + np.nanmean(y[ok])
            new_scores.append(group[["ts_code", "trade_date", "signal_score", "strategy_id"]])
            n_ok += 1
        if new_scores:
            score = pd.concat(new_scores, ignore_index=True)
        print(f"    MV: processed={n_ok}/{n_ok+n_nan+n_fail+n_tiny} days, nan={n_nan}, fail={n_fail}, rows={len(score)}")

    # Industry neutralization: per-industry z-score
    if neutralize_ind and score is not None and not score.empty:
        print("    Neutralizing industry...")
        ind_map = load_industry_map()
        if ind_map and len(ind_map) > 0:
            ind_map_ts = {}
            for k, v in ind_map.items():
                new_k = re.sub(r'^(SZ|SH)(\d+)', r'\2.\1', k)
                ind_map_ts[new_k] = v
            score["_ind"] = score["ts_code"].map(ind_map_ts).fillna("various")
            n_unmapped = (score["_ind"] == "various").sum()
            n_industries = score["_ind"].nunique()
            score["signal_score"] = score.groupby("_ind")["signal_score"].transform(
                lambda x: (x - x.mean()) / x.std() if x.std() > 0 else x - x.mean()
            )
            score.drop(columns=["_ind"], inplace=True)
            print(f"    Ind: {n_industries} industries, unmapped={n_unmapped} rows, result NaN={score['signal_score'].isna().sum()}")

    # Volatility orthogonalization: daily regression signal ~ vol_rank
    if orthogonalize_vol and score is not None and not score.empty:
        print("    Orthogonalizing against volatility...")
        global _vol_date_cache
        if _vol_date_cache is None:
            print("    Building Vol date index (once)...")
            vol = df.groupby(level="instrument")["$return"].transform(lambda x: x.rolling(20).std())
            vol_align = vol.reindex(df.index).fillna(0)
            vol_dates = vol_align.index.get_level_values("datetime")
            _vol_date_cache = {}
            for i, d in enumerate(vol_dates):
                key = str(d)[:10].replace("-", "")
                if key not in _vol_date_cache: _vol_date_cache[key] = []
                _vol_date_cache[key].append(i)
            for key in _vol_date_cache:
                _vol_date_cache[key] = vol_align.iloc[_vol_date_cache[key]]
        vol_date_map = _vol_date_cache

        score["trade_date_dt"] = pd.to_datetime(score["trade_date"])
        new_scores_v = []
        nv_ok, nv_nan = 0, 0
        for dt, group in score.groupby("trade_date_dt"):
            if len(group) < 50: continue
            dt_str_v = dt.strftime("%Y%m%d")
            vol_day = vol_date_map.get(dt_str_v, pd.Series(dtype=float))
            if len(vol_day) < 50: continue
            group = group.copy()
            vol_map_v = dict(zip(vol_day.index.get_level_values("instrument"), vol_day.values))
            vol_map_ts = {}
            for k, v in vol_map_v.items():
                new_k = re.sub(r'^(SZ|SH)(\d+)', r'\2.\1', k)
                vol_map_ts[new_k] = v
            group["vol_val"] = group["ts_code"].map(vol_map_ts)
            x = group["vol_val"].rank().values; y = group["signal_score"].values
            ok = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
            if ok.sum() < 30: nv_nan += 1; continue
            try:
                coef = np.polyfit(x[ok], y[ok], 1)
                group.loc[ok, "signal_score"] = y[ok] - np.polyval(coef, x[ok])
            except np.linalg.LinAlgError:
                continue
            new_scores_v.append(group[["ts_code", "trade_date", "signal_score", "strategy_id"]])
            nv_ok += 1
        if new_scores_v:
            score = pd.concat(new_scores_v, ignore_index=True)
        print(f"    Vol: processed={nv_ok} days, nan={nv_nan}, rows={len(score)}")

    # Market filter
    print(f"    Market filter param: {repr(market_filter)}")
    if market_filter == "bear_only" and score is not None and not score.empty:
        idx_path = QA_ROOT / "data/index_returns.csv"
        if not idx_path.exists():
            print(f"    Market filter: index_returns.csv not found")
        else:
            idx_df = pd.read_csv(idx_path, dtype={"trade_date": str})
            idx_pool = idx_df[idx_df["pool"] == pool_name].copy()
            if not idx_pool.empty:
                idx_pool["dt"] = pd.to_datetime(idx_pool["trade_date"])
                idx_pool = idx_pool.set_index("dt").sort_index()
                idx_pool["rolling_10d"] = idx_pool["return"].rolling(10).mean()
                up_dates = set(str(d)[:10].replace("-", "") for d in idx_pool[idx_pool["rolling_10d"] > 0.005].index)
                n_up = len(up_dates)
                print(f"    Market filter: {n_up} up-market dates detected")
                if up_dates:
                    n_before = len(score)
                    score = score[~score["trade_date"].isin(up_dates)].copy()
                    print(f"    Market filter: removed {n_before - len(score)}/{n_before} up-market rows")

    if base.empty or score is None or score.empty:
        return None

    start_d, end_d = None, None
    if date_filter and len(date_filter) == 2:
        start_d, end_d = date_filter[0], date_filter[1]

    runner = get_qp_runner()
    try:
        result = runner(
            factor_score=score,
            backtest_base=base,
            strategy_id=factor_name,
            start_date=start_d,
            end_date=end_d,
            rebalance_interval=rebalance_interval,
            max_holdings=max_holdings,
            candidate_pool_size=max_holdings * 2,
            initial_cash=initial_cash,
            buy_cost_rate=0.00028,
            sell_cost_rate=0.00078,
            lot_size=100,
            score_ascending=False,
            hold_threshold_multiplier=hold_threshold,
        )
        return result
    except Exception as e:
        import traceback
        print(f"    QP backtest failed: {e}")
        traceback.print_exc()
        return None


def get_adaptive_params(turnover_est=0.3, pool="CSI2000", rebal_sensitivity=None):
    """根据 IC 衰减和换手率，自适应选择最优调仓频率和初始资金。

    逻辑：IC 保留率 ≥ 80% 的最长周期为基准，再按换手率微调（高换手→拉长省手续费）。
    CSI2000 跳过月度（仅 ~28 个数据点，统计不可靠）。
    """
    # 1. 构建可选频率阶梯（IC 保留率 ≥ 80%，数据点 ≥ 15）
    freq_ladder = []  # [(name, interval_days, retention)]
    freq_options = [("每日", 1), ("每周", 5), ("双周", 10)]
    # CSI2000 月度数据太少，跳过
    if pool != "CSI2000":
        freq_options.append(("月度", 20))

    if rebal_sensitivity:
        for label, interval in freq_options:
            info = rebal_sensitivity.get(label, {})
            if interval == 20:
                # 月度宽松一点：保留率 ≥ 60% 即可，但数据点要 ≥ 25
                if info.get("retention", 0) >= 0.60 and info.get("n_periods", 0) >= 25:
                    freq_ladder.append((label, interval, info["retention"]))
            else:
                if info.get("retention", 0) >= 0.80 and info.get("n_periods", 0) >= 15:
                    freq_ladder.append((label, interval, info["retention"]))

    # 2. 默认取最长可行频率
    all_labels = ["每日", "每周", "双周", "月度"]
    all_intervals = [1, 5, 10, 20]
    if freq_ladder:
        rebalance_interval = freq_ladder[-1][1]
    else:
        rebalance_interval = 1

    # 3. 按换手率微调：高换手 → 拉长一档，低换手 → 缩短一档
    if rebalance_interval in all_intervals:
        idx = all_intervals.index(rebalance_interval)
        if turnover_est > 0.5 and idx + 1 < len(all_intervals):
            # 对 CSI2000 跳过月度档位
            next_idx = idx + 1
            if pool == "CSI2000" and all_intervals[next_idx] == 20:
                pass  # skip monthly for CSI2000
            else:
                rebalance_interval = all_intervals[next_idx]
        elif turnover_est < 0.15 and idx - 1 >= 0:
            rebalance_interval = all_intervals[idx - 1]

    # 4. 初始资金
    pool_sizes = {"CSI300": 300, "CSI500": 500, "CSI1000": 1000, "CSI2000": 2000, "FULL": 5000}
    n_stocks = pool_sizes.get(pool, 2000)
    initial_cash = max(500_000, int(n_stocks * 1000 * min(turnover_est, 0.5)))
    return rebalance_interval, initial_cash, None

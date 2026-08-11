#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四股票池选中因子合成与 Quant-Project A 股回测入口。

本脚本负责读取最终因子清单、计算 point-in-time 池内信号、执行稳健性扫描、
生成目标持仓 CSV，并在非 --live 模式调用本地 Quant-Project 回测引擎。
QuantaAlpha、Quant-Project 和 daily_pv.h5 均为外部本地依赖，通过命令行或
config.toml 配置；运行 ``python scripts/run_selected_portfolio_qp.py --help``
不要求这些外部依赖存在。
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import re
import sys
import time
import types
from pathlib import Path

import numpy as np
import pandas as pd

import qp_backtest_bridge as qpb
from toolkit_paths import (
    ConfigurationError,
    collect_runtime_errors,
    format_runtime_errors,
    load_factor_names,
    resolve_toolkit_paths,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------- 参数 ----------
def build_parser():
    parser = argparse.ArgumentParser(
        description="四股票池选中因子合成与 Quant-Project 回测入口"
    )
    parser.add_argument("--config", help="TOML 路径配置文件")
    parser.add_argument("--qa-root", help="本地 QuantaAlpha 根目录")
    parser.add_argument("--qp-root", help="本地 Quant-Project 根目录")
    parser.add_argument("--data-path", help="daily_pv.h5 路径")
    parser.add_argument("--factor-list", help="每行一个因子的 UTF-8 TXT 文件")
    parser.add_argument("--output-dir", help="日志、结果、NAV 和目标持仓输出目录")
    parser.add_argument(
        "--pool",
        choices=["CSI300", "CSI500", "CSI1000", "CSI2000"],
        default="CSI2000",
    )
    parser.add_argument(
        "--sel-dir",
        help="兼容旧流程：从目录中的 *.html 文件名读取因子",
    )
    parser.add_argument(
        "--factors",
        default="",
        help="逗号分隔因子名，优先级最高",
    )
    parser.add_argument("--weight", choices=["icir", "equal"], default="icir")
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="剔除相关性超过阈值的冗余因子",
    )
    parser.add_argument("--dedup-thr", type=float, default=0.9)
    parser.add_argument("--rebal", default="auto", help="auto 或固定调仓日数")
    parser.add_argument("--max-holdings", type=int, default=50)
    parser.add_argument("--initial-cash", type=int, default=2_000_000)
    parser.add_argument("--no-neut-mv", dest="neut_mv", action="store_false")
    parser.add_argument("--no-neut-ind", dest="neut_ind", action="store_false")
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--slippage-sweep", default="")
    parser.add_argument("--rebal-sweep", default="")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--wf-warmup", type=int, default=120)
    parser.add_argument("--wf-window", type=int, default=0)
    parser.add_argument(
        "--benchmark",
        choices=["auto", "index", "equalweight"],
        default="auto",
    )
    parser.add_argument("--loo", action="store_true")
    parser.add_argument("--loo-split", default="20240101")
    parser.add_argument("--exclude", default="")
    parser.add_argument(
        "--live",
        action="store_true",
        help="仅生成最近信号日目标持仓 CSV，不连接券商或自动下单",
    )
    parser.set_defaults(neut_mv=True, neut_ind=True)
    return parser


ap = build_parser()
args = ap.parse_args()

try:
    paths = resolve_toolkit_paths(args, repo_root=REPO_ROOT)
except ConfigurationError as exc:
    ap.error(str(exc))

preflight_errors = collect_runtime_errors(
    paths,
    pool=args.pool,
    require_qp=not args.live,
    require_industry=args.neut_ind,
)
if preflight_errors:
    ap.error(format_runtime_errors(preflight_errors))

OUTPUT_DIR = paths.output_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 64)
print(f"  {args.pool} 选中因子合成回测  |  weight={args.weight}  dedup={args.dedup}")
print(f"  中性化: mv={args.neut_mv} ind={args.neut_ind}  rebal={args.rebal}  maxN={args.max_holdings}")
print("=" * 64)

# ---------- 进度落盘（供在对话侧实时查看运行到哪一步）----------
LOG_PATH = OUTPUT_DIR / f"run_progress_{args.pool}.log"
STATUS_PATH = OUTPUT_DIR / f"run_status_{args.pool}.json"
_T0 = time.time()
def log_stage(stage, msg="", pct=None):
    el = time.time() - _T0
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts} +{el:6.1f}s]" + (f" [{pct:3.0f}%]" if pct is not None else "       ") + f" {stage}" + (f" | {msg}" if msg else "")
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        json.dump({"pool": args.pool, "stage": stage, "msg": msg, "pct": pct,
                   "elapsed_sec": round(el, 1),
                   "updated": datetime.datetime.now().isoformat(timespec="seconds")},
                  open(STATUS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
open(LOG_PATH, "w").close()  # 清空上次日志
log_stage("启动", f"weight={args.weight} dedup={args.dedup} neut_mv={args.neut_mv} neut_ind={args.neut_ind}", 0)

# ---------- mock joblib（与 run_portfolio_icir 一致）----------
jb = types.ModuleType('joblib')
def _d(f):
    class _D:
        def __init__(s, fu): s.f = fu
        def __call__(s, *a, **kw): return (s.f, a, kw)
    return _D(f)
def _P(n=-1, **kw):
    class P:
        def __call__(self, tasks):
            return [t[0](*t[1]) if isinstance(t, tuple) else t() for t in tasks]
    return P()
jb.delayed, jb.Parallel = _d, _P
sys.modules['joblib'] = jb

# ---------- 载入表达式解析/函数库 ----------
spec = importlib.util.spec_from_file_location("ep", str(paths.expression_parser))
ep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ep)
spec2 = importlib.util.spec_from_file_location("fl", str(paths.function_library))
fl = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(fl)
for name in dir(ep):
    globals()[name] = getattr(ep, name)
for name in dir(fl):
    if not name.startswith("_"):
        globals()[name] = getattr(fl, name)

# ---------- 复用 bridge：base 构建 + QP 回测入口 ----------
qpb.configure_paths(paths.qa_root, paths.qp_root)
run_qp = None if args.live else qpb.get_qp_runner()
build_base = qpb.build_backtest_base_from_hdf5

DATA_PATH = paths.data_path
FACTORLIB = paths.factor_library_dir

# ---------- 1. 读取选中因子名 ----------
def _normalize_selected(items):
    names = []
    seen = set()
    for raw in items:
        name = str(raw).strip()
        if args.pool == "CSI2000" and name.endswith("_副本"):
            name = name[: -len("_副本")]
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


if args.factors:
    selected = _normalize_selected(args.factors.split(","))
elif args.factor_list:
    try:
        selected = load_factor_names(
            Path(args.factor_list),
            strip_copy_suffix=args.pool == "CSI2000",
        )
    except ConfigurationError as exc:
        ap.error(str(exc))
elif args.sel_dir:
    selected = _normalize_selected(
        Path(item).stem
        for item in sorted(glob.glob(os.path.join(args.sel_dir, "*.html")))
    )
    if not selected:
        ap.error(f"在 {args.sel_dir} 没找到 *.html 因子文件")
else:
    default_factor_list = REPO_ROOT / "data" / f"factors_{args.pool}.txt"
    try:
        selected = load_factor_names(
            default_factor_list,
            strip_copy_suffix=args.pool == "CSI2000",
        )
    except ConfigurationError as exc:
        ap.error(str(exc))

print(f"\n选中因子 {len(selected)} 个:")
for s in selected: print("  -", s)
log_stage("读取选中因子", f"{len(selected)}个", 2)

# ---------- 2. 因子名 → 表达式 ----------
name2expr = {}
for lib in glob.glob(str(FACTORLIB / "all_factors_library_*_full.json")):
    d = json.load(open(lib, encoding="utf-8"))
    for fid, fac in d["factors"].items():
        name2expr[fac["factor_name"]] = fac["factor_expression"]
missing = [s for s in selected if s not in name2expr]
if missing:
    ap.error("因子库缺少表达式:\n" + "\n".join(f"  - {name}" for name in missing))

# ---------- 3. 载入数据 + 池 mask（与 run_portfolio_icir 同口径）----------
print(f"\n载入数据 {DATA_PATH} ...")
log_stage("载入数据中", "读取 daily_pv.h5 (约1.9GB,较慢)", 5)
df = pd.read_hdf(DATA_PATH, key="data")
required_columns = {"$return", "$open", "$close", "$high", "$low", "$volume"}
if args.neut_mv:
    required_columns.add("$circ_mv")
missing_columns = sorted(required_columns - set(df.columns))
if missing_columns:
    ap.error(f"daily_pv.h5 缺少必要列: {missing_columns}")
df = df.groupby(df.index.names).first()
print(f"  记录数: {len(df):,}")
log_stage("数据载入完成", f"{len(df):,}行", 12)
dts = df.index.get_level_values("datetime")
ins = df.index.get_level_values("instrument")

def _to_qlib(c): return re.sub(r'(\d+)\.(\w+)', r'\2\1', c)

POOL = args.pool
schedule_file = paths.schedule(POOL)
pool_mask = np.zeros(len(df), dtype=bool)
if schedule_file.exists():
    sched = json.load(open(schedule_file))
    for s in sched:
        sd = pd.Timestamp(s["snap_date"])
        ed = pd.Timestamp(s["out_date"]) if s["out_date"] else dts.max() + pd.Timedelta(days=1)
        codes = set(_to_qlib(c) for c in s["codes"])
        pool_mask |= (dts >= sd) & (dts <= ed) & np.array(ins.map(lambda x: x in codes))
    print(f"  {POOL}: 真实调仓表 {len(sched)} 期")
else:
    sys.exit(f"[错误] 缺 {schedule_file}")

pool_stocks = set(df.index.get_level_values("instrument")[pool_mask].unique())
uni_mask = np.where(np.array(df.index.get_level_values("instrument").map(lambda x: x in pool_stocks)))[0]
df_univ = df.iloc[uni_mask]
# 逐(股,日) point-in-time 成分股掩码，对齐 df_univ：仅"当期真实成分股"为 True。
# 因子仍在全 universe / 全历史上计算（保证滚动窗口完整），但 IC/排序/交易只在当期成分内进行，
# 从而 (a) 强制半年一次的成分调入调出 (b) 自动把区间限制到 schedule 最早日期(2024-01-31)，消除区间泄漏。
pit_member = pool_mask[uni_mask]
print(f"  池内: {int(pool_mask.sum()):,} 行 / universe(全历史): {len(df_univ):,} 行 / {len(pool_stocks)} 只")
print(f"  point-in-time 当期成分行数: {int(pit_member.sum()):,}（仅这些参与 IC/排序/交易）")
log_stage("池构建完成", f"universe {len(df_univ):,}行 / PIT当期成分 {int(pit_member.sum()):,}行 / {len(pool_stocks)}只", 16)

# 行业映射（行业中性化用）
ind_map = qpb.load_industry_map() if args.neut_ind else {}

# ---------- 4. 逐因子计算 + 中性化 + IC/ICIR + rank ----------
_avail_cols = sorted(df_univ.columns.tolist(), key=lambda x: -len(x))
if args.neut_mv:
    lmv = np.log(df_univ["$circ_mv"].abs() + 1)
if args.neut_ind:
    ind_series = pd.Series(df_univ.index.get_level_values("instrument").map(lambda x: ind_map.get(x, "NA")),
                           index=df_univ.index)

def neutralize(result):
    """对因子值逐日截面做 市值 / 行业 中性化。"""
    if args.neut_mv:
        neut = result.copy()
        for dt in result.index.get_level_values("datetime").unique():
            dm = np.where(result.index.get_level_values("datetime") == dt)[0]
            x = lmv.iloc[dm].values; y = result.iloc[dm].values
            ok = ~(np.isnan(x) | np.isnan(y))
            if ok.sum() < 10: continue
            coef = np.polyfit(x[ok], y[ok], 1)
            neut.iloc[dm] = y - np.polyval(coef, x) + np.nanmean(y[ok])
        result = neut
    if args.neut_ind:
        # 行业内去均值
        tmp = pd.DataFrame({"v": result.values,
                            "dt": result.index.get_level_values("datetime"),
                            "ind": ind_series.values}, index=result.index)
        grp = tmp.groupby(["dt", "ind"])["v"].transform("mean")
        result = result - grp + np.nanmean(result.values)
    return result

factor_ranks = {}   # name -> per-day 原始 pct rank（不预套方向）
icir = {}           # name -> 全样本 |ICIR|
sign_full = {}      # name -> 全样本方向(+1/-1)
daily_ic = {}       # name -> 日频IC序列(供walk-forward)
_nsel = len(selected)
for _i, name in enumerate(selected):
    log_stage(f"计算因子 {_i+1}/{_nsel}", name, 16 + 44.0 * _i / max(_nsel, 1))
    expr = name2expr[name]
    try:
        ee = ep.parse_symbol(expr, df_univ.columns)
        ee = ep.parse_expression(ee)
        for col in _avail_cols:
            ee = re.sub(r'\b' + re.escape(col[1:]) + r'\b', f"df_univ['{col}']", ee)
        # Compatibility boundary: expressions must come from a trusted local
        # QuantaAlpha factor library. Never evaluate untrusted user input here.
        result = eval(ee)
        if isinstance(result, pd.DataFrame): result = result.iloc[:, 0]
        result = pd.Series(result, index=df_univ.index).astype(np.float64)
    except Exception as e:
        print(f"  [跳过] {name}: 计算失败 {e}"); continue
    if result.isna().all():
        print(f"  [跳过] {name}: 全NaN"); continue
    if args.neut_mv or args.neut_ind:
        try: result = neutralize(result)
        except Exception as e: print(f"  [警告] {name} 中性化失败,用原值: {e}")
    # 仅在 point-in-time 当期成分股内做 IC 与排序（强制半年换仓 + 限制到真实指数区间）
    rp = result.iloc[np.where(pit_member)[0]]
    tmp = pd.DataFrame({"_fv": rp})
    tmp["_fr"] = df["$return"].reindex(rp.index).groupby(level="instrument").shift(-1)
    valid = tmp.dropna()
    dic = valid.groupby(level="datetime").apply(
        lambda g: g["_fv"].rank().corr(g["_fr"].rank()) if len(g) >= 15 else np.nan).dropna()
    ic_mean = dic.mean(); ic_std = dic.std()
    ir = ic_mean / ic_std if ic_std > 0 else 0.0
    # 方向对齐：IC为负则反向（合成前统一为正向预测）
    sign = 1.0 if ic_mean >= 0 else -1.0
    icir[name] = abs(ir)
    sign_full[name] = sign
    daily_ic[name] = dic                      # 每因子日频IC序列（供walk-forward滚动估计权重/方向）
    factor_ranks[name] = rp.groupby(level="datetime").rank(pct=True)   # 原始pct-rank，不预套方向
    print(f"  {name[:44]:44s} IC={ic_mean:+.4f} ICIR={ir:+.3f} {'(反向)' if sign<0 else ''}")

kept = list(factor_ranks.keys())
if len(kept) < 2:
    sys.exit("[错误] 有效因子不足2个,无法合成")
log_stage("因子计算完成", f"有效 {len(kept)}/{_nsel}", 60)

# ---------- 5. 可选去重（相关性>阈值,保留ICIR更高者）----------
def _aligned_rank(n):
    """方向对齐后的 pct-rank（负向因子取 1-rank），用于去重相关与全样本合成。"""
    return factor_ranks[n] if sign_full[n] >= 0 else (1.0 - factor_ranks[n])

if args.dedup:
    # 用方向对齐后的池内 pct-rank 的日截面相关近似
    order = sorted(kept, key=lambda n: -icir[n])
    keep = []
    aligned = {n: _aligned_rank(n) for n in order}
    for n in order:
        redundant = False
        for k in keep:
            common = aligned[n].index.intersection(aligned[k].index)
            if len(common) < 100: continue
            c = aligned[n].loc[common].corr(aligned[k].loc[common])
            if c is not None and c > args.dedup_thr:
                print(f"  [去重] 剔除 {n} (与 {k} 相关 {c:.2f} > {args.dedup_thr})")
                redundant = True; break
        if not redundant: keep.append(n)
    kept = keep
    print(f"  去重后保留 {len(kept)} 个: {kept}")
    log_stage("去重完成", f"保留 {len(kept)} 个: {','.join(kept)}", 64)

# ---------- 5b. 剔除指定因子（固定最终因子集）----------
if args.exclude:
    excl = set(x.strip() for x in args.exclude.split(",") if x.strip())
    hit = [n for n in kept if n in excl]
    kept = [n for n in kept if n not in excl]
    print(f"  [排除] 剔除 {hit} -> 剩 {len(kept)} 个: {kept}")
    if len(kept) < 2: sys.exit("[错误] 剔除后因子不足2个")

# ---------- 6. 合成信号（动态权重）----------
WF = bool(args.walk_forward)

def build_composite(factors, verbose=False):
    """把给定因子子集合成一条信号(WF或全样本)。供主流程与LOO复用。"""
    ad = sorted(set(d for n in factors for d in factor_ranks[n].index.get_level_values("datetime").unique()))
    if WF:
        icm = pd.DataFrame({n: daily_ic[n] for n in factors if n in daily_ic}).sort_index()
        if args.wf_window <= 0:
            em_ = icm.expanding(min_periods=args.wf_warmup).mean().shift(1)
            es_ = icm.expanding(min_periods=args.wf_warmup).std().shift(1)
        else:
            em_ = icm.rolling(args.wf_window, min_periods=args.wf_warmup).mean().shift(1)
            es_ = icm.rolling(args.wf_window, min_periods=args.wf_warmup).std().shift(1)
        wabs = (em_ / es_).abs().reindex(ad).ffill()
        wsg = np.sign(em_).reindex(ad).ffill()
        if args.weight == "equal":
            wabs = wabs.notna().astype(float).where(wabs.notna())
    else:
        if args.weight == "icir":
            wv = np.array([icir[n] for n in factors]); wv = wv / wv.sum() if wv.sum() > 0 else np.ones(len(factors)) / len(factors)
        else:
            wv = np.ones(len(factors)) / len(factors)
        wm = dict(zip(factors, wv))
    parts = []; n_skip = 0
    for date in ad:
        if WF:
            wrow = wabs.loc[date]; srow = wsg.loc[date]
            if not np.isfinite(wrow.to_numpy(dtype=float)).any():
                n_skip += 1; continue
        avail, ws = [], []
        for n in factors:
            rk = factor_ranks[n]
            dr = rk.loc[rk.index.get_level_values("datetime") == date].dropna()
            if len(dr) < 30: continue
            if WF:
                wi = wrow.get(n, np.nan); si = srow.get(n, np.nan)
                if not (np.isfinite(wi) and np.isfinite(si)) or wi <= 0 or si == 0: continue
                avail.append(dr if si > 0 else (1.0 - dr)); ws.append(float(wi))
            else:
                avail.append(dr if sign_full[n] >= 0 else (1.0 - dr)); ws.append(wm[n])
        if len(avail) < 2: continue
        ws = np.array(ws); ws = ws / ws.sum() if ws.sum() > 0 else np.ones(len(ws)) / len(ws)
        sig = None
        for dr, ww in zip(avail, ws):
            sig = dr * ww if sig is None else sig.add(dr * ww, fill_value=0)
        parts.append(sig)
    comp = pd.concat(parts)
    if verbose and WF:
        print(f"  walk-forward({'expanding' if args.wf_window<=0 else 'rolling'+str(args.wf_window)}): 跳过预热{n_skip}天, 有效信号从 {comp.index.get_level_values('datetime').min().date()} 起")
    return comp

def composite_to_score(comp, sid=None):
    rows = []
    sid = sid or f"{POOL}_selected_{args.weight}"
    for (inst, dt), val in comp.dropna().items():
        ts = re.sub(r"^(SH|SZ)(\d+)", r"\2.\1", inst)
        rows.append({"ts_code": ts, "trade_date": pd.Timestamp(dt).strftime("%Y%m%d"), "signal_score": float(val), "strategy_id": sid})
    return pd.DataFrame(rows)

print(f"\n合成 {len(kept)} 因子信号 ({'walk-forward '+('expanding' if args.wf_window<=0 else 'rolling'+str(args.wf_window)) if WF else '全样本 weight='+args.weight}) ...")
composite = build_composite(kept, verbose=True)
print(f"  合成信号点数: {len(composite):,}")
log_stage("合成信号完成", f"{len(kept)}因子 / {len(composite):,}点{' (WF)' if WF else ''}", 68)

# ---------- 6b. 自适应调仓频率（按合成信号自身 IC 衰减 + 换手，与单因子报告同口径）----------
if str(args.rebal).lower() == "auto":
    log_stage("推算自适应调仓", "基于合成信号IC衰减+换手", 69)
    comp = composite.dropna()
    # 合成信号日频 Rank IC（vs 次日收益，当期成分内）
    nret = df["$return"].reindex(comp.index).groupby(level="instrument").shift(-1)
    cdf = pd.DataFrame({"_s": comp, "_r": nret}).dropna()
    cic = cdf.groupby(level="datetime").apply(
        lambda g: g["_s"].rank().corr(g["_r"].rank()) if len(g) >= 15 else np.nan).dropna()
    rebal_sens = {}
    if len(cic) >= 60 and cic.mean() != 0:
        for freq, label in [(1, "每日"), (5, "每周"), (10, "双周"), (20, "月度")]:
            sub = cic.iloc[::freq]
            if len(sub) >= 15:
                rebal_sens[label] = {"retention": round(float(sub.mean() / cic.mean()), 3), "n_periods": len(sub)}
    # 合成信号换手：相邻交易日 Top-20% 成分重叠（与 factor_deep_analysis 同定义）
    tos, prev_top = [], None
    for dt, day in comp.groupby(level="datetime"):
        k = max(1, int(0.2 * len(day)))
        top = set(day.nlargest(k).index.get_level_values("instrument"))
        if prev_top: tos.append(1 - len(top & prev_top) / len(prev_top))
        prev_top = top
    turnover_est = float(np.mean(tos)) if tos else 0.3
    REBAL, _adap_cash, _ = qpb.get_adaptive_params(
        turnover_est,
        POOL,
        rebal_sensitivity=rebal_sens,
    )
    print(f"  自适应调仓: 保留率={ {k: v['retention'] for k, v in rebal_sens.items()} }  换手≈{turnover_est:.1%}  ->  {REBAL}日")
    log_stage("自适应调仓确定", f"{REBAL}日 (换手≈{turnover_est:.1%})", 71)
else:
    REBAL = int(args.rebal)
    print(f"  固定调仓: {REBAL}日")

# ---------- 6c. 实盘模式：出最近交易日的目标持仓清单 ----------
if args.live:
    log_stage("生成目标持仓", "取最近交易日合成打分Top-N", 90)
    latest = composite.index.get_level_values("datetime").max()
    day = composite.loc[composite.index.get_level_values("datetime") == latest].dropna()
    day = day.sort_values(ascending=False).head(args.max_holdings)   # 当期成分内(composite已gate) Top-N
    closes = df_univ["$close"].loc[df_univ.index.get_level_values("datetime") == latest]
    n = len(day); per = args.initial_cash / max(n, 1)
    rows = []
    for (inst, dt), sc in day.items():
        ts = re.sub(r"^(SH|SZ|BJ)(\d+)", r"\2.\1", inst)   # 含北交所BJ->NNNNNN.BJ
        px = float(closes.get((inst, dt), np.nan))
        shares = int((per / px) // 100 * 100) if np.isfinite(px) and px > 0 else 0
        rows.append({"ts_code": ts, "score": round(float(sc), 5), "target_weight": round(1.0 / n, 4),
                     "last_close": round(px, 3) if np.isfinite(px) else None,
                     "suggest_shares": shares, "suggest_amount": round(shares * px, 0) if np.isfinite(px) else 0})
    tp = pd.DataFrame(rows)
    dstr = pd.Timestamp(latest).strftime("%Y%m%d")
    out = OUTPUT_DIR / f"target_portfolio_{POOL}_{dstr}.csv"
    tp.to_csv(out, index=False)
    print("\n" + "=" * 70)
    print(f"  目标持仓清单  信号日={pd.Timestamp(latest).date()}  {n}只等权  AUM={args.initial_cash:,}  调仓周期{REBAL}日")
    print(f"  实际投入约 {tp['suggest_amount'].sum():,.0f} (剩余现金留作整手误差)")
    print("=" * 70)
    print(tp.head(15).to_string(index=False))
    if n > 15: print(f"  ... 共{n}只，完整见 CSV")
    print(f"\n目标持仓 -> {out}")
    log_stage("完成 ✓", f"目标持仓{n}只 信号日{pd.Timestamp(latest).date()}", 100)
    print("Done!")
    sys.exit(0)

# ---------- 7. 构造 QP score 表 + base ----------
score = composite_to_score(composite)
print(f"  score 表: {len(score):,} 行")
log_stage("score表完成", f"{len(score):,}行", 72)
print("  构建回测 base ...")
log_stage("构建回测base中", "含板块涨跌停+停牌标志", 75)
base = build_base(df, pool_mask)
log_stage("base完成", f"{len(base):,}行", 80)

# ---------- 8. 跑 QP 回测（支持滑点）----------
BASE_BUY, BASE_SELL = 0.00028, 0.00078   # 佣金+印花税(现行)
suffix = "_dedup" if args.dedup else ""
if args.exclude:
    suffix += f"_ex{len([x for x in args.exclude.split(',') if x.strip()])}"  # 剔除N个因子,区分文件名避免覆盖
if WF:
    suffix += "_wf" + ("exp" if args.wf_window <= 0 else str(args.wf_window))  # 区分WF模式,避免覆盖
if str(args.rebal).lower() != "auto":
    suffix += f"_rb{int(args.rebal)}"

# 回测窗口：限制到首个/末个真实成分日，避免 2021-2023 空仓年份稀释年化/夏普等指标
START_DATE = pd.Timestamp(min(composite.index.get_level_values("datetime"))).strftime("%Y%m%d")
END_DATE = pd.Timestamp(max(composite.index.get_level_values("datetime"))).strftime("%Y%m%d")
print(f"  回测窗口: {START_DATE} ~ {END_DATE}（限制到真实成分区间，不含空仓年份）")

def load_benchmark(pool, d0, d1):
    """读取指数日收益，算区间年化/夏普/回撤，并返回日收益 df 供算信息比率。"""
    p = paths.index_returns
    if not p.exists():
        print("  [基准] 缺 data/index_returns.csv，跳过基准对比"); return None
    idx = pd.read_csv(p, dtype={"trade_date": str})
    idx = idx[idx["pool"] == pool].copy()
    idx = idx[(idx["trade_date"] >= str(d0)) & (idx["trade_date"] <= str(d1))].sort_values("trade_date")
    if len(idx) < 2: return None
    r = idx["return"].astype(float).values
    cum = float(np.prod(1 + r) - 1)
    ann = float((1 + cum) ** (252 / len(r)) - 1)
    sh = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    navi = np.cumprod(1 + r); dd = float((navi / np.maximum.accumulate(navi) - 1).min())
    return {"ann": ann, "cum": cum, "sharpe": sh, "maxdd": dd, "df": idx[["trade_date", "return"]]}

def benchmark_equalweight(d0, d1):
    """池内等权基准：逐日 point-in-time 成分股的等权平均收益（proxy池无外部指数时用）。"""
    mret = df_univ["$return"].iloc[np.where(pit_member)[0]]
    ew = mret.groupby(level="datetime").mean().dropna()
    ew.index = pd.to_datetime(ew.index)
    bdf = pd.DataFrame({"trade_date": ew.index.strftime("%Y%m%d"), "return": ew.values})
    bdf = bdf[(bdf["trade_date"] >= str(d0)) & (bdf["trade_date"] <= str(d1))].sort_values("trade_date")
    if len(bdf) < 2: return None
    r = bdf["return"].astype(float).values
    cum = float(np.prod(1 + r) - 1)
    ann = float((1 + cum) ** (252 / len(r)) - 1)
    sh = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    navi = np.cumprod(1 + r); dd = float((navi / np.maximum.accumulate(navi) - 1).min())
    return {"ann": ann, "cum": cum, "sharpe": sh, "maxdd": dd, "df": bdf}

def get_benchmark(d0, d1):
    """按 --benchmark 选择基准：equalweight=池内等权；index=外部指数；auto=有外部指数用指数,否则等权。"""
    if args.benchmark == "equalweight":
        return benchmark_equalweight(d0, d1)
    bm = load_benchmark(POOL, d0, d1)
    if bm is None and args.benchmark == "auto":
        print(f"  [基准] index_returns.csv 无 {POOL}，改用池内等权基准")
        return benchmark_equalweight(d0, d1)
    return bm

def _run_bt(slip_bps, rebal=None):
    """在基础成本上叠加单边滑点(bps)再跑回测。rebal=None 用自适应/指定的 REBAL。"""
    slip = slip_bps / 1e4
    rr = rebal if rebal is not None else REBAL
    res = run_qp(
        factor_score=score, backtest_base=base, strategy_id=f"{POOL}_selected_{args.weight}",
        start_date=START_DATE, end_date=END_DATE,
        rebalance_interval=rr, max_holdings=args.max_holdings,
        candidate_pool_size=args.max_holdings * 2, initial_cash=args.initial_cash,
        buy_cost_rate=BASE_BUY + slip, sell_cost_rate=BASE_SELL + slip, lot_size=100,
        score_ascending=False, hold_threshold_multiplier=2.0,
    )
    return res

# ===== 因子留一法(LOO)归因：全部 + 逐个去掉一个因子，看每个因子对超额的边际贡献(全段+两段) =====
if args.loo:
    print(f"\n因子留一法(LOO): 全部 + 逐个去1 (共{len(kept)+1}次回测), 两段分界={args.loo_split}")
    SP = args.loo_split
    bm = get_benchmark(START_DATE, END_DATE)
    bm_h1 = get_benchmark(START_DATE, str(int(SP) - 1)); bm_h2 = get_benchmark(SP, END_DATE)
    slip = args.slippage_bps / 1e4
    def _ann(nav, d0, d1):
        if nav is None or getattr(nav, "empty", True): return None
        td = nav["trade_date"].astype(str)
        sub = nav[(td >= str(d0)) & (td <= str(d1))]
        if len(sub) < 2: return None
        col = "nav" if "nav" in sub.columns else "total_equity"
        v = sub[col].astype(float).values
        return float((v[-1] / v[0]) ** (252 / len(v)) - 1)
    def _loo_eval(factors, label):
        sc = composite_to_score(build_composite(factors), sid=f"loo_{label}")
        res = run_qp(factor_score=sc, backtest_base=base, strategy_id=f"loo_{label}",
                     start_date=START_DATE, end_date=END_DATE,
                     rebalance_interval=REBAL, max_holdings=args.max_holdings,
                     candidate_pool_size=args.max_holdings * 2, initial_cash=args.initial_cash,
                     buy_cost_rate=BASE_BUY + slip, sell_cost_rate=BASE_SELL + slip, lot_size=100,
                     score_ascending=False, hold_threshold_multiplier=2.0)
        if not (res and res.get("metrics")): return {"label": label, "error": "no metrics"}
        m = res["metrics"]; nav = res.get("nav")
        a1 = _ann(nav, START_DATE, str(int(SP) - 1)); a2 = _ann(nav, SP, END_DATE)
        return {"label": label, "n": len(factors), "annual": m.get("annual_return"), "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "excess": (m.get("annual_return") - bm["ann"]) if bm else None,
                "excess_h1": (a1 - bm_h1["ann"]) if (a1 is not None and bm_h1) else None,
                "excess_h2": (a2 - bm_h2["ann"]) if (a2 is not None and bm_h2) else None}
    rows_out = [_loo_eval(kept, "全部")]
    base_exc = rows_out[0].get("excess"); base_h1 = rows_out[0].get("excess_h1"); base_h2 = rows_out[0].get("excess_h2")
    for i, drop in enumerate(kept):
        log_stage(f"LOO {i+1}/{len(kept)}", f"去 {drop}", 82 + 16.0 * i / max(len(kept), 1))
        rows_out.append(_loo_eval([n for n in kept if n != drop], f"去_{drop}"))
    print("\n" + "=" * 100)
    print(f"  ===== {POOL} 因子留一法归因 ({args.weight}权 · 调仓{REBAL}日 · 两段分界{SP}) =====")
    if bm: print(f"  基准全段年化{bm['ann']:+.1%} | H1({START_DATE}~{int(SP)-1})年化{bm_h1['ann']:+.1%} | H2({SP}~{END_DATE})年化{bm_h2['ann']:+.1%}")
    print(f"  {'方案':40} {'全段超额':>9} {'边际全':>8} {'边际H1':>8} {'边际H2':>8} {'一致?':>6}")
    for r in rows_out:
        if "error" in r: print(f"  {r['label']:40} (失败)"); continue
        if r["label"] == "全部":
            print(f"  {r['label']:40} {r['excess']:+8.1%} {'基准':>8}"); continue
        mg = base_exc - r["excess"] if (base_exc is not None and r["excess"] is not None) else None
        m1 = base_h1 - r["excess_h1"] if (base_h1 is not None and r["excess_h1"] is not None) else None
        m2 = base_h2 - r["excess_h2"] if (base_h2 is not None and r["excess_h2"] is not None) else None
        cons = ("✓" if (m1 is not None and m2 is not None and (m1 > 0) == (m2 > 0)) else "✗") if (m1 is not None and m2 is not None) else "?"
        r["marg_full"] = mg; r["marg_h1"] = m1; r["marg_h2"] = m2; r["consistent"] = cons
        f = lambda x: f"{x:+8.1%}" if x is not None else "     n/a"
        print(f"  {r['label']:40} {r['excess']:+8.1%} {f(mg)} {f(m1)} {f(m2)} {cons:>6}")
    print("=" * 100)
    print("  边际>0=该因子有贡献,<0=拖累; 一致✓=两段同号(可据此增删), ✗=regime依赖(不宜删)")
    out = OUTPUT_DIR / f"loo_{POOL}_{args.weight}{suffix}.json"
    json.dump({"pool": POOL, "weight": args.weight, "rebal": REBAL, "window": [START_DATE, END_DATE], "split": SP,
               "benchmark": ({"annual": bm["ann"]} if bm else None), "loo": rows_out},
              open(out, "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n结果 -> {out}")
    log_stage("完成 ✓", f"两段LOO {len(kept)}因子归因完成", 100)
    print("Done!")
    sys.exit(0)

# ===== 调仓周期扫描：一次数据/因子，多个调仓周期各回测一次 =====
rebal_sweep = [int(x) for x in args.rebal_sweep.split(",") if x.strip() != ""] if args.rebal_sweep else None
if rebal_sweep:
    print(f"\n调仓周期扫描: {rebal_sweep} 日（滑点 {args.slippage_bps:.0f}bps/边）")
    bm = get_benchmark(START_DATE, END_DATE)
    rows_out = []
    for si, rb in enumerate(rebal_sweep):
        log_stage(f"调仓回测 {si+1}/{len(rebal_sweep)}", f"{rb}日", 82 + 16.0 * si / max(len(rebal_sweep), 1))
        res = _run_bt(args.slippage_bps, rebal=rb)
        if res and res.get("metrics"):
            m = res["metrics"]
            ann = m.get("annual_return")
            rows_out.append({"rebal": rb, "annual_return": ann, "sharpe": m.get("sharpe"),
                             "max_drawdown": m.get("max_drawdown"), "total_return": m.get("total_return"),
                             "avg_turnover_daily": m.get("average_turnover"),
                             "annual_turnover": (m.get("average_turnover") or 0) * 252,
                             "excess_annual": (ann - bm["ann"]) if bm else None})
        else:
            rows_out.append({"rebal": rb, "error": "no metrics"})
    print("\n" + "=" * 82)
    print(f"  ===== {POOL} 调仓周期扫描 (去重{len(kept)}因子 · {args.weight}权 · 滑点{args.slippage_bps:.0f}bps · {START_DATE}~{END_DATE}) =====")
    if bm: print(f"  基准 {POOL}指数: 年化{bm['ann']:+.1%}  夏普{bm['sharpe']:.2f}")
    print(f"  {'调仓日':>6} {'年化':>8} {'夏普':>6} {'回撤':>8} {'日均换手':>8} {'年化换手':>9} {'超额年化':>9}")
    for r in rows_out:
        if "error" in r: print(f"  {r['rebal']:>6d}  (回测失败)"); continue
        exc = f"{r['excess_annual']:>+8.1%}" if r["excess_annual"] is not None else "   n/a"
        print(f"  {r['rebal']:>6d} {r['annual_return']:>7.1%} {r['sharpe']:>6.2f} {r['max_drawdown']:>7.1%} "
              f"{r['avg_turnover_daily']:>7.1%} {r['annual_turnover']:>8.0%} {exc}")
    print("=" * 82)
    out = OUTPUT_DIR / f"rebal_sweep_{POOL}_{args.weight}{suffix}.json"
    json.dump({"pool": POOL, "weight": args.weight, "dedup": args.dedup, "window": [START_DATE, END_DATE],
               "slippage_bps": args.slippage_bps, "factors": kept,
               "benchmark": ({"annual": bm["ann"], "sharpe": bm["sharpe"], "maxdd": bm["maxdd"]} if bm else None),
               "sweep": rows_out}, open(out, "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n结果 -> {out}")
    log_stage("完成 ✓", f"调仓扫描{len(rebal_sweep)}档 {rebal_sweep}日", 100)
    print("Done!")
    sys.exit(0)

sweep_levels = [float(x) for x in args.slippage_sweep.split(",") if x.strip() != ""] if args.slippage_sweep else None

if sweep_levels:
    # ===== 滑点扫描：一次数据/因子，多档回测 =====
    print(f"\n滑点扫描: {sweep_levels} bps（单边）")
    rows_out = []
    for si, bps in enumerate(sweep_levels):
        pct = 82 + 16.0 * si / max(len(sweep_levels), 1)
        log_stage(f"滑点回测 {si+1}/{len(sweep_levels)}", f"{bps:.0f}bps/边", pct)
        res = _run_bt(bps)
        if res and res.get("metrics"):
            m = res["metrics"]
            rows_out.append({"slippage_bps": bps, "annual_return": m.get("annual_return"),
                             "sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown"),
                             "total_return": m.get("total_return"), "win_rate": m.get("win_rate"),
                             "average_turnover": m.get("average_turnover")})
        else:
            rows_out.append({"slippage_bps": bps, "error": "no metrics"})
    print("\n" + "=" * 72)
    print(f"  ===== {POOL} 滑点压力测试 ({'去重' if args.dedup else '原始'} · {len(kept)}因子 · {args.weight}权) =====")
    print(f"  {'滑点bps/边':>10} {'年化':>9} {'夏普':>7} {'最大回撤':>9} {'累计':>9} {'日胜率':>7}")
    for r in rows_out:
        if "error" in r: print(f"  {r['slippage_bps']:>10.0f}  (回测失败)"); continue
        print(f"  {r['slippage_bps']:>10.0f} {r['annual_return']:>8.1%} {r['sharpe']:>7.2f} "
              f"{r['max_drawdown']:>8.1%} {r['total_return']:>8.1%} {r['win_rate']:>6.1%}")
    print("=" * 72)
    bm = get_benchmark(START_DATE, END_DATE)
    if bm:
        print(f"  基准 {POOL}指数 同区间: 年化{bm['ann']:+.1%}  夏普{bm['sharpe']:.2f}  回撤{bm['maxdd']:+.1%}")
        print(f"  {'滑点bps/边':>10} {'超额年化':>10} {'是否跑赢':>9}")
        for r in rows_out:
            if "error" in r: continue
            exc = r["annual_return"] - bm["ann"]
            r["excess_annual"] = exc
            print(f"  {r['slippage_bps']:>10.0f} {exc:>+9.1%} {'跑赢' if exc > 0 else '跑输':>9}")
        print("=" * 72)
    out = OUTPUT_DIR / f"slippage_sweep_{POOL}_{args.weight}{suffix}.json"
    json.dump({"pool": POOL, "weight": args.weight, "dedup": args.dedup, "rebal": REBAL, "factors": kept,
               "window": [START_DATE, END_DATE],
               "benchmark": ({"annual": bm["ann"], "sharpe": bm["sharpe"], "maxdd": bm["maxdd"]} if bm else None),
               "base_cost": {"buy": BASE_BUY, "sell": BASE_SELL}, "sweep": rows_out},
              open(out, "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n结果 -> {out}")
    last = rows_out[-1]
    log_stage("完成 ✓", f"扫描{len(sweep_levels)}档; 末档{last.get('slippage_bps'):.0f}bps 年化{last.get('annual_return',0):+.1%} 夏普{last.get('sharpe',0):+.2f}", 100)
    print("Done!")
    sys.exit(0)

# ===== 单跑（可带 --slippage-bps）=====
print(f"\n运行 Quant-Project 回测 ... (滑点 {args.slippage_bps:.0f}bps/边)")
log_stage("QP回测运行中", f"最耗时的一步,引擎逐日撮合;滑点{args.slippage_bps:.0f}bps;详细输出见终端", 82)
result = _run_bt(args.slippage_bps)

# ---------- 9. 输出 ----------
if result and result.get("metrics"):
    m = result["metrics"]
    nav = result.get("nav")
    print("\n" + "=" * 64)
    print(f"  ===== {POOL} 组合回测结果（成本后 · {'中性化' if args.neut_mv or args.neut_ind else '未中性化'} · 滑点{args.slippage_bps:.0f}bps · {START_DATE}~{END_DATE}）=====")
    print(f"  因子数        : {len(kept)}  (weight={args.weight}, rebal={REBAL}日)")
    print(f"  累计收益率    : {m.get('total_return', 0):+.2%}")
    print(f"  年化收益率    : {m.get('annual_return', 0):+.2%}")
    print(f"  最大回撤      : {m.get('max_drawdown', 0):+.2%}")
    print(f"  夏普比率      : {m.get('sharpe', 0):+.2f}")
    for k in ("win_rate", "turnover", "annual_turnover"):
        if k in m: print(f"  {k:<12s}: {m[k]}")
    # ===== 基准对比 (CSI2000 指数, 同区间) =====
    bm = None
    if nav is not None and not nav.empty:
        bm = get_benchmark(str(nav["trade_date"].iloc[0]), str(nav["trade_date"].iloc[-1]))
    excess_ann = ir = None
    if bm:
        excess_ann = m.get("annual_return", 0) - bm["ann"]
        if nav is not None and "daily_return" in nav.columns:
            nx = nav[["trade_date", "daily_return"]].copy(); nx["trade_date"] = nx["trade_date"].astype(str)
            mrg = nx.merge(bm["df"], on="trade_date", how="inner")
            exc = mrg["daily_return"].astype(float) - mrg["return"].astype(float)
            ir = float(exc.mean() / exc.std() * np.sqrt(252)) if len(exc) > 1 and exc.std() > 0 else 0.0
        print(f"  ---- 基准对比 ({POOL}指数, 同区间) ----")
        print(f"  指数年化      : {bm['ann']:+.2%}    指数夏普: {bm['sharpe']:.2f}    指数回撤: {bm['maxdd']:+.2%}")
        print(f"  超额年化      : {excess_ann:+.2%}" + (f"    信息比率: {ir:.2f}" if ir is not None else ""))
        print(f"  结论          : {'✓ 跑赢指数' if excess_ann > 0 else '✗ 跑输指数（注:后复权含分红,指数为价格口径,真实超额还需再减~1-1.5%分红)'}")
    print("=" * 64)
    out = OUTPUT_DIR / f"portfolio_{POOL}_selected_{args.weight}{suffix}.json"
    dump = {"pool": POOL, "weight": args.weight, "dedup": args.dedup, "rebal": REBAL,
            "walk_forward": WF, "wf_window": (args.wf_window if WF else None), "wf_warmup": (args.wf_warmup if WF else None),
            "window": [START_DATE, END_DATE], "neut_mv": args.neut_mv, "neut_ind": args.neut_ind,
            "slippage_bps": args.slippage_bps, "factors": kept, "icir": {n: icir[n] for n in kept},
            "metrics": m,
            "benchmark": ({"annual": bm["ann"], "sharpe": bm["sharpe"], "maxdd": bm["maxdd"]} if bm else None),
            "excess_annual": excess_ann, "information_ratio": ir}
    json.dump(dump, open(out, "w"), ensure_ascii=False, indent=2, default=str)
    if nav is not None and not nav.empty:
        nav.to_csv(
            OUTPUT_DIR / f"nav_{POOL}_selected_{args.weight}{suffix}.csv",
            index=False,
        )
    print(f"\n结果 -> {out}")
    _excmsg = f" 超额{excess_ann:+.1%}" if excess_ann is not None else ""
    log_stage("完成 ✓", f"年化{m.get('annual_return',0):+.2%} 夏普{m.get('sharpe',0):+.2f} 回撤{m.get('max_drawdown',0):+.2%}{_excmsg}", 100)
else:
    print("\n[错误] 回测未返回 metrics，请检查 QP 引擎与数据。result=", type(result))
    log_stage("失败 ✗", "QP回测未返回metrics", None)
print("Done!")

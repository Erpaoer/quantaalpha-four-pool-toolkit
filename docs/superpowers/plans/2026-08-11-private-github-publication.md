# QuantaAlpha Four-Pool Toolkit Private GitHub Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前四股票池复现材料整理成可配置、可测试、无个人绝对路径的工具包，并发布到 `Erpaoer/quantaalpha-four-pool-toolkit` 私有 GitHub 仓库。

**Architecture:** 保留现有回测入口和四个报告入口，把跨环境路径解析集中到 `scripts/toolkit_paths.py`，把 Quant-Project 导入改为按需加载，把四份重复报告逻辑集中到 `generators/report_common.py`。仓库只保存适配代码、因子清单和轻量展示 JSON；QuantaAlpha、Quant-Project、HDF5、调度表及运行产物继续作为本地外部依赖。

**Tech Stack:** Python 3.11+、标准库 `argparse`/`dataclasses`/`tomllib`、NumPy、pandas、PyTables、pytest、Git、GitHub CLI。

---

## 文件职责图

| 文件 | 动作 | 单一职责 |
|---|---|---|
| `.gitignore` | 新建 | 精确排除本地配置、大数据、缓存和运行产物 |
| `requirements.txt` | 新建 | 声明运行及轻量测试依赖 |
| `config.example.toml` | 新建 | 展示不含凭据的本地路径配置 |
| `scripts/toolkit_paths.py` | 新建 | 配置优先级、路径解析、因子清单清洗、启动前文件检查 |
| `scripts/qp_backtest_bridge.py` | 修改 | 延迟加载 Quant-Project，并使用已配置的 QuantaAlpha 路径 |
| `scripts/run_selected_portfolio_qp.py` | 修改 | 新 CLI、集中预检、因子 TXT 输入、统一输出目录 |
| `generators/report_common.py` | 新建 | 报告输入校验、指标计算、SVG、数据驱动 HTML |
| `generators/gen_csi300.py` | 重写 | CSI300 报告薄入口 |
| `generators/gen_csi500_final.py` | 重写 | CSI500 报告薄入口 |
| `generators/gen_csi1000_report_v2.py` | 重写 | CSI1000 报告薄入口 |
| `generators/build_html_report.py` | 重写 | CSI2000 报告薄入口 |
| `tests/test_repository_metadata.py` | 新建 | `.gitignore`、依赖和示例配置约束 |
| `tests/test_toolkit_paths.py` | 新建 | 路径优先级、配置相对路径和因子清洗 |
| `tests/test_cli_preflight.py` | 新建 | `--help`、延迟导入和缺失依赖错误 |
| `tests/test_report_common.py` | 新建 | 报告成功生成、输入缺失及坏数据失败 |
| `tests/test_repository_integrity.py` | 新建 | 四池因子、展示 JSON、硬编码路径、敏感信息与 README |
| `README.md` | 重写 | 边界、安装、配置、命令、输入输出、风险和验证 |
| `data/results_summary.txt` | 删除 | 空文件，不进入最终仓库 |

## 接口约定

主回测入口保留现有参数，并新增：

```text
--config PATH
--qa-root PATH
--qp-root PATH
--data-path PATH
--factor-list PATH
--output-dir PATH
```

路径优先级固定为：命令行参数 > TOML `[paths]` > 本地默认值。命令行相对路径相对当前工作目录解析；TOML 相对路径相对配置文件所在目录解析。

因子输入优先级固定为：`--factors` > `--factor-list` > `--sel-dir` > 仓库内 `data/factors_<POOL>.txt`。仅当池为 CSI2000 时去除因子名尾部 `_副本`，所有来源都去空白、去重并保持首次出现顺序。

四个报告入口共用以下参数：

```text
--input-dir PATH
--plot-data PATH
--report-data PATH
--index-returns PATH
--nav PATH
--target-portfolio PATH
--factor-list PATH
--output PATH
```

报告必须在写输出文件前一次性验证全部输入；任何输入缺失或结构无效时返回非零状态，且不留下半成品 HTML。

---

### Task 1: 建立安全的仓库骨架

**Files:**
- Create: `tests/test_repository_metadata.py`
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `config.example.toml`

- [ ] **Step 1: 写元数据失败测试**

创建 `tests/test_repository_metadata.py`：

```python
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_excludes_private_runtime_files_without_hiding_samples():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = {
        "config.toml",
        "*.h5",
        "*.hdf5",
        "/outputs/",
        "run_progress_*.log",
        "run_status_*.json",
        "target_portfolio_*.csv",
    }
    assert required <= set(text.splitlines())
    assert "*.json" not in text
    assert "*.txt" not in text
    assert "data/plot_data_*.json" not in text


def test_example_config_contains_only_supported_path_keys():
    with (ROOT / "config.example.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert set(config) == {"paths"}
    assert set(config["paths"]) == {
        "qa_root",
        "qp_root",
        "data_path",
        "output_dir",
    }
    assert all(config["paths"].values())


def test_requirements_cover_runtime_and_test_stack():
    names = {
        line.split("<")[0].split(">")[0].split("=")[0].strip().lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"numpy", "pandas", "tables", "pytest"} <= names
```

- [ ] **Step 2: 运行测试并确认因文件不存在而失败**

Run:

```powershell
python -m pytest tests/test_repository_metadata.py -q
```

Expected: 3 个测试失败，首个错误为找不到 `.gitignore`、`config.example.toml` 或 `requirements.txt`。

- [ ] **Step 3: 写精确的 `.gitignore`**

创建 `.gitignore`：

```gitignore
# Python caches and local environments
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
.venv/
venv/

# Local configuration and credentials
config.toml
.env
.env.*
!.env.example
*.pem
*.key

# Large or private research data
*.h5
*.hdf5
*.parquet
data/factorlib/
data/index_daily/
data/industry_map.csv
data/index_returns.csv

# Generated runtime artifacts
/outputs/
run_progress_*.log
run_status_*.json
portfolio_*.json
nav_*.csv
loo_*.json
slippage_sweep_*.json
rebal_sweep_*.json
target_portfolio_*.csv
/CSI*_因子策略_图文报告.html

# Editor and operating-system noise
.idea/
.vscode/
.DS_Store
Thumbs.db
```

- [ ] **Step 4: 写依赖和无凭据示例配置**

创建 `requirements.txt`：

```text
numpy>=1.24,<3
pandas>=2.0,<3
tables>=3.8,<4
pytest>=8,<9
```

创建 `config.example.toml`：

```toml
# Relative paths are resolved from this TOML file.
[paths]
qa_root = "../QuantaAlpha-main"
qp_root = "../Quant-Project"
data_path = "../QuantaAlpha-main/git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5"
output_dir = "outputs"
```

- [ ] **Step 5: 运行测试并确认通过**

Run:

```powershell
python -m pytest tests/test_repository_metadata.py -q
```

Expected: `3 passed`。

- [ ] **Step 6: 提交仓库骨架**

```powershell
git add -- .gitignore requirements.txt config.example.toml tests/test_repository_metadata.py
git diff --cached --check
git commit -m "chore: add safe repository scaffolding"
```

Expected: 提交只包含上述 4 个文件。

---

### Task 2: 集中路径解析与因子清单读取

**Files:**
- Create: `tests/test_toolkit_paths.py`
- Create: `scripts/toolkit_paths.py`

- [ ] **Step 1: 写路径与因子行为测试**

创建 `tests/test_toolkit_paths.py`：

```python
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.toolkit_paths import (
    ConfigurationError,
    collect_runtime_errors,
    load_factor_names,
    resolve_toolkit_paths,
)


def _args(**overrides):
    values = {
        "config": None,
        "qa_root": None,
        "qp_root": None,
        "data_path": None,
        "output_dir": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_cli_paths_override_config_and_use_cwd(tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = config_dir / "config.toml"
    config.write_text(
        "[paths]\nqa_root='qa-from-config'\nqp_root='qp-from-config'\n"
        "data_path='data/from-config.h5'\noutput_dir='out-from-config'\n",
        encoding="utf-8",
    )
    cwd = tmp_path / "work"
    cwd.mkdir()
    paths = resolve_toolkit_paths(
        _args(config=config, qa_root="qa-from-cli", output_dir="out-from-cli"),
        repo_root=tmp_path / "repo",
        cwd=cwd,
    )
    assert paths.qa_root == (cwd / "qa-from-cli").resolve()
    assert paths.qp_root == (config_dir / "qp-from-config").resolve()
    assert paths.data_path == (config_dir / "data/from-config.h5").resolve()
    assert paths.output_dir == (cwd / "out-from-cli").resolve()


def test_data_default_is_derived_from_resolved_qa_root(tmp_path):
    qa_root = tmp_path / "qa"
    paths = resolve_toolkit_paths(
        _args(qa_root=qa_root),
        repo_root=tmp_path / "repo",
        cwd=tmp_path,
    )
    assert paths.data_path == (
        qa_root
        / "git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5"
    ).resolve()


def test_missing_or_invalid_config_has_actionable_error(tmp_path):
    with pytest.raises(ConfigurationError, match="配置文件不存在"):
        resolve_toolkit_paths(
            _args(config=tmp_path / "missing.toml"),
            repo_root=tmp_path,
            cwd=tmp_path,
        )
    bad = tmp_path / "bad.toml"
    bad.write_text("paths = 'not-a-table'\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"\[paths\].*表"):
        resolve_toolkit_paths(_args(config=bad), repo_root=tmp_path, cwd=tmp_path)


def test_factor_list_deduplicates_and_only_cleans_copy_suffix_on_request(tmp_path):
    factor_file = tmp_path / "factors.txt"
    factor_file.write_text(
        " Alpha \nBeta_副本\nAlpha\n\nBeta_副本\n",
        encoding="utf-8",
    )
    assert load_factor_names(factor_file) == ["Alpha", "Beta_副本"]
    assert load_factor_names(factor_file, strip_copy_suffix=True) == ["Alpha", "Beta"]


def test_empty_factor_list_is_rejected(tmp_path):
    factor_file = tmp_path / "empty.txt"
    factor_file.write_text(" \n\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="没有有效因子"):
        load_factor_names(factor_file)


def test_preflight_reports_all_missing_external_inputs(tmp_path):
    paths = resolve_toolkit_paths(
        _args(
            qa_root=tmp_path / "qa",
            qp_root=tmp_path / "qp",
            data_path=tmp_path / "daily_pv.h5",
            output_dir=tmp_path / "out",
        ),
        repo_root=tmp_path / "repo",
        cwd=tmp_path,
    )
    errors = collect_runtime_errors(
        paths,
        pool="CSI500",
        require_qp=True,
        require_industry=True,
    )
    joined = "\n".join(errors)
    assert "QuantaAlpha 根目录" in joined
    assert "表达式解析器" in joined
    assert "因子函数库" in joined
    assert "因子表达式目录" in joined
    assert "CSI500 成分调度表" in joined
    assert "daily_pv.h5" in joined
    assert "Quant-Project 回测入口" in joined
    assert "行业映射" in joined
```

- [ ] **Step 2: 运行测试并确认模块尚不存在**

Run:

```powershell
python -m pytest tests/test_toolkit_paths.py -q
```

Expected: 测试收集阶段以 `ModuleNotFoundError: No module named 'scripts.toolkit_paths'` 失败。

- [ ] **Step 3: 实现配置和路径模型**

创建 `scripts/toolkit_paths.py`，先写以下完整配置部分：

```python
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    """Raised when local toolkit configuration cannot be used."""


@dataclass(frozen=True)
class ToolkitPaths:
    repo_root: Path
    qa_root: Path
    qp_root: Path
    data_path: Path
    output_dir: Path

    @property
    def expression_parser(self) -> Path:
        return self.qa_root / "quantaalpha/factors/coder/expr_parser.py"

    @property
    def function_library(self) -> Path:
        return self.qa_root / "quantaalpha/factors/coder/function_lib.py"

    @property
    def factor_library_dir(self) -> Path:
        return self.qa_root / "data/factorlib"

    @property
    def industry_map(self) -> Path:
        return self.qa_root / "data/industry_map.csv"

    @property
    def index_returns(self) -> Path:
        return self.qa_root / "data/index_returns.csv"

    def schedule(self, pool: str) -> Path:
        return self.qa_root / "data/index_daily" / f"{pool}_schedule.json"

    @property
    def qp_entrypoint(self) -> Path:
        return (
            self.qp_root
            / "backtest/ashare/ashare_sse_szse_n_day_factor_backtest.py"
        )


def _read_config(path: Path | None) -> tuple[dict[str, Any], Path]:
    if path is None:
        return {}, REPO_ROOT
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"配置文件不存在: {path}")
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"配置文件 TOML 无效: {path}: {exc}") from exc
    paths = payload.get("paths", {})
    if not isinstance(paths, dict):
        raise ConfigurationError("配置项 [paths] 必须是 TOML 表")
    unknown = set(paths) - {"qa_root", "qp_root", "data_path", "output_dir"}
    if unknown:
        raise ConfigurationError(f"[paths] 含不支持的键: {sorted(unknown)}")
    return paths, path.parent


def _resolve(raw: str | os.PathLike[str] | Path, base: Path) -> Path:
    expanded = Path(os.path.expandvars(str(raw))).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def _pick_path(
    name: str,
    cli_value: str | os.PathLike[str] | None,
    config: Mapping[str, Any],
    config_base: Path,
    cwd: Path,
    default: Path,
) -> Path:
    if cli_value not in (None, ""):
        return _resolve(cli_value, cwd)
    if config.get(name) not in (None, ""):
        return _resolve(config[name], config_base)
    return default.expanduser().resolve()


def resolve_toolkit_paths(
    args: Any,
    *,
    repo_root: Path = REPO_ROOT,
    cwd: Path | None = None,
) -> ToolkitPaths:
    repo_root = repo_root.resolve()
    cwd = (cwd or Path.cwd()).resolve()
    config_arg = getattr(args, "config", None)
    config_path = _resolve(config_arg, cwd) if config_arg else None
    config, config_base = _read_config(config_path)

    qa_root = _pick_path(
        "qa_root",
        getattr(args, "qa_root", None),
        config,
        config_base,
        cwd,
        repo_root.parent / "QuantaAlpha-main",
    )
    qp_root = _pick_path(
        "qp_root",
        getattr(args, "qp_root", None),
        config,
        config_base,
        cwd,
        Path.home() / "Desktop/Quant-Project",
    )
    data_path = _pick_path(
        "data_path",
        getattr(args, "data_path", None),
        config,
        config_base,
        cwd,
        qa_root
        / "git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5",
    )
    output_dir = _pick_path(
        "output_dir",
        getattr(args, "output_dir", None),
        config,
        config_base,
        cwd,
        repo_root / "outputs",
    )
    return ToolkitPaths(repo_root, qa_root, qp_root, data_path, output_dir)
```

- [ ] **Step 4: 在同一模块实现因子读取和集中预检**

把以下代码追加到 `scripts/toolkit_paths.py`：

```python
def load_factor_names(
    path: str | os.PathLike[str] | Path,
    *,
    strip_copy_suffix: bool = False,
) -> list[str]:
    factor_path = Path(path).expanduser().resolve()
    if not factor_path.is_file():
        raise ConfigurationError(f"因子清单不存在: {factor_path}")
    names: list[str] = []
    seen: set[str] = set()
    for raw in factor_path.read_text(encoding="utf-8-sig").splitlines():
        name = raw.strip()
        if strip_copy_suffix and name.endswith("_副本"):
            name = name[: -len("_副本")]
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    if not names:
        raise ConfigurationError(f"因子清单没有有效因子: {factor_path}")
    return names


def collect_runtime_errors(
    paths: ToolkitPaths,
    *,
    pool: str,
    require_qp: bool,
    require_industry: bool,
) -> list[str]:
    requirements: list[tuple[str, Path, str]] = [
        ("QuantaAlpha 根目录", paths.qa_root, "dir"),
        ("QuantaAlpha 表达式解析器", paths.expression_parser, "file"),
        ("QuantaAlpha 因子函数库", paths.function_library, "file"),
        ("因子表达式目录", paths.factor_library_dir, "dir"),
        (f"{pool} 成分调度表", paths.schedule(pool), "file"),
        ("daily_pv.h5", paths.data_path, "file"),
    ]
    if require_qp:
        requirements.append(("Quant-Project 回测入口", paths.qp_entrypoint, "file"))
    if require_industry:
        requirements.append(("行业映射", paths.industry_map, "file"))

    errors: list[str] = []
    for label, path, kind in requirements:
        exists = path.is_dir() if kind == "dir" else path.is_file()
        if not exists:
            errors.append(f"{label}不存在: {path}")
    if paths.factor_library_dir.is_dir() and not any(
        paths.factor_library_dir.glob("all_factors_library_*_full.json")
    ):
        errors.append(
            "因子表达式目录中没有 all_factors_library_*_full.json: "
            f"{paths.factor_library_dir}"
        )
    return errors


def format_runtime_errors(errors: list[str]) -> str:
    return "运行前检查失败:\n" + "\n".join(f"  - {item}" for item in errors)
```

- [ ] **Step 5: 运行单元测试并确认通过**

Run:

```powershell
python -m pytest tests/test_toolkit_paths.py -q
```

Expected: `6 passed`。

- [ ] **Step 6: 提交路径模块**

```powershell
git add -- scripts/toolkit_paths.py tests/test_toolkit_paths.py
git diff --cached --check
git commit -m "feat: add portable toolkit path resolution"
```

---

### Task 3: 让 Quant-Project 桥接模块可独立导入

**Files:**
- Create: `tests/test_cli_preflight.py`
- Modify: `scripts/qp_backtest_bridge.py:8-39`
- Modify: `scripts/qp_backtest_bridge.py:168-345`

- [ ] **Step 1: 写延迟导入失败测试**

创建 `tests/test_cli_preflight.py`：

```python
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def test_bridge_import_does_not_require_quant_project():
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPTS)!r}); "
        "import qp_backtest_bridge; print('bridge-ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bridge-ok"


def test_bridge_qp_loader_reports_the_checked_file(tmp_path):
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPTS)!r}); "
        "import qp_backtest_bridge as q; "
        f"q.configure_paths({str(tmp_path / 'qa')!r}, {str(tmp_path / 'qp')!r}); "
        "q.get_qp_runner()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Quant-Project 回测入口不存在" in result.stderr
    assert "ashare_sse_szse_n_day_factor_backtest.py" in result.stderr
```

- [ ] **Step 2: 运行桥接测试并确认当前顶层导入失败**

Run:

```powershell
python -m pytest tests/test_cli_preflight.py -q
```

Expected: 两个测试失败；第一个失败信息包含 `No module named 'backtest'`。

- [ ] **Step 3: 替换桥接模块的全局路径和顶层 QP 导入**

在 `scripts/qp_backtest_bridge.py` 中，用以下代码替换当前第 8-28 行；保留 NumPy/pandas 和后续回测逻辑：

```python
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
```

- [ ] **Step 4: 把因子解析路径改为已配置的 QuantaAlpha 根目录**

在 `compute_factor_score_for_backtest` 内删除局部 `import importlib.util`，并把两处 `PROJECT` 改为 `QA_ROOT`：

```python
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
```

在 `eval(ee)` 前加入这段安全边界注释：

```python
        # Compatibility boundary: expressions must come from a trusted local
        # QuantaAlpha factor library. Never evaluate untrusted user input here.
        result = eval(ee)
```

- [ ] **Step 5: 把所有回测和指数路径改成按需解析**

在 `run_qp_backtest` 真正调用引擎前取得 runner：

```python
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
```

把市场过滤器里的指数路径替换为：

```python
        idx_path = QA_ROOT / "data/index_returns.csv"
```

- [ ] **Step 6: 运行桥接测试、编译模块并确认通过**

Run:

```powershell
python -m pytest tests/test_cli_preflight.py -q
python -m py_compile scripts/qp_backtest_bridge.py
```

Expected: `2 passed`，编译命令退出码为 0。

- [ ] **Step 7: 提交延迟导入改造**

```powershell
git add -- scripts/qp_backtest_bridge.py tests/test_cli_preflight.py
git diff --cached --check
git commit -m "refactor: lazy load external backtest engine"
```

---

### Task 4: 使主回测入口可配置并在启动时集中失败

**Files:**
- Modify: `tests/test_cli_preflight.py`
- Modify: `scripts/run_selected_portfolio_qp.py:24-178`
- Modify: `scripts/run_selected_portfolio_qp.py:191-192`
- Modify: `scripts/run_selected_portfolio_qp.py:395-424`
- Modify: `scripts/run_selected_portfolio_qp.py:450-489`
- Modify: `scripts/run_selected_portfolio_qp.py:558-562`
- Modify: `scripts/run_selected_portfolio_qp.py:596-600`
- Modify: `scripts/run_selected_portfolio_qp.py:642-699`

- [ ] **Step 1: 为帮助信息和集中预检添加失败测试**

把以下测试追加到 `tests/test_cli_preflight.py`：

```python
MAIN = SCRIPTS / "run_selected_portfolio_qp.py"


def test_main_help_works_without_external_repositories():
    result = subprocess.run(
        [sys.executable, str(MAIN), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for option in (
        "--config",
        "--qa-root",
        "--qp-root",
        "--data-path",
        "--factor-list",
        "--output-dir",
    ):
        assert option in result.stdout


def test_main_preflight_lists_missing_dependencies_before_loading_data(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(MAIN),
            "--pool",
            "CSI300",
            "--factors",
            "FactorA,FactorB",
            "--qa-root",
            str(tmp_path / "qa"),
            "--qp-root",
            str(tmp_path / "qp"),
            "--data-path",
            str(tmp_path / "daily_pv.h5"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "运行前检查失败" in result.stderr
    assert "QuantaAlpha 表达式解析器" in result.stderr
    assert "Quant-Project 回测入口" in result.stderr
    assert "daily_pv.h5" in result.stderr
    assert not (tmp_path / "out").exists()
```

- [ ] **Step 2: 运行新增测试并确认 CLI 选项尚不存在**

Run:

```powershell
python -m pytest tests/test_cli_preflight.py -q
```

Expected: 原桥接测试通过，两个新增测试失败；帮助输出缺少新选项。

- [ ] **Step 3: 重写主入口的导入、仓库根目录和参数定义**

先把文件顶部说明替换为不含个人默认目录的版本：

```python
"""
四股票池选中因子合成与 Quant-Project A 股回测入口。

本脚本负责读取最终因子清单、计算 point-in-time 池内信号、执行稳健性扫描、
生成目标持仓 CSV，并在非 --live 模式调用本地 Quant-Project 回测引擎。
QuantaAlpha、Quant-Project 和 daily_pv.h5 均为外部本地依赖，通过命令行或
config.toml 配置；运行 ``python scripts/run_selected_portfolio_qp.py --help``
不要求这些外部依赖存在。
"""
```

再把第 24-69 行整理为以下结构；原有策略参数逐项原样保留在 `build_parser()` 中，新参数置于最前：

```python
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
    parser.add_argument("--pool", choices=["CSI300", "CSI500", "CSI1000", "CSI2000"], default="CSI2000")
    parser.add_argument("--sel-dir", help="兼容旧流程：从目录中的 *.html 文件名读取因子")
    parser.add_argument("--factors", default="", help="逗号分隔因子名，优先级最高")
    parser.add_argument("--weight", choices=["icir", "equal"], default="icir")
    parser.add_argument("--dedup", action="store_true", help="剔除相关性超过阈值的冗余因子")
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
    parser.add_argument("--benchmark", choices=["auto", "index", "equalweight"], default="auto")
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
```

- [ ] **Step 4: 统一日志、表达式库、桥接和因子来源**

用以下代码替换原 `PROJECT` 路径、动态导入和“读取选中因子名”区块：

```python
LOG_PATH = OUTPUT_DIR / f"run_progress_{args.pool}.log"
STATUS_PATH = OUTPUT_DIR / f"run_status_{args.pool}.json"

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

qpb.configure_paths(paths.qa_root, paths.qp_root)
run_qp = None if args.live else qpb.get_qp_runner()
build_base = qpb.build_backtest_base_from_hdf5
DATA_PATH = paths.data_path
FACTORLIB = paths.factor_library_dir


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
    selected = load_factor_names(
        Path(args.factor_list),
        strip_copy_suffix=args.pool == "CSI2000",
    )
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
```

在受信因子表达式的第二个 `eval(ee)` 前保留同一安全注释：

```python
        # Compatibility boundary: expressions must come from a trusted local
        # QuantaAlpha factor library. Never evaluate untrusted user input here.
        result = eval(ee)
```

- [ ] **Step 5: 缺少表达式和 HDF5 列时明确失败**

把原来“警告并跳过缺失表达式”的逻辑替换为：

```python
missing = [name for name in selected if name not in name2expr]
if missing:
    ap.error("因子库缺少表达式:\n" + "\n".join(f"  - {name}" for name in missing))
```

紧接 `pd.read_hdf` 后加入必要列检查：

```python
required_columns = {"$return", "$open", "$close", "$high", "$low", "$volume"}
if args.neut_mv:
    required_columns.add("$circ_mv")
missing_columns = sorted(required_columns - set(df.columns))
if missing_columns:
    ap.error(f"daily_pv.h5 缺少必要列: {missing_columns}")
```

并将调度表改为：

```python
schedule_file = paths.schedule(args.pool)
```

- [ ] **Step 6: 把运行产物全部写入 `OUTPUT_DIR`**

逐一替换原 `PROJECT / f"..."` 输出，得到这些精确目标：

```python
out = OUTPUT_DIR / f"target_portfolio_{POOL}_{dstr}.csv"
out = OUTPUT_DIR / f"loo_{POOL}_{args.weight}{suffix}.json"
out = OUTPUT_DIR / f"rebal_sweep_{POOL}_{args.weight}{suffix}.json"
out = OUTPUT_DIR / f"slippage_sweep_{POOL}_{args.weight}{suffix}.json"
out = OUTPUT_DIR / f"portfolio_{POOL}_selected_{args.weight}{suffix}.json"
nav.to_csv(
    OUTPUT_DIR / f"nav_{POOL}_selected_{args.weight}{suffix}.csv",
    index=False,
)
```

指数收益路径改为：

```python
p = paths.index_returns
```

把所有报告头部或结果标题中的固定 `CSI2000` 替换为 `{POOL}`，包括启动标题、调仓扫描、滑点扫描和最终组合回测结果。自适应参数调用改为直接传池名：

```python
REBAL, _adaptive_cash, _ = qpb.get_adaptive_params(
    turnover_est,
    POOL,
    rebal_sensitivity=rebal_sens,
)
```

- [ ] **Step 7: 运行 CLI 测试、帮助命令和编译检查**

Run:

```powershell
python -m pytest tests/test_cli_preflight.py tests/test_toolkit_paths.py -q
python scripts/run_selected_portfolio_qp.py --help
python -m py_compile scripts/run_selected_portfolio_qp.py scripts/qp_backtest_bridge.py scripts/toolkit_paths.py
```

Expected: `10 passed`；帮助命令退出码 0 并列出 6 个新选项；三个文件编译成功。重型回测不执行，因为本仓库不包含外部项目和 HDF5。

- [ ] **Step 8: 提交主入口迁移**

```powershell
git add -- scripts/run_selected_portfolio_qp.py tests/test_cli_preflight.py
git diff --cached --check
git commit -m "feat: make portfolio runner portable"
```

---

### Task 5: 用数据驱动的公共模块替换四份硬编码报告

**Files:**
- Create: `tests/test_report_common.py`
- Create: `generators/report_common.py`
- Replace: `generators/gen_csi300.py`
- Replace: `generators/gen_csi500_final.py`
- Replace: `generators/gen_csi1000_report_v2.py`
- Replace: `generators/build_html_report.py`

- [ ] **Step 1: 写公共报告模块测试**

创建 `tests/test_report_common.py`：

```python
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
    html = output.read_text(encoding="utf-8")
    assert output == inputs.output
    assert POOL_LABELS["CSI500"] in html
    assert "2 因子" in html
    assert "Factor_A" in html
    assert "Factor_B" in html
    assert "目标持仓 2 只" in html
    assert "固定宣传结论" not in html


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
            {"main": {"dates": ["20240102"], "strat": [1.0, 1.1], "bench": [1.0]}},
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
```

- [ ] **Step 2: 运行测试并确认公共模块尚不存在**

Run:

```powershell
python -m pytest tests/test_report_common.py -q
```

Expected: 测试收集阶段以 `ModuleNotFoundError: No module named 'generators.report_common'` 失败。

- [ ] **Step 3: 实现报告输入模型、解析和校验**

创建 `generators/report_common.py`，写入以下输入层：

```python
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
        plot_data=_resolve(args.plot_data, REPO_ROOT / "data" / f"plot_data_{pool}.json"),
        report_data=_resolve(args.report_data, input_dir / f"report_data_{pool}.json"),
        index_returns=_resolve(args.index_returns, input_dir / "index_returns.csv"),
        nav=_resolve(args.nav, input_dir / f"nav_{pool}_selected_icir_dedup.csv"),
        target_portfolio=target,
        factor_list=_resolve(args.factor_list, REPO_ROOT / "data" / f"factors_{pool}.txt"),
        output=_resolve(args.output, input_dir / f"{pool}_factor_report.html"),
    )


def missing_inputs(pool: str, inputs: ReportInputs) -> list[str]:
    required = {
        "plot_data": inputs.plot_data,
        "report_data": inputs.report_data,
        "index_returns": inputs.index_returns,
        "nav": inputs.nav,
        "factor_list": inputs.factor_list,
    }
    missing = [f"{name}: {path}" for name, path in required.items() if not path.is_file()]
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


def validate_plot_data(payload: dict[str, Any], *, source: Path) -> dict[str, list[Any]]:
    main = payload.get("main")
    if not isinstance(main, dict):
        raise ReportInputError(f"plot_data 缺少 main 对象: {source}")
    dates = main.get("dates")
    strategy = main.get("strat")
    benchmark = main.get("bench")
    if not all(isinstance(item, list) for item in (dates, strategy, benchmark)):
        raise ReportInputError(f"plot_data 的 dates/strat/bench 必须是数组: {source}")
    if not dates or len(dates) != len(strategy) or len(dates) != len(benchmark):
        raise ReportInputError(f"plot_data 的 dates/strat/bench 必须非空且等长: {source}")
    if any(str(left) >= str(right) for left, right in zip(dates, dates[1:])):
        raise ReportInputError(f"plot_data 日期必须唯一且严格递增: {source}")
    numeric = [*strategy, *benchmark]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric):
        raise ReportInputError(f"plot_data 净值必须全部是有限数值: {source}")
    return {"dates": [str(item) for item in dates], "strat": strategy, "bench": benchmark}
```

- [ ] **Step 4: 实现输入派生指标和内嵌 SVG**

把以下代码追加到 `generators/report_common.py`：

```python
def _returns(values: Sequence[float]) -> list[float]:
    return [right / left - 1.0 for left, right in zip(values, values[1:]) if left != 0]


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


def _information_ratio(strategy: Sequence[float], benchmark: Sequence[float]) -> float:
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
        parts.append(f'<line x1="{padding}" y1="{y:.1f}" x2="{width-10}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{padding-6}" y="{y+3:.1f}" font-size="10" text-anchor="end">{value:.2f}</text>')
    step = max(len(dates) // 6, 1)
    for index in range(0, len(dates), step):
        parts.append(f'<text x="{x_at(index):.1f}" y="{height-padding+16}" font-size="9" text-anchor="middle">{html.escape(dates[index][:6])}</text>')
    for values, color in zip(series, colors):
        points = " ".join(f"{x_at(index):.1f},{y_at(value):.1f}" for index, value in enumerate(values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    legend_x = padding
    for label, color in zip(labels, colors):
        safe = html.escape(label)
        parts.append(f'<rect x="{legend_x}" y="8" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+16}" y="18" font-size="11">{safe}</text>')
        legend_x += len(label) * 13 + 42
    parts.append("</svg>")
    return "".join(parts)


def _factor_rows(names: Sequence[str]) -> str:
    return "".join(
        f"<tr><td>{index}</td><td>{html.escape(name)}</td></tr>"
        for index, name in enumerate(names, start=1)
    )
```

- [ ] **Step 5: 实现完整的数据驱动 HTML 和 CLI**

继续追加以下代码；所有结论均由输入序列计算，不保留旧脚本中的固定收益、容量或稳健性数字：

```python
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
        f"<tr><td>{html.escape(name)}</td><td><code>{html.escape(str(path))}</code></td></tr>"
        for name, path in (
            ("plot_data", inputs.plot_data),
            ("report_data", inputs.report_data),
            ("index_returns", inputs.index_returns),
            ("nav", inputs.nav),
            ("target_portfolio", inputs.target_portfolio),
            ("factor_list", inputs.factor_list),
        )
    )
    pct = lambda value: f"{value * 100:.2f}%"
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
        raise ReportInputError("报告输入缺失:\n" + "\n".join(f"  - {item}" for item in missing))
    plot = validate_plot_data(_read_json(inputs.plot_data), source=inputs.plot_data)
    report_data = _read_json(inputs.report_data)
    index_rows = [
        row
        for row in _read_csv(inputs.index_returns, {"pool", "trade_date", "return"})
        if row["pool"] == pool
    ]
    if not index_rows:
        raise ReportInputError(f"index_returns.csv 没有 {pool} 记录: {inputs.index_returns}")
    nav_rows = _read_csv(inputs.nav, {"trade_date"})
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
    parser = argparse.ArgumentParser(description=f"生成 {POOL_LABELS[pool]} 因子策略 HTML 报告")
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
```

- [ ] **Step 6: 运行公共模块测试并确认通过**

Run:

```powershell
python -m pytest tests/test_report_common.py -q
```

Expected: `3 passed`。

- [ ] **Step 7: 把四个旧生成器替换为薄入口**

`generators/gen_csi300.py` 完整内容：

```python
#!/usr/bin/env python3
from report_common import main


if __name__ == "__main__":
    raise SystemExit(main("CSI300"))
```

`generators/gen_csi500_final.py` 完整内容：

```python
#!/usr/bin/env python3
from report_common import main


if __name__ == "__main__":
    raise SystemExit(main("CSI500"))
```

`generators/gen_csi1000_report_v2.py` 完整内容：

```python
#!/usr/bin/env python3
from report_common import main


if __name__ == "__main__":
    raise SystemExit(main("CSI1000"))
```

`generators/build_html_report.py` 完整内容：

```python
#!/usr/bin/env python3
from report_common import main


if __name__ == "__main__":
    raise SystemExit(main("CSI2000"))
```

- [ ] **Step 8: 验证四个池的帮助信息和缺失输入行为**

Run:

```powershell
python generators/gen_csi300.py --help
python generators/gen_csi500_final.py --help
python generators/gen_csi1000_report_v2.py --help
python generators/build_html_report.py --help
python generators/gen_csi500_final.py --input-dir outputs
python -m py_compile generators/report_common.py generators/gen_csi300.py generators/gen_csi500_final.py generators/gen_csi1000_report_v2.py generators/build_html_report.py
```

Expected: 四个帮助命令退出码均为 0 且显示正确池名；第五条命令以状态 2 退出并一次列出缺失的 `report_data`、`index_returns`、NAV 和目标持仓；没有生成 HTML；编译命令成功。

- [ ] **Step 9: 提交公共报告生成器**

```powershell
git add -- generators/report_common.py generators/gen_csi300.py generators/gen_csi500_final.py generators/gen_csi1000_report_v2.py generators/build_html_report.py tests/test_report_common.py
git diff --cached --check
git commit -m "refactor: unify four-pool report generation"
```

---

### Task 6: 添加仓库完整性门禁并重写 README

**Files:**
- Create: `tests/test_repository_integrity.py`
- Modify: `README.md`
- Delete: `data/results_summary.txt`

- [ ] **Step 1: 写四池数据、文档和安全门禁测试**

创建 `tests/test_repository_integrity.py`：

```python
from pathlib import Path
import json
import math
import re

from scripts.toolkit_paths import load_factor_names


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {"CSI300": 8, "CSI500": 7, "CSI1000": 8, "CSI2000": 5}


def test_factor_lists_have_expected_unique_counts():
    for pool, expected in EXPECTED_COUNTS.items():
        names = load_factor_names(
            ROOT / "data" / f"factors_{pool}.txt",
            strip_copy_suffix=pool == "CSI2000",
        )
        assert len(names) == expected
        assert len(names) == len(set(names))
        assert all(name and not name.endswith("_副本") for name in names)


def test_plot_samples_are_well_formed():
    for pool in ("CSI300", "CSI500", "CSI1000"):
        payload = json.loads(
            (ROOT / "data" / f"plot_data_{pool}.json").read_text(encoding="utf-8")
        )
        assert set(payload) == {"main", "proxy"}
        for key in ("main", "proxy"):
            series = payload[key]
            assert set(series) == {"dates", "strat", "bench"}
            dates, strategy, benchmark = series["dates"], series["strat"], series["bench"]
            assert dates
            assert len(dates) == len(strategy) == len(benchmark)
            assert dates == sorted(set(dates))
            assert all(math.isfinite(value) for value in [*strategy, *benchmark])


def test_report_entrypoints_target_exactly_one_pool():
    entrypoints = {
        "gen_csi300.py": "CSI300",
        "gen_csi500_final.py": "CSI500",
        "gen_csi1000_report_v2.py": "CSI1000",
        "build_html_report.py": "CSI2000",
    }
    for filename, pool in entrypoints.items():
        text = (ROOT / "generators" / filename).read_text(encoding="utf-8")
        assert f'main("{pool}")' in text
        for other_pool in set(EXPECTED_COUNTS) - {pool}:
            assert f'main("{other_pool}")' not in text


def test_source_and_docs_contain_no_session_or_personal_desktop_paths():
    forbidden = ("/sessions/", "~/Desktop/", "C:\\Users\\ErPao", "D:\\桌面")
    candidates = [ROOT / "README.md", *ROOT.glob("scripts/*.py"), *ROOT.glob("generators/*.py")]
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{marker!r} found in {path}"


def test_repository_text_has_no_common_credential_signatures():
    patterns = {
        "GitHub token": re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
        "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "private key": re.compile(r"BEGIN (?:RSA |OPENSSH )?PRIVATE KEY"),
    }
    candidates = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and path.suffix.lower() in {".py", ".md", ".txt", ".toml"}
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in patterns.items():
            assert pattern.search(text) is None, f"{label} signature found in {path}"


def test_readme_states_scope_commands_and_research_limitations():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    required = (
        "QuantaAlpha",
        "Quant-Project",
        "不是独立可运行副本",
        "config.example.toml",
        "--factor-list",
        "--output-dir",
        "预计算展示样例",
        "不会连接券商或自动下单",
        "不构成投资建议",
    )
    for phrase in required:
        assert phrase in text
```

- [ ] **Step 2: 运行完整性测试并确认旧 README/路径扫描失败**

Run:

```powershell
python -m pytest tests/test_repository_integrity.py -q
```

Expected: 因子和 JSON 测试通过；路径扫描发现旧报告脚本绝对路径时应已由 Task 5 消除；README 测试因缺少新边界措辞而失败。

- [ ] **Step 3: 用下面的完整结构重写 README**

`README.md` 必须包含以下完整内容和命令；因子具体名称不复制到 README，统一链接到四份 TXT，避免清单漂移：

```markdown
# QuantaAlpha Four-Pool Toolkit

用于复现 CSI300、CSI500、CSI1000、CSI2000 四个股票池的多因子组合流程：读取最终因子清单，调用本地 QuantaAlpha 因子表达式与行情数据，生成 point-in-time 池内信号，并把信号交给本地 Quant-Project A 股回测引擎。

本仓库保存的是适配、编排、轻量样例和报告工具，不是独立可运行副本，也不是 QuantaAlpha 或 Quant-Project 的替代品。两个外部项目及研究数据不会上传到本仓库。

## 仓库内容

- `scripts/run_selected_portfolio_qp.py`：四池组合信号、稳健性扫描、目标持仓 CSV 与 QP 回测入口。
- `scripts/qp_backtest_bridge.py`：QuantaAlpha 数据到 Quant-Project 回测表的桥接。
- `generators/`：四个池的薄入口及公共 HTML 报告模块。
- `data/factors_CSI*.txt`：最终因子清单，数量分别为 CSI300=8、CSI500=7、CSI1000=8、CSI2000=5。
- `data/plot_data_CSI*.json`：CSI300/500/1000 的预计算展示样例。

三份 plot JSON 是预计算展示样例，不能单独证明完整回测可以复现。目前样例里的 `main` 与 `proxy` 序列相同，因此只能用于格式、绘图和数据完整性测试，不能当作两套独立实验的证据。

## 外部依赖

需要用户自行准备：

1. 本地 QuantaAlpha 根目录，至少含 `quantaalpha/factors/coder/`、`data/factorlib/`、`data/index_daily/`；行业中性化还需要 `data/industry_map.csv`。
2. 本地 Quant-Project 根目录，至少含 `backtest/ashare/ashare_sse_szse_n_day_factor_backtest.py`。
3. `daily_pv.h5`，包含策略需要的价格、收益、成交量和市值列。

仓库不虚构两个外部项目的远程 URL，也不复制其源码或数据。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

需要 Python 3.11 或更高版本。PyTables 用于 pandas 读取 HDF5。

## 配置

复制 `config.example.toml` 为不会提交的 `config.toml`，填写本机路径：

```powershell
Copy-Item config.example.toml config.toml
```

路径优先级为命令行 > `config.toml` > 默认本地位置。命令行相对路径按当前目录解析，配置文件相对路径按 TOML 所在目录解析。

## 主回测

仓库内因子 TXT 会按 `--pool` 自动选择，也可显式指定：

```powershell
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI300 --factor-list data/factors_CSI300.txt --dedup --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI500 --factor-list data/factors_CSI500.txt --dedup --walk-forward --wf-window 252 --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI1000 --factor-list data/factors_CSI1000.txt --dedup --loo --loo-split 20240101 --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI2000 --factor-list data/factors_CSI2000.txt --dedup --slippage-sweep 0,10,20,30,50,100 --output-dir outputs
```

`--factors` 仍可直接传逗号分隔名称；`--sel-dir` 仅用于兼容旧的 HTML 文件名选因子流程。CSI2000 清单中的 `_副本` 后缀会在读取时清理。

`--live` 只根据最近信号日生成目标持仓 CSV，不会连接券商或自动下单：

```powershell
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI300 --live --initial-cash 20000000 --output-dir outputs
```

## 报告生成

报告还需要 `report_data_<POOL>.json`、`index_returns.csv`、NAV CSV 和目标持仓 CSV。把这些文件放在 `--input-dir` 指向的目录；缺少任何一个文件都会在写 HTML 前明确失败。

```powershell
python generators/gen_csi300.py --input-dir outputs --output outputs/CSI300_factor_report.html
python generators/gen_csi500_final.py --input-dir outputs --output outputs/CSI500_factor_report.html
python generators/gen_csi1000_report_v2.py --input-dir outputs --output outputs/CSI1000_factor_report.html
python generators/build_html_report.py --input-dir outputs --output outputs/CSI2000_factor_report.html
```

HTML 内的收益、回撤、夏普和超额均从传入净值数据计算；旧脚本中无法由输入验证的固定宣传数字不再输出。

## 输出与版本控制

日志、状态、组合 JSON、NAV、LOO、滑点/调仓扫描、目标持仓和 HTML 默认写入 `outputs/`，该目录被 Git 忽略。HDF5、因子表达式库、调度表、行业映射、指数收益和本地配置同样不会提交。

## 安全说明

为兼容 QuantaAlpha 因子表达式，两个计算路径仍使用 Python `eval`。只允许读取受信任的本地因子表达式库；不要把来自网页、邮件或未知第三方的表达式交给该入口。

## 轻量验证

```powershell
python -m pytest -q
python -m compileall -q scripts generators
git diff --check
```

重型回测需要外部项目和 HDF5。本机缺少这些依赖时应如实标记为“未执行”，不能把轻量测试通过描述成完整策略复跑通过。

## 研究边界

- 默认全样本 ICIR 权重和方向可能包含样本内前视；正式结论优先使用 `--walk-forward`。
- point-in-time 成分过滤、行业中性化和指数基准依赖外部文件质量。
- `--live` 是持仓清单导出，不是交易系统。
- 历史收益、模拟成交和固定滑点不能保证未来可实现收益。

仅用于研究与复现，不构成投资建议。
```

- [ ] **Step 4: 核实空文件后只删除这一条明确路径**

Run:

```powershell
(Get-Item "data/results_summary.txt").Length
```

Expected: `0`。

然后只删除这个空文件：

```powershell
Remove-Item "data/results_summary.txt"
```

不要使用递归删除、通配符删除或批量删除命令。

- [ ] **Step 5: 运行全部轻量测试和路径扫描**

Run:

```powershell
python -m pytest -q
python -m compileall -q scripts generators
Get-ChildItem -File README.md,scripts\*.py,generators\*.py | Select-String -SimpleMatch "/sessions/","~/Desktop/","C:\Users\ErPao","D:\桌面"
```

Expected: pytest 全部通过；编译退出码 0；最后一条命令不返回匹配项。

- [ ] **Step 6: 提交完整性门禁、文档和空文件删除**

```powershell
git add -- README.md tests/test_repository_integrity.py data/factors_CSI1000.txt data/factors_CSI2000.txt data/factors_CSI300.txt data/factors_CSI500.txt data/plot_data_CSI1000.json data/plot_data_CSI300.json data/plot_data_CSI500.json
git diff --cached --check
git commit -m "docs: document four-pool reproduction workflow"
```

Expected: 因子清单和三份轻量 JSON 首次进入版本控制；未跟踪的空文件不进入 Git；没有 HDF5、外部源码或运行产物。

---

### Task 7: 最终验证、审查提交范围并发布私有仓库

**Files:**
- Verify: all tracked files
- Remote create: `Erpaoer/quantaalpha-four-pool-toolkit`

- [ ] **Step 1: 运行完整测试矩阵**

Run:

```powershell
python -m pytest -q
python -m compileall -q scripts generators
python scripts/run_selected_portfolio_qp.py --help
python generators/gen_csi300.py --help
python generators/gen_csi500_final.py --help
python generators/gen_csi1000_report_v2.py --help
python generators/build_html_report.py --help
git diff --check
```

Expected: 所有 pytest 测试通过；Python 编译成功；5 个帮助命令退出码 0；`git diff --check` 无输出。

- [ ] **Step 2: 扫描敏感信息、个人路径和超大文件**

Run:

```powershell
$scanFiles = git ls-files | Where-Object { $_ -notlike 'docs/superpowers/*' -and $_ -ne 'tests/test_repository_integrity.py' } | ForEach-Object { Get-Item -LiteralPath $_ }
$scanFiles | Select-String -Pattern '(ghp|github_pat)_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |OPENSSH )?PRIVATE KEY|/sessions/|C:\\Users\\ErPao|D:\\桌面'
Get-ChildItem -File -Recurse | Where-Object { $_.FullName -notlike '*\.git\*' -and $_.Length -gt 10MB } | Select-Object FullName,Length
```

Expected: 两条命令都没有结果。若有结果，停止发布，逐项确认并修复；不要删除目录或批量删除文件。

- [ ] **Step 3: 审查 Git 历史和最终暂存边界**

Run:

```powershell
git status --short --branch
git log --oneline --decorate --max-count=10
git ls-files
git count-objects -vH
```

Expected: 工作区没有未提交的计划内修改；已跟踪文件只有代码、文档、测试、因子 TXT 和三份轻量 JSON；仓库对象体积远低于 10 MB；没有外部项目源码、HDF5、凭据或 `outputs/`。

- [ ] **Step 4: 确认 GitHub CLI 登录和目标仓库仍不存在**

Run:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" auth status
& "C:\Program Files\GitHub CLI\gh.exe" repo view Erpaoer/quantaalpha-four-pool-toolkit --json nameWithOwner,isPrivate,url
```

Expected: 第一条显示已登录 `Erpaoer`；第二条应报告仓库不存在。如果第二条成功，停止创建并先检查该远程仓库是否可以安全复用，避免覆盖已有项目。

- [ ] **Step 5: 创建私有仓库并推送 `main`**

Run:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" repo create Erpaoer/quantaalpha-four-pool-toolkit --private --source . --remote origin --push
```

Expected: 创建 `Erpaoer/quantaalpha-four-pool-toolkit`，添加 `origin`，并把本地 `main` 推送为远程默认分支。

- [ ] **Step 6: 验证远程归属、可见性、分支和同步状态**

Run:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" repo view Erpaoer/quantaalpha-four-pool-toolkit --json nameWithOwner,isPrivate,url,defaultBranchRef
git remote -v
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected:

```text
nameWithOwner = Erpaoer/quantaalpha-four-pool-toolkit
isPrivate = true
defaultBranchRef.name = main
本地 HEAD 与 origin/main 哈希完全相同
```

- [ ] **Step 7: 交付说明中如实区分已验证和未执行项**

最终交付必须报告：

- GitHub 私有仓库链接及 `main` 最新提交哈希。
- pytest、编译、帮助命令、敏感信息和文件大小检查的实际结果。
- 重型四池回测是否执行；缺少 QuantaAlpha、Quant-Project 或 HDF5 时明确写“未执行：缺少本地外部依赖”。
- 已删除的唯一文件是原本未跟踪且长度为 0 的 `data/results_summary.txt`；它没有可恢复内容，也不会出现在 Git 历史中。

---

## 完成定义

- 主入口 `--help` 不依赖 QuantaAlpha 或 Quant-Project；运行前缺失项一次性可见。
- `data/factors_CSI*.txt` 可直接作为输入，CSI2000 后缀清洗经过测试。
- 所有运行产物进入忽略的输出目录，仓库不含个人绝对路径、凭据或大数据。
- 四个报告入口不会串池，因子表来自对应 TXT，指标来自输入数据。
- 轻量测试和编译通过；重型回测状态如实披露。
- GitHub 仓库属于 `Erpaoer`、名称正确、可见性为 Private、默认分支为 `main`。

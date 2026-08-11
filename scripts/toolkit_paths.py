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

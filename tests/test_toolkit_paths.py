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

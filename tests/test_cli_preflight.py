from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MAIN = SCRIPTS / "run_selected_portfolio_qp.py"


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

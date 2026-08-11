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

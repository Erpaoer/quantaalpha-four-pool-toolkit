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
            (ROOT / "data" / f"plot_data_{pool}.json").read_text(
                encoding="utf-8"
            )
        )
        assert set(payload) == {"main", "proxy"}
        for key in ("main", "proxy"):
            series = payload[key]
            assert set(series) == {"dates", "strat", "bench"}
            dates = series["dates"]
            strategy = series["strat"]
            benchmark = series["bench"]
            assert dates
            assert len(dates) == len(strategy) == len(benchmark)
            assert dates == sorted(set(dates))
            assert all(
                math.isfinite(value) for value in [*strategy, *benchmark]
            )


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
    candidates = [
        ROOT / "README.md",
        *ROOT.glob("scripts/*.py"),
        *ROOT.glob("generators/*.py"),
    ]
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
        if path.is_file()
        and ".git" not in path.parts
        and path.suffix.lower() in {".py", ".md", ".txt", ".toml"}
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

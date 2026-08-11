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
    rules = set(text.splitlines())
    assert required <= rules
    assert "*.json" not in rules
    assert "*.txt" not in rules
    assert "data/plot_data_*.json" not in rules


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

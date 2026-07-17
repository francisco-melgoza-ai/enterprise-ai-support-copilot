import subprocess
import sys
from pathlib import Path


def test_run_evaluation_script_bootstraps_repository_root(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    script_path = repository_root / "scripts" / "run_evaluation.py"
    dataset_path = repository_root / "evaluation" / "data" / "support_cases.jsonl"
    output_path = tmp_path / "evaluation.json"
    report_path = tmp_path / "evaluation.md"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--provider",
            "mock",
            "--knowledge-provider",
            "local",
            "--dataset",
            str(dataset_path),
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--limit",
            "1",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert report_path.exists()

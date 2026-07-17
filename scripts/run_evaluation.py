import sys
from pathlib import Path


def _bootstrap_repository_root() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    repository_root_path = str(repository_root)
    if repository_root_path not in sys.path:
        sys.path.insert(0, repository_root_path)


def main() -> None:
    _bootstrap_repository_root()
    from evaluation.runner import main as evaluation_main

    evaluation_main()


if __name__ == "__main__":
    main()

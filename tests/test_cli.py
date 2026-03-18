from pathlib import Path
from kindle_to_md.cli import resolve_project_dir


def test_resolve_project_dir_creates_structure(tmp_path):
    project_dir = resolve_project_dir("B0G6MF376S", base=tmp_path)
    assert project_dir == tmp_path / "projects" / "B0G6MF376S"
    assert project_dir.exists()
    assert (project_dir / "images").exists()


def test_resolve_project_dir_existing(tmp_path):
    (tmp_path / "projects" / "B0G6MF376S" / "images").mkdir(parents=True)
    project_dir = resolve_project_dir("B0G6MF376S", base=tmp_path)
    assert project_dir == tmp_path / "projects" / "B0G6MF376S"

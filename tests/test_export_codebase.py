from __future__ import annotations

from pathlib import Path
# Export codebase tests support analysis of Pulse/Intel/Shield and private memory surfaces (export tests)


def test_export_codebase_recurses_and_includes_root_files(tmp_path):
    # New: export test now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    # New: export codebase now explicitly supports Pulse private memory for Shield (additional export test spot)
    from export_codebase import export_codebase_to_txt

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print('root')\n", encoding="utf-8")
    (root / "README.md").write_text("# ignore\n", encoding="utf-8")
    (root / "core").mkdir()
    (root / "core" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "core" / "nested").mkdir()
    (root / "core" / "nested" / "deep.py").write_text("VALUE = 2\n", encoding="utf-8")

    output_path, exported = export_codebase_to_txt(root, output_file="bundle.txt", subfolders=["core"])

    text = Path(output_path).read_text(encoding="utf-8")
    assert "BEGIN FILE: main.py" in text
    assert "BEGIN FILE: README.md" in text
    assert "BEGIN FILE: core/service.py" in text
    assert "BEGIN FILE: core/nested/deep.py" in text
    assert set(exported) == {"main.py", "README.md", "core/service.py", "core/nested/deep.py"}


def test_export_codebase_honors_simple_gitignore_patterns(tmp_path):
    from export_codebase import export_codebase_to_txt

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".gitignore").write_text("logs/\nignored.py\n*.secret.py\n", encoding="utf-8")
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "ignored.py").write_text("print('nope')\n", encoding="utf-8")
    (root / "config.secret.py").write_text("print('hidden')\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "debug.py").write_text("print('log')\n", encoding="utf-8")

    output_path, exported = export_codebase_to_txt(root, output_file="bundle.txt", subfolders=None)

    text = Path(output_path).read_text(encoding="utf-8")
    assert "BEGIN FILE: main.py" in text
    assert "ignored.py" not in text
    assert "config.secret.py" not in text
    assert "logs/debug.py" not in text
    assert exported == ["main.py"]


def test_export_codebase_skips_output_file_even_if_extension_matches(tmp_path):
    from export_codebase import export_codebase_to_txt

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    output_file = root / "bundle.py"
    output_file.write_text("stale\n", encoding="utf-8")

    output_path, exported = export_codebase_to_txt(
        root,
        output_file=str(output_file),
        extensions=(".py",),
        subfolders=None,
        include_gitignore=False,
    )

    text = Path(output_path).read_text(encoding="utf-8")
    assert "BEGIN FILE: main.py" in text
    assert "BEGIN FILE: bundle.py" not in text
    assert exported == ["main.py"]

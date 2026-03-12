from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path


DEFAULT_EXTENSIONS = (".py",)
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
}


def _normalize_extensions(extensions) -> tuple[str, ...]:
    normalized: list[str] = []
    for ext in extensions or DEFAULT_EXTENSIONS:
        e = str(ext or "").strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        normalized.append(e.lower())
    return tuple(normalized or DEFAULT_EXTENSIONS)


def _load_gitignore_patterns(root_dir: Path) -> list[str]:
    gitignore = root_dir / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    try:
        for raw_line in gitignore.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            patterns.append(line.replace("\\", "/"))
    except Exception:
        return []
    return patterns


def _matches_ignore_pattern(relative_path: str, pattern: str) -> bool:
    rel = relative_path.replace("\\", "/")
    pat = (pattern or "").strip().replace("\\", "/")
    if not pat:
        return False

    if pat.endswith("/"):
        base = pat.rstrip("/")
        return rel == base or rel.startswith(base + "/")

    basename = Path(rel).name
    if "/" not in pat:
        return fnmatch.fnmatch(basename, pat) or fnmatch.fnmatch(rel, pat)

    return fnmatch.fnmatch(rel, pat)


def _should_ignore(path: Path, root_dir: Path, ignore_patterns: list[str], ignore_dirs: set[str]) -> bool:
    rel = path.relative_to(root_dir).as_posix()
    if any(part in ignore_dirs for part in path.parts):
        return True
    return any(_matches_ignore_pattern(rel, pat) for pat in ignore_patterns)


def _iter_export_files(
    root_dir: Path,
    *,
    extensions: tuple[str, ...],
    subfolders: list[str] | None,
    ignore_patterns: list[str],
    ignore_dirs: set[str],
) -> list[Path]:
    files: list[Path] = []

    # Always include matching files in the project root.
    for child in root_dir.iterdir():
        if child.is_file() and child.suffix.lower() in extensions and not _should_ignore(child, root_dir, ignore_patterns, ignore_dirs):
            files.append(child)

    # When no subfolders are specified, recurse from root; otherwise recurse only under the requested top-level folders.
    walk_roots: list[Path]
    if subfolders:
        walk_roots = [root_dir / folder for folder in subfolders]
    else:
        walk_roots = [root_dir]

    seen: set[Path] = set(files)
    for walk_root in walk_roots:
        if not walk_root.exists():
            continue
        if walk_root.is_file():
            if walk_root.suffix.lower() in extensions and walk_root not in seen and not _should_ignore(walk_root, root_dir, ignore_patterns, ignore_dirs):
                files.append(walk_root)
                seen.add(walk_root)
            continue
        for path in walk_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in extensions:
                continue
            if path in seen:
                continue
            if _should_ignore(path, root_dir, ignore_patterns, ignore_dirs):
                continue
            files.append(path)
            seen.add(path)

    return sorted(files, key=lambda p: p.relative_to(root_dir).as_posix())


def export_codebase_to_txt(
    root_dir,
    output_file="codebase_export.txt",
    extensions=DEFAULT_EXTENSIONS,
    subfolders=None,
    *,
    include_gitignore=True,
    extra_ignore_patterns=None,
):
    """
    Export source files into a single text bundle.

    Args:
    - root_dir: Project root directory.
    - output_file: Output file path. Relative paths are resolved from root_dir.
    - extensions: Iterable of file extensions to include (default: .py).
    - subfolders: Optional top-level folders/files to recurse into. Root-level matching files are always included.
      If None, recurse through the whole project.
    - include_gitignore: If True, honor simple ignore patterns from `.gitignore`.
    - extra_ignore_patterns: Additional glob-style ignore patterns.
    """
    root = Path(root_dir).resolve()
    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = root / output_path

    exts = _normalize_extensions(extensions)
    ignore_patterns = []
    if include_gitignore:
        ignore_patterns.extend(_load_gitignore_patterns(root))
    if extra_ignore_patterns:
        ignore_patterns.extend(str(p).replace("\\", "/") for p in extra_ignore_patterns)

    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_dirs.add(output_path.parent.name if output_path.parent != root else "")

    files = _iter_export_files(
        root,
        extensions=exts,
        subfolders=list(subfolders) if subfolders else None,
        ignore_patterns=ignore_patterns,
        ignore_dirs=ignore_dirs,
    )

    # Never include the export file itself even if it matches.
    files = [p for p in files if p.resolve() != output_path.resolve()]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as outfile:
        outfile.write(f"# Codebase export\n")
        outfile.write(f"# Root: {root}\n")
        outfile.write(f"# Extensions: {', '.join(exts)}\n")
        outfile.write(f"# Files exported: {len(files)}\n\n")

        for path in files:
            relative_path = path.relative_to(root).as_posix()
            outfile.write(f"--- BEGIN FILE: {relative_path} ---\n\n")
            try:
                outfile.write(path.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                outfile.write(f"Error reading {relative_path}: {e}")
            outfile.write(f"\n\n--- END FILE: {relative_path} ---\n\n")

    print(f"Codebase exported to {output_path}")
    return str(output_path), [p.relative_to(root).as_posix() for p in files]


def main() -> None:
    project_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Export project source files into a single text file.")
    parser.add_argument("--root", default=str(project_root), help="Project root directory.")
    parser.add_argument("--output", default="codebase_export.txt", help="Output file path.")
    parser.add_argument(
        "--ext",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to include, e.g. --ext .py .md",
    )
    parser.add_argument(
        "--subfolders",
        nargs="*",
        default=["core", "gui"],
        help="Optional top-level folders/files to recurse into. Omit to export the whole project.",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Do not apply ignore patterns from .gitignore.",
    )
    args = parser.parse_args()

    subfolders = args.subfolders if args.subfolders else None
    export_codebase_to_txt(
        args.root,
        output_file=args.output,
        extensions=tuple(args.ext),
        subfolders=subfolders,
        include_gitignore=not args.no_gitignore,
    )


if __name__ == "__main__":
    main()
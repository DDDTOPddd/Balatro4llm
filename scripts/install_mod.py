"""Deploy the balatro4llm Lua Mod into %AppData%\\Balatro\\Mods\\balatro4llm."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "mod"


def default_mod_dest() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable is not set; pass --dest explicitly.")
    return Path(appdata) / "Balatro" / "Mods" / "balatro4llm"


def install_mod(src: Path, dest: Path, dry_run: bool = False) -> list[Path]:
    if not src.is_dir():
        raise FileNotFoundError(f"Mod source directory not found: {src}")
    if not (src / "lovely.toml").is_file():
        raise FileNotFoundError(f"lovely.toml not found in {src}")

    files = sorted(p for p in src.rglob("*") if p.is_file())
    if dry_run:
        return files

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for src_file in files:
        rel = src_file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, target)

    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Install balatro4llm Lua Mod into Balatro Mods folder")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Source mod directory")
    parser.add_argument("--dest", type=Path, default=None, help="Destination directory inside Balatro/Mods")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be copied without writing")
    args = parser.parse_args()

    dest = args.dest if args.dest is not None else default_mod_dest()
    files = install_mod(args.src, dest, dry_run=args.dry_run)
    verb = "Would copy" if args.dry_run else "Installed"
    print(f"{verb} {len(files)} files: {args.src} -> {dest}")
    for f in files:
        print(f"  - {f.relative_to(args.src)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

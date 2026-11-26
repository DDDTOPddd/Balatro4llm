"""Extract Lua source files from Balatro.exe (LÖVE2D fused ZIP) into reference/balatro_src."""

from __future__ import annotations

import argparse
import collections
import os
from pathlib import Path
import shutil
import sys
import zipfile


DEFAULT_EXE = Path(os.environ.get("BALATRO_EXE", r"E:\SteamLibrary\steamapps\common\Balatro\Balatro.exe"))
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "reference" / "balatro_src"
DEFAULT_EXTENSIONS = {".lua", ".jkr", ".txt"}


def extract_balatro_source(exe_path: Path, out_dir: Path, extract_all: bool = False) -> tuple[int, dict[str, int]]:
    if not exe_path.is_file():
        raise FileNotFoundError(f"Balatro executable not found: {exe_path}")

    if not zipfile.is_zipfile(exe_path):
        raise ValueError(f"File does not appear to contain a readable ZIP archive: {exe_path}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_root = out_dir.resolve()

    ext_counts: dict[str, int] = collections.Counter()
    extracted = 0

    with zipfile.ZipFile(exe_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower() or "<noext>"
            ext_counts[ext] += 1

            if not extract_all and ext not in DEFAULT_EXTENSIONS:
                continue

            target = (out_root / info.filename).resolve()
            if out_root not in target.parents and target != out_root:
                raise ValueError(f"Unsafe zip member path detected: {info.filename}")

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1

    return extracted, dict(ext_counts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Balatro Lua source from Balatro.exe")
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE, help="Path to Balatro.exe")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    parser.add_argument("--all", action="store_true", help="Extract all files instead of only text/Lua files")
    args = parser.parse_args()

    extracted, ext_counts = extract_balatro_source(args.exe, args.out, extract_all=args.all)
    print(f"Extracted {extracted} files from {args.exe} -> {args.out}")
    print("Archive file extension summary:")
    for ext, count in sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {ext:10s}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

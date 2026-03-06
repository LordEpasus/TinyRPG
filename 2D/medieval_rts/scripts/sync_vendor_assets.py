#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DIR_ASSETS = [
    "Tiny Swords (Free Pack)",
    "mystic_woods_free_2",
    "Pixel Art Top Down - Basic v1",
    "Sprout Lands - Sprites - Basic pack",
    "Tiny RPG Character Asset Pack v1.03 -Free Soldier&Orc",
]
FILE_ASSETS = [
    "Ship_full.png",
]


def _copy_dir(src: Path, dst: Path, *, clean: bool, dry_run: bool) -> None:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Missing source directory: {src}")
    if clean and dst.exists() and not dry_run:
        shutil.rmtree(dst)
    if dry_run:
        print(f"[dry-run] copy dir: {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    print(f"[ok] copied dir: {src.name}")


def _copy_file(src: Path, dst: Path, *, dry_run: bool) -> None:
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Missing source file: {src}")
    if dry_run:
        print(f"[dry-run] copy file: {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[ok] copied file: {src.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy external 2D assets into medieval_rts/assets/vendor2d")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to medieval_rts project root",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Path to external 2D asset root (default: <project-root>/..)",
    )
    parser.add_argument("--clean", action="store_true", help="Delete target directories before copying")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing files")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else project_root.parent
    vendor_root = project_root / "assets" / "vendor2d"

    print(f"project_root: {project_root}")
    print(f"source_root:  {source_root}")
    print(f"vendor_root:  {vendor_root}")

    if not args.dry_run:
        vendor_root.mkdir(parents=True, exist_ok=True)

    for name in DIR_ASSETS:
        _copy_dir(source_root / name, vendor_root / name, clean=args.clean, dry_run=args.dry_run)

    for name in FILE_ASSETS:
        _copy_file(source_root / name, vendor_root / name, dry_run=args.dry_run)

    if not args.dry_run:
        total_files = sum(1 for p in vendor_root.rglob("*") if p.is_file())
        print(f"[done] vendor assets synced. files={total_files}")
    else:
        print("[done] dry-run complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

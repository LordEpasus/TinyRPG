#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_VENDOR_PATHS = [
    Path("Tiny Swords (Free Pack)"),
    Path("mystic_woods_free_2"),
    Path("Pixel Art Top Down - Basic v1"),
    Path("Sprout Lands - Sprites - Basic pack"),
    Path("Tiny RPG Character Asset Pack v1.03 -Free Soldier&Orc"),
    Path("Ship_full.png"),
]


def run(cmd: list[str], cwd: Path) -> None:
    print("[run]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def ensure_vendor_assets(project_root: Path) -> None:
    vendor_root = project_root / "assets" / "vendor2d"
    missing: list[str] = []
    for rel in REQUIRED_VENDOR_PATHS:
        if not (vendor_root / rel).exists():
            missing.append(str(rel))
    if missing:
        joined = "\n  - ".join(missing)
        raise SystemExit(
            "Missing vendor assets. Run first:\n"
            f"  python scripts/sync_vendor_assets.py --project-root {project_root}\n"
            f"Missing:\n  - {joined}"
        )


def make_zip_from_dist(project_root: Path, app_name: str) -> Path:
    dist_dir = project_root / "dist" / app_name
    if not dist_dir.exists():
        raise SystemExit(f"dist folder not found: {dist_dir}")

    release_dir = project_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    zip_base = release_dir / f"{app_name}-win64"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=str(dist_dir.parent), base_dir=dist_dir.name)
    return Path(zip_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows exe with PyInstaller for Medieval RTS")
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]), help="medieval_rts project root")
    parser.add_argument("--name", default="MedievalKingdomsRTS", help="App name")
    parser.add_argument("--clean", action="store_true", help="Delete build/dist before build")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    app_name = args.name

    ensure_vendor_assets(project_root)

    if args.clean:
        shutil.rmtree(project_root / "build", ignore_errors=True)
        shutil.rmtree(project_root / "dist", ignore_errors=True)

    add_data = f"assets{os.pathsep}assets"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        app_name,
        "--add-data",
        add_data,
        "main.py",
    ]
    run(cmd, cwd=project_root)

    zip_path = make_zip_from_dist(project_root, app_name)
    print(f"[done] release zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

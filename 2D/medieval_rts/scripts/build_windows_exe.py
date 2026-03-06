#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from version import APP_NAME, GAME_RUNTIME_DIR, VERSION

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


def maybe_build_icon(project_root: Path) -> Path | None:
    icon_source = project_root / "assets" / "icons" / "png" / "castle.png"
    if not icon_source.exists():
        return None

    try:
        from PIL import Image
    except Exception:
        print("[warn] Pillow not found, exe icon skipped")
        return None

    build_dir = project_root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    icon_path = build_dir / "app_icon.ico"

    with Image.open(icon_source) as image:
        img = image.convert("RGBA")
        img.save(
            icon_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    return icon_path


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


def _pyinstaller_base_cmd(project_root: Path, icon_path: Path | None) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
    ]
    if icon_path is not None:
        cmd.extend(["--icon", str(icon_path)])
    return cmd


def build_game_runtime(project_root: Path, app_name: str, icon_path: Path | None) -> None:
    add_data = f"assets{os.pathsep}assets"
    cmd = _pyinstaller_base_cmd(project_root, icon_path)
    cmd.extend(
        [
            "--onedir",
            "--name",
            f"{app_name}-Game",
            "--add-data",
            add_data,
            "main.py",
        ]
    )
    run(cmd, cwd=project_root)


def build_launcher(project_root: Path, app_name: str, icon_path: Path | None) -> None:
    cmd = _pyinstaller_base_cmd(project_root, icon_path)
    cmd.extend(
        [
            "--onefile",
            "--name",
            app_name,
            "launcher.py",
        ]
    )
    run(cmd, cwd=project_root)


def assemble_release_layout(project_root: Path, app_name: str) -> Path:
    dist_dir = project_root / "dist"
    launcher_exe = dist_dir / f"{app_name}.exe"
    runtime_dir = dist_dir / f"{app_name}-Game"

    if not launcher_exe.exists():
        raise SystemExit(f"launcher exe not found: {launcher_exe}")
    if not runtime_dir.exists():
        raise SystemExit(f"runtime folder not found: {runtime_dir}")

    package_dir = dist_dir / app_name
    shutil.rmtree(package_dir, ignore_errors=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher_exe, package_dir / launcher_exe.name)
    shutil.copytree(runtime_dir, package_dir / GAME_RUNTIME_DIR, dirs_exist_ok=True)
    (package_dir / "version.txt").write_text(f"v{VERSION}\n", encoding="utf-8")
    return package_dir


def make_zip_from_dist(project_root: Path, package_dir: Path, app_name: str) -> Path:
    if not package_dir.exists():
        raise SystemExit(f"package folder not found: {package_dir}")

    release_dir = project_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    zip_base = release_dir / f"{app_name}-win64"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=str(package_dir.parent), base_dir=package_dir.name)
    return Path(zip_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows exe with PyInstaller for Medieval RTS")
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]), help="medieval_rts project root")
    parser.add_argument("--name", default=APP_NAME, help="App name")
    parser.add_argument("--clean", action="store_true", help="Delete build/dist before build")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    app_name = args.name

    ensure_vendor_assets(project_root)

    if args.clean:
        shutil.rmtree(project_root / "build", ignore_errors=True)
        shutil.rmtree(project_root / "dist", ignore_errors=True)

    icon_path = maybe_build_icon(project_root)
    build_game_runtime(project_root, app_name, icon_path)
    build_launcher(project_root, app_name, icon_path)
    package_dir = assemble_release_layout(project_root, app_name)
    zip_path = make_zip_from_dist(project_root, package_dir, app_name)
    print(f"[done] release zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

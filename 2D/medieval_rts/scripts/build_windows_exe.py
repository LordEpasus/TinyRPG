#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
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


def maybe_build_installer_theme(project_root: Path) -> tuple[Path | None, Path | None]:
    try:
        from PIL import Image, ImageColor, ImageDraw, ImageOps
    except Exception:
        print("[warn] Pillow not found, installer theme skipped")
        return None, None

    build_dir = project_root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    wizard_path = build_dir / "installer_wizard.bmp"
    banner_path = build_dir / "installer_banner.bmp"

    tiny_root = project_root / "assets" / "vendor2d" / "Tiny Swords (Free Pack)" / "UI Elements" / "UI Elements"
    banner_src = tiny_root / "Banners" / "Banner.png"
    paper_src = tiny_root / "Papers" / "RegularPaper.png"
    wood_src = tiny_root / "Wood Table" / "WoodTable.png"
    castle_src = project_root / "assets" / "icons" / "png" / "castle.png"

    wizard = Image.new("RGB", (164, 314), ImageColor.getrgb("#0f1b2b"))
    draw = ImageDraw.Draw(wizard)
    for y in range(wizard.height):
        blend = y / max(1, wizard.height - 1)
        r = int(15 + (47 - 15) * blend)
        g = int(27 + (36 - 27) * blend)
        b = int(43 + (52 - 43) * blend)
        draw.line((0, y, wizard.width, y), fill=(r, g, b))
    draw.rectangle((10, 10, 154, 304), outline=(191, 157, 107), width=2)

    if wood_src.exists():
        with Image.open(wood_src) as wood:
            wood = ImageOps.fit(wood.convert("RGBA"), (124, 74))
            wood.putalpha(136)
            wizard.paste(wood, (20, 214), wood)
    if paper_src.exists():
        with Image.open(paper_src) as paper:
            paper = ImageOps.fit(paper.convert("RGBA"), (132, 110))
            wizard.paste(paper, (16, 22), paper)
    if castle_src.exists():
        with Image.open(castle_src) as castle:
            castle = ImageOps.contain(castle.convert("RGBA"), (92, 92))
            wizard.paste(castle, ((wizard.width - castle.width) // 2, 96), castle)
    if banner_src.exists():
        with Image.open(banner_src) as banner:
            banner = ImageOps.contain(banner.convert("RGBA"), (120, 28))
            wizard.paste(banner, ((wizard.width - banner.width) // 2, 176), banner)

    draw.text((24, 188), "Medieval", fill=(245, 236, 214))
    draw.text((24, 204), "Kingdoms RTS", fill=(245, 236, 214))
    wizard.save(wizard_path, format="BMP")

    banner = Image.new("RGB", (55, 55), ImageColor.getrgb("#142133"))
    draw = ImageDraw.Draw(banner)
    draw.rectangle((0, 0, banner.width - 1, banner.height - 1), outline=(191, 157, 107), width=2)
    if castle_src.exists():
        with Image.open(castle_src) as castle:
            castle = ImageOps.contain(castle.convert("RGBA"), (36, 36))
            banner.paste(castle, ((banner.width - castle.width) // 2, (banner.height - castle.height) // 2), castle)
    banner.save(banner_path, format="BMP")
    return wizard_path, banner_path


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


def find_iscc() -> Path | None:
    candidates = [
        shutil.which("iscc"),
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def write_inno_script(
    project_root: Path,
    package_dir: Path,
    app_name: str,
    icon_path: Path | None,
    wizard_image: Path | None,
    banner_image: Path | None,
) -> Path:
    build_dir = project_root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    script_path = build_dir / "windows_installer.iss"
    icon_line = f'SetupIconFile={icon_path.as_posix()}' if icon_path is not None else ""
    wizard_line = f'WizardImageFile={wizard_image.as_posix()}' if wizard_image is not None else ""
    banner_line = f'WizardSmallImageFile={banner_image.as_posix()}' if banner_image is not None else ""
    script = textwrap.dedent(
        f"""\
        [Setup]
        AppId=LordEpasus.MedievalKingdomsRTS
        AppName={app_name}
        AppVerName={app_name} v{VERSION}
        AppVersion={VERSION}
        AppPublisher=LordEpasus
        DefaultDirName={{localappdata}}\\Programs\\{app_name}
        DefaultGroupName={app_name}
        DisableProgramGroupPage=yes
        UninstallDisplayIcon={{app}}\\{app_name}.exe
        OutputDir={ (project_root / "release").as_posix() }
        OutputBaseFilename={app_name}-Setup
        ArchitecturesAllowed=x64compatible
        ArchitecturesInstallIn64BitMode=x64compatible
        PrivilegesRequired=lowest
        Compression=lzma
        SolidCompression=yes
        WizardStyle=modern
        WizardResizable=no
        {wizard_line}
        {banner_line}
        {icon_line}

        [Languages]
        Name: "turkish"; MessagesFile: "compiler:Languages\\Turkish.isl"

        [Tasks]
        Name: "desktopicon"; Description: "Masaustu kisayolu olustur"; Flags: unchecked

        [Files]
        Source: "{package_dir.as_posix()}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

        [Icons]
        Name: "{{autoprograms}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"
        Name: "{{autodesktop}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"; Tasks: desktopicon

        [Run]
        Filename: "{{app}}\\{app_name}.exe"; Description: "Oyunu baslat"; Flags: nowait postinstall skipifsilent
        """
    )
    script_path.write_text(script, encoding="utf-8")
    return script_path


def build_windows_installer(project_root: Path, package_dir: Path, app_name: str, icon_path: Path | None) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Inno Setup (ISCC.exe) bulunamadi. --installer icin once Inno Setup kurulu olmali.")
    wizard_image, banner_image = maybe_build_installer_theme(project_root)
    script_path = write_inno_script(project_root, package_dir, app_name, icon_path, wizard_image, banner_image)
    run([str(iscc), str(script_path)], cwd=project_root)
    installer_path = project_root / "release" / f"{app_name}-Setup.exe"
    if not installer_path.exists():
        raise SystemExit(f"installer olusmadi: {installer_path}")
    return installer_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows exe with PyInstaller for Medieval RTS")
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]), help="medieval_rts project root")
    parser.add_argument("--name", default=APP_NAME, help="App name")
    parser.add_argument("--clean", action="store_true", help="Delete build/dist before build")
    parser.add_argument("--installer", action="store_true", help="Build Windows setup installer with Inno Setup")
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
    installer_path = None
    if args.installer:
        installer_path = build_windows_installer(project_root, package_dir, app_name, icon_path)
    print(f"[done] release zip: {zip_path}")
    if installer_path is not None:
        print(f"[done] release installer: {installer_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

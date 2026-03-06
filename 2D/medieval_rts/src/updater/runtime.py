from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from version import GAME_EXE, GAME_RUNTIME_DIR, LAUNCHER_EXE


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    if is_frozen_build():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def launcher_executable() -> Path:
    root = install_root()
    if is_frozen_build():
        return root / LAUNCHER_EXE
    return root / "launcher.py"


def runtime_game_executable() -> Path:
    root = install_root()
    if is_frozen_build():
        return root / GAME_RUNTIME_DIR / GAME_EXE
    return root / "main.py"


def launch_game_process() -> subprocess.Popen[bytes]:
    game_path = runtime_game_executable()
    if is_frozen_build():
        return subprocess.Popen([str(game_path)], cwd=str(game_path.parent))
    return subprocess.Popen([sys.executable, str(game_path)], cwd=str(game_path.parent))


def apply_portable_update(staged_root: Path, destination_root: Path) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in staged_root.iterdir():
        target = destination_root / source.name
        if source.is_dir():
            if target.exists() and not target.is_dir():
                target.unlink()
            shutil.copytree(source, target, dirs_exist_ok=True)
            continue
        if target.exists() and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copy2(source, target)


def schedule_windows_update(staged_root: Path, destination_root: Path, *, cleanup_root: Path | None = None) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    script_path = Path(tempfile.gettempdir()) / f"mkrtsupd_{int(time.time())}.cmd"
    launcher_path = launcher_executable()

    cleanup_line = ""
    if cleanup_root is not None:
        cleanup_line = f'rmdir /s /q "{cleanup_root}" >nul 2>nul'

    script_body = textwrap.dedent(
        f"""\
        @echo off
        setlocal enableextensions
        set "SRC={staged_root}"
        set "DST={destination_root}"
        set "LAUNCHER={launcher_path}"

        for /l %%i in (1,1,25) do (
            timeout /t 1 /nobreak >nul
            del "%LAUNCHER%" >nul 2>nul
            if not exist "%LAUNCHER%" goto copy
        )

        :copy
        robocopy "%SRC%" "%DST%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
        if %ERRORLEVEL% GEQ 8 goto fail
        {cleanup_line}
        start "" "%LAUNCHER%" --skip-update
        del "%~f0"
        exit /b 0

        :fail
        start "" "%LAUNCHER%" --skip-update --update-failed
        del "%~f0"
        exit /b 1
        """
    )
    script_path.write_text(script_body, encoding="utf-8")

    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x08000000
    subprocess.Popen(
        ["cmd", "/c", str(script_path)],
        cwd=str(destination_root),
        creationflags=creationflags,
    )
    return script_path

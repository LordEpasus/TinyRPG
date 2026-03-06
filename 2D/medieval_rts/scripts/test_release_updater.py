#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.updater import (
    apply_portable_update,
    download_asset,
    extract_release_archive,
    fetch_release_by_tag,
    find_release_asset,
    has_newer_version,
)
from version import APP_NAME, GITHUB_RELEASE_ASSET


def _read_version(package_root: Path) -> str:
    version_file = package_root / "version.txt"
    if not version_file.exists():
        raise SystemExit(f"version.txt bulunamadi: {version_file}")
    return version_file.read_text(encoding="utf-8").strip()


def _validate_layout(package_root: Path) -> None:
    launcher = package_root / f"{APP_NAME}.exe"
    runtime = package_root / "runtime"
    runtime_exe = runtime / f"{APP_NAME}-Game.exe"
    if not launcher.exists():
        raise SystemExit(f"launcher bulunamadi: {launcher}")
    if not runtime.exists():
        raise SystemExit(f"runtime klasoru bulunamadi: {runtime}")
    if not runtime_exe.exists():
        raise SystemExit(f"runtime exe bulunamadi: {runtime_exe}")


def _download_release_asset(tag: str, target_dir: Path) -> Path:
    release = fetch_release_by_tag(tag)
    if release is None:
        raise SystemExit(f"Release bulunamadi: {tag}")
    asset = find_release_asset(release, GITHUB_RELEASE_ASSET)
    if asset is None:
        raise SystemExit(f"{tag} icin asset bulunamadi: {GITHUB_RELEASE_ASSET}")
    suffix = Path(asset.name).suffix or ".zip"
    archive = target_dir / f"{tag}-{APP_NAME}{suffix}"
    download_asset(asset, archive)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Public GitHub release zip'leriyle updater gecisini test eder")
    parser.add_argument("--from-tag", default="v0.1.1", help="Kurulu sayilacak release tag'i")
    parser.add_argument("--to-tag", default="v0.1.2", help="Guncellenecek release tag'i")
    parser.add_argument("--keep-temp", action="store_true", help="Gecici dosyalari silme")
    args = parser.parse_args()

    if not has_newer_version(args.from_tag, args.to_tag):
        raise SystemExit(f"Hedef surum daha yeni degil: {args.from_tag} -> {args.to_tag}")

    temp_dir = Path(tempfile.mkdtemp(prefix="mkrts-update-test-"))
    try:
        source_zip = _download_release_asset(args.from_tag, temp_dir / "downloads")
        target_zip = _download_release_asset(args.to_tag, temp_dir / "downloads")

        source_root = extract_release_archive(source_zip, temp_dir / "extract" / "from")
        target_root = extract_release_archive(target_zip, temp_dir / "extract" / "to")

        install_root = temp_dir / "install"
        apply_portable_update(source_root, install_root)
        before_version = _read_version(install_root)
        _validate_layout(install_root)

        apply_portable_update(target_root, install_root)
        after_version = _read_version(install_root)
        _validate_layout(install_root)

        expected = args.to_tag
        if before_version != args.from_tag:
            raise SystemExit(f"Baslangic surumu beklenen gibi degil: {before_version} != {args.from_tag}")
        if after_version != expected:
            raise SystemExit(f"Guncellenen surum beklenen gibi degil: {after_version} != {expected}")

        print(f"[ok] updater layout testi gecti: {args.from_tag} -> {args.to_tag}")
        print(f"[path] simulated install root: {install_root}")
        if args.keep_temp:
            print(f"[keep] temp korunuyor: {temp_dir}")
        return 0
    finally:
        if temp_dir.exists() and not args.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

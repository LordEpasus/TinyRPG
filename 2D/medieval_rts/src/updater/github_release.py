from __future__ import annotations

import json
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from version import APP_NAME, GITHUB_LATEST_RELEASE_API, GITHUB_TAG_RELEASE_API


class UpdaterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag_name: str
    version: str
    html_url: str
    published_at: str
    assets: tuple[ReleaseAsset, ...]


_VERSION_RE = re.compile(r"\d+")


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts = [int(part) for part in _VERSION_RE.findall(raw)]
    if not parts:
        return (0,)
    return tuple(parts)


def has_newer_version(current_version: str, latest_version: str) -> bool:
    return _version_tuple(latest_version) > _version_tuple(current_version)


def _fetch_release(api_url: str, timeout: float = 6.0) -> ReleaseInfo | None:
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}-launcher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
    except Exception:
        return None

    tag_name = str(payload.get("tag_name", "")).strip()
    if not tag_name:
        return None

    assets: list[ReleaseAsset] = []
    for item in payload.get("assets", []):
        name = str(item.get("name", "")).strip()
        url = str(item.get("browser_download_url", "")).strip()
        size = int(item.get("size", 0) or 0)
        if not name or not url:
            continue
        assets.append(ReleaseAsset(name=name, download_url=url, size=size))

    return ReleaseInfo(
        tag_name=tag_name,
        version=tag_name.removeprefix("v"),
        html_url=str(payload.get("html_url", "")).strip(),
        published_at=str(payload.get("published_at", "")).strip(),
        assets=tuple(assets),
    )


def fetch_latest_release(timeout: float = 6.0) -> ReleaseInfo | None:
    return _fetch_release(GITHUB_LATEST_RELEASE_API, timeout=timeout)


def fetch_release_by_tag(tag: str, timeout: float = 6.0) -> ReleaseInfo | None:
    clean = str(tag).strip()
    if not clean:
        return None
    return _fetch_release(GITHUB_TAG_RELEASE_API.format(tag=clean), timeout=timeout)


def find_release_asset(release: ReleaseInfo, asset_name: str) -> ReleaseAsset | None:
    for asset in release.assets:
        if asset.name == asset_name:
            return asset
    return None


def download_asset(
    asset: ReleaseAsset,
    target_path: Path,
    *,
    progress_callback=None,
    timeout: float = 30.0,
) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        asset.download_url,
        headers={"User-Agent": f"{APP_NAME}-launcher"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length", asset.size) or asset.size or 0)
            downloaded = 0
            with target_path.open("wb") as fh:
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total)
    except Exception as exc:
        raise UpdaterError(f"Release indirilemedi: {exc}") from exc
    return target_path


def extract_release_archive(archive_path: Path, target_dir: Path) -> Path:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(target_dir)
    except Exception as exc:
        raise UpdaterError(f"Release paketi acilamadi: {exc}") from exc

    dirs = [path for path in target_dir.iterdir() if path.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    return target_dir

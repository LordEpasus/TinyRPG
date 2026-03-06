from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from version import APP_NAME, GITHUB_RELEASE_ASSET, GITHUB_RELEASES_URL, VERSION
from src.updater import (
    download_asset,
    extract_release_archive,
    fetch_latest_release,
    find_release_asset,
    has_newer_version,
    install_root,
    is_frozen_build,
    launch_game_process,
    schedule_windows_update,
)

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:  # pragma: no cover - optional runtime UI
    tk = None
    messagebox = None
    ttk = None


class _ProgressWindow:
    def __init__(self) -> None:
        self.root = None
        self.label = None
        self.bar = None
        self.status = None
        self._last_percent = -1
        if tk is None or ttk is None:
            return
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} Launcher")
        self.root.geometry("460x160")
        self.root.resizable(False, False)
        self.root.configure(bg="#132033")
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        title = tk.Label(
            self.root,
            text=f"{APP_NAME} guncelleyici",
            font=("Georgia", 16, "bold"),
            fg="#f4e5c3",
            bg="#132033",
        )
        title.pack(pady=(18, 8))

        self.label = tk.Label(
            self.root,
            text="Guncellemeler kontrol ediliyor...",
            font=("Georgia", 11),
            fg="#ebf1fb",
            bg="#132033",
        )
        self.label.pack()

        self.bar = ttk.Progressbar(self.root, orient="horizontal", mode="determinate", length=340)
        self.bar.pack(pady=(18, 6))

        self.status = tk.Label(
            self.root,
            text="Hazir",
            font=("Georgia", 10),
            fg="#a9bdd9",
            bg="#132033",
        )
        self.status.pack()
        self._pump()

    def _pump(self) -> None:
        if self.root is None:
            return
        self.root.update_idletasks()
        self.root.update()

    def set_status(self, text: str) -> None:
        if self.label is not None:
            self.label.config(text=text)
        if self.status is not None:
            self.status.config(text=text)
        self._pump()

    def set_progress(self, downloaded: int, total: int) -> None:
        if self.bar is None:
            return
        if total <= 0:
            self.bar.config(mode="indeterminate")
            self.bar.start(10)
            self._pump()
            return
        if str(self.bar.cget("mode")) != "determinate":
            self.bar.stop()
            self.bar.config(mode="determinate")
        percent = max(0, min(100, int((downloaded / max(1, total)) * 100)))
        if percent == self._last_percent:
            return
        self._last_percent = percent
        self.bar["value"] = percent
        if self.status is not None:
            self.status.config(text=f"Indiriliyor... %{percent}")
        self._pump()

    def ask_update(self, latest_version: str, release_url: str) -> bool:
        message = (
            f"Yeni surum bulundu.\n\n"
            f"Kurulu surum: v{VERSION}\n"
            f"Yeni surum: v{latest_version}\n\n"
            f"Guncelleme indirilsin mi?\n{release_url}"
        )
        if messagebox is None:
            return True
        return bool(messagebox.askyesno(f"{APP_NAME} Guncelleme", message, parent=self.root))

    def show_info(self, text: str) -> None:
        if messagebox is not None and self.root is not None:
            messagebox.showinfo(APP_NAME, text, parent=self.root)

    def show_error(self, text: str) -> None:
        if messagebox is not None and self.root is not None:
            messagebox.showerror(APP_NAME, text, parent=self.root)

    def close(self) -> None:
        if self.bar is not None and str(self.bar.cget("mode")) == "indeterminate":
            self.bar.stop()
        if self.root is not None:
            self.root.destroy()
            self.root = None


def _should_check_updates(args: list[str]) -> bool:
    if "--skip-update" in args:
        return False
    if not is_frozen_build():
        return False
    return sys.platform.startswith("win")


def _run_update_flow(ui: _ProgressWindow) -> bool:
    ui.set_status("Guncellemeler kontrol ediliyor...")
    release = fetch_latest_release()
    if release is None or not has_newer_version(VERSION, release.version):
        return False

    asset = find_release_asset(release, GITHUB_RELEASE_ASSET)
    if asset is None:
        ui.show_error(
            "Yeni surum bulundu ama uygun Windows paketi bulunamadi.\n"
            f"Elle indirmek icin: {GITHUB_RELEASES_URL}"
        )
        return False

    if not ui.ask_update(release.version, release.html_url or GITHUB_RELEASES_URL):
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix="mkrtsupd-"))
    keep_temp_dir = False
    try:
        archive_path = temp_dir / asset.name
        ui.set_status("Yeni surum indiriliyor...")
        download_asset(asset, archive_path, progress_callback=ui.set_progress)
        ui.set_status("Paket aciliyor...")
        staged_root = extract_release_archive(archive_path, temp_dir / "release")
        ui.set_status("Kurulum hazirlaniyor...")
        schedule_windows_update(staged_root, install_root(), cleanup_root=temp_dir)
        keep_temp_dir = True
    except Exception as exc:
        ui.show_error(str(exc))
        return False
    finally:
        if temp_dir.exists() and not keep_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return True


def main() -> int:
    args = sys.argv[1:]
    ui = _ProgressWindow()
    try:
        if "--update-failed" in args:
            ui.show_error("Guncelleme tamamlanamadi. Mevcut surum aciliyor.")

        if _should_check_updates(args):
            if _run_update_flow(ui):
                return 0

        ui.set_status("Oyun baslatiliyor...")
        try:
            launch_game_process()
        except FileNotFoundError:
            ui.show_error(
                "Oyun dosyalari bulunamadi.\n"
                "Release paketini yeniden indirip tekrar acmayi dene."
            )
            return 1
        return 0
    finally:
        ui.close()


if __name__ == "__main__":
    raise SystemExit(main())

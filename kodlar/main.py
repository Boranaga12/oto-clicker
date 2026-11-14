from __future__ import annotations

import logging
import sys
import threading
import traceback
from .platform_win import SingleInstanceLock, enable_dpi_awareness, set_application_identity

# Set the coordinate system before GUI/input libraries can establish a DPI mode.
enable_dpi_awareness()

import tkinter as tk
from logging.handlers import RotatingFileHandler
from tkinter import messagebox

from .app_paths import writable_data_file
from .config import load_config
from .engine import RandomizedAutoClicker
from .gui import ClickerApp


LOG_FILE = writable_data_file("app.log", migrate_legacy=False)


def configure_logging() -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except OSError:
        # Günlük klasörü geçici olarak kilitliyse uygulamanın açılmasını engelleme.
        logging.basicConfig(level=logging.INFO)


def run_application() -> None:
    try:
        app_config = load_config()
        clicker = RandomizedAutoClicker(app_config)
        root = tk.Tk()
        app = ClickerApp(root, clicker)
    except Exception as exc:
        logging.exception("Uygulama başlatılamadı")
        try:
            messagebox.showerror("Arık Makro", f"Uygulama başlatılamadı:\n{exc}")
        except tk.TclError:
            pass
        raise

    engine_thread = threading.Thread(
        target=clicker.run,
        name="macro-engine",
        daemon=True,
    )
    engine_thread.start()

    def report_tk_error(exc_type, exc_value, exc_traceback) -> None:
        logging.getLogger(__name__).error(
            "Arayüz hatası",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        messagebox.showerror("Arık Makro", f"Beklenmeyen hata:\n{exc_value}")

    root.report_callback_exception = report_tk_error

    def on_close() -> None:
        clicker.log("Program sonlandırılıyor.")
        app.shutdown()
        clicker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        clicker.stop()
        engine_thread.join(timeout=2.0)


def main() -> None:
    configure_logging()
    set_application_identity()
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Arık Makro", "Arık Makro zaten çalışıyor.", parent=root)
        root.destroy()
        instance_lock.release()
        return
    try:
        run_application()
    finally:
        instance_lock.release()


def cli() -> int:
    try:
        main()
    except Exception:
        # python.exe is supervised by baslat.bat; preserve the failure evidence.
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())

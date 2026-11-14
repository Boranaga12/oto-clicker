"""Console-free startup with visible errors, including failed application imports."""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import traceback
from pathlib import Path

from .app_paths import writable_data_file


def report_startup_error(error: Exception) -> None:
    details = traceback.format_exc()
    destination = writable_data_file('startup-error.log', migrate_legacy=False)
    saved = None
    for candidate in (destination, Path(tempfile.gettempdir()) / 'ArikMakro-startup-error.log'):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(details, encoding='utf-8')
            saved = candidate
            break
        except OSError:
            continue
    location = f'Hata ayrıntıları:\n{saved}' if saved else 'Hata günlüğü yazılamadı.'
    message = f'Uygulama açılamadı:\n{error}\n\n{location}'
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, message, 'Arık Makro — Açılış Hatası', 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(message + '\n')


def main() -> int:
    try:
        # Import inside the guard so missing dependencies cannot fail silently.
        from .main import main as run_application
        run_application()
    except Exception as error:
        report_startup_error(error)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

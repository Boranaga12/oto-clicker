"""Run with `py kodlar/hata_ayikla.py` to see startup errors in a console."""
from pathlib import Path
import subprocess


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    interpreters = [root / 'kodlar/.venv/Scripts/python.exe', root / '.venv/Scripts/python.exe']
    interpreter = next((path for path in interpreters if path.is_file()), None)
    if interpreter is None:
        print('Önce baslat.bat dosyasını çalıştırın.')
    else:
        subprocess.run([str(interpreter), '-u', '-X', 'faulthandler', '-m', 'kodlar.main'], cwd=root)
    input('Kapatmak için Enter...')


if __name__ == '__main__':
    main()

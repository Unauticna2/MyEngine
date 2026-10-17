"""Install optional importer packages into the Python used by the editor."""
from pathlib import Path
import configparser
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    interpreter = Path(sys.executable)
    ini = root/'python.ini'
    if ini.is_file():
        config = configparser.ConfigParser()
        config.read(ini, encoding='utf-16')
        candidate = Path(config.get('Python', 'Home'))/'python.exe'
        if not candidate.is_file():
            raise RuntimeError('Configured Python was not found: '+str(candidate))
        interpreter = candidate
    print('Installing importer packages into:', interpreter, flush=True)
    result = subprocess.call([str(interpreter), '-m', 'pip', 'install',
                              'pypdfium2>=4.30,<6', 'Pillow>=10.3,<13'])
    if result:
        return result
    print('Python dependencies installed. LibreOffice must also be installed.')
    print('https://www.libreoffice.org/download/download-libreoffice/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

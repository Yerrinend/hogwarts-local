"""Standalone executable entry point; credentials never bundled."""
import ctypes
import os
from pathlib import Path
import sys
import threading
import urllib.request
import webbrowser

def main():
    folder = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'HogwartsLocal'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['RPG_DATA_DIR'] = str(folder)
    url = 'http://127.0.0.1:8765'
    mode = 'personal' if '--personal' in sys.argv else 'shared'
    try:
        with urllib.request.urlopen(url + '/api/bootstrap', timeout=2) as r:
            import json
            if json.load(r).get('starter', '').startswith('Хроники Хогвартса'):
                webbrowser.open(url + '/?mode=' + mode)
                return
    except Exception:
        pass
    import server
    app = server.ThreadingHTTPServer(('127.0.0.1', server.PORT), server.Handler)
    threading.Timer(.6, lambda: webbrowser.open(url + '/?mode=' + mode)).start()
    try:
        app.serve_forever()
    finally:
        app.server_close()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(None, 'Не удалось запустить приложение. Возможно, порт 8765 занят.\n' + str(e), 'Хроники Хогвартса', 16)

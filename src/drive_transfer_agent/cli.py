import argparse
import threading
import webbrowser

import uvicorn
from filelock import FileLock, Timeout

from .api import create_app
from .config import Settings


def main():
    parser = argparse.ArgumentParser(description="Drive Transfer Agent — assistente local")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    settings.initialize()
    lock = FileLock(settings.data / "instance.lock", timeout=0)
    try:
        with lock:
            if not args.no_browser:
                threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{settings.dta_port}")).start()
            uvicorn.run(
                create_app(settings), host="127.0.0.1", port=settings.dta_port, workers=1, access_log=False
            )
    except Timeout:
        print("O aplicativo já está em execução. Usando a instância existente.")
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{settings.dta_port}")


if __name__ == "__main__":
    main()

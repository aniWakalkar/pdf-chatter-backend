import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SERVICES = [
    ("auth-service", "services.auth_service.main:app", 8001, "127.0.0.1"),
    ("document-service", "services.document_service.main:app", 8002, "127.0.0.1"),
    ("chat-service", "services.chat_service.main:app", 8003, "127.0.0.1"),
    ("api-gateway", "services.api_gateway.main:app", int(os.getenv("PORT", "8000")), os.getenv("HOST", "127.0.0.1")),
]


def main() -> None:
    reload = "--reload" in sys.argv
    processes: list[tuple[str, subprocess.Popen]] = []
    for name, app, port, host in SERVICES:
        command = [sys.executable, "-m", "uvicorn", app, "--host", host, "--port", str(port)]
        if reload:
            command += ["--reload", "--reload-dir", "services", "--reload-dir", "shared"]
        processes.append((name, subprocess.Popen(command, cwd=BASE_DIR)))
        print(f"Started {name} on http://{host}:{port}")

    def shutdown(*_):
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        for name, process in processes:
            if process.poll() is not None:
                print(f"{name} exited with code {process.returncode}. Stopping all services.")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()

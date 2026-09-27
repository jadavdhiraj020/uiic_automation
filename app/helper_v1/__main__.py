"""Run with: uv run python -m app.helper_v1"""

import logging
import os
from pathlib import Path

from .api import HelperServer, HOST, PORT
from .coordinator import RunCoordinator


def main():
    if os.name != "nt":
        raise SystemExit("The UIIC V1 helper requires an interactive Windows user session")
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "DocWriterHelperV1"
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=root / "helper.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    coordinator = RunCoordinator(root)
    server = HelperServer(coordinator)
    print(f"UIIC helper listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        coordinator.shutdown()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

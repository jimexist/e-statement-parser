"""Native macOS window (WebKit via pywebview) around the local web UI.

The server listens on a random 127.0.0.1 port that lives only as long as the
window; nothing is reachable from other machines.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

from .store import DEFAULT_DB


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    """Exposed to the page as window.pywebview.api (WKWebView can't download blobs)."""

    def save_csv(self, text: str) -> str | None:
        import webview

        path = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename="transactions.csv")
        if not path:
            return None
        path = path if isinstance(path, str) else path[0]
        Path(path).write_text(text)
        return path


def main(db_path: Path = DEFAULT_DB) -> None:
    import uvicorn
    import webview

    from .web import create_app

    port = _free_port()
    app = create_app(db_path)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        threading.Event().wait(0.05)

    webview.create_window("eStatement", f"http://127.0.0.1:{port}/", width=1280, height=820,
                          min_size=(820, 560), js_api=Api())
    webview.start(private_mode=True)
    server.should_exit = True


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB)

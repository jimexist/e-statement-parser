"""PyInstaller entry point for eStatement.app."""

import multiprocessing
import sys

from estatement.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ("import", "parse", "export", "serve", "download-model"):
        from estatement.cli import main as cli

        raise SystemExit(cli(sys.argv[1:]))
    main()

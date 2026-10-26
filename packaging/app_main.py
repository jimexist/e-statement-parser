"""PyInstaller entry point for eStatement.app."""

import multiprocessing
import sys

from estatement.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Any arguments (subcommand or global option like --db) mean CLI use; none opens the window.
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        from estatement.cli import main as cli

        raise SystemExit(cli(sys.argv[1:]))
    main()

#!/usr/bin/env python3
"""Thin wrapper: delegates to sk_entry.main without extra behavior."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from sk_entry import main  # noqa: E402


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # the entry itself has a last-resort guard
        sys.stderr.write("run_skill failed: %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(0)

#!/usr/bin/env python3
"""seed_demo.py - seed the demo tenant with the synthetic scenarios (F-10).

Not implemented yet: the scenario JSON files and the seeding pipeline land with F-10.
This stub exits non-zero so `make demo` cannot silently pretend success.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("[seed] F-10 not implemented yet (scripts/seed_demo.py is a stub)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

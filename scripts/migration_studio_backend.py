#!/usr/bin/env python3
"""Dispatch the Python modules embedded in PVM Migration Studio packages."""

import sys

from pvm_server import migrate, tooling


MODULES = {
    "pvm_server.migrate": migrate.main,
    "pvm_server.tooling": tooling.main,
}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--self-test"]:
        assert set(MODULES) == {"pvm_server.migrate", "pvm_server.tooling"}
        print("migration studio backend self-test passed")
        return 0
    if len(arguments) < 2 or arguments[0] != "-m" or arguments[1] not in MODULES:
        modules = ", ".join(sorted(MODULES))
        raise SystemExit(f"usage: pvm_migration_backend -m MODULE ... ({modules})")
    module = arguments[1]
    sys.argv = [module, *arguments[2:]]
    MODULES[module]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

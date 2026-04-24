#!/usr/bin/env python3
"""Generate a conservative Verilator filelist for an APF core tree.

This is intentionally simple: it preserves APF shim order first, then appends RTL
files found under user-supplied roots. Review the generated filelist for vendor IP
that needs a real model instead of a stub.
"""
from __future__ import annotations

import argparse
from pathlib import Path

RTL_EXTS = {".v", ".sv"}
SHIMS = [
    "rtl_shims/mf_pllbase_sim.sv",
    "rtl_shims/altsyncram_sim.sv",
    "rtl_shims/vendor_ip_stubs.sv",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("roots", nargs="*", default=["rtl", "core/rtl", "apf/framework"], help="RTL roots to scan")
    p.add_argument("-o", "--output", default="build/verilator_filelist.f")
    p.add_argument("--incdir", action="append", default=["rtl_shims"], help="include directory")
    args = p.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for inc in args.incdir:
        lines.append(f"+incdir+{inc}")
    lines.extend(SHIMS)

    seen = set(lines)
    for root_s in args.roots:
        root = Path(root_s)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in RTL_EXTS:
                continue
            item = path.as_posix()
            if item not in seen:
                lines.append(item)
                seen.add(item)

    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} with {len(lines)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

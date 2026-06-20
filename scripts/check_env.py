from __future__ import annotations

import shutil
import subprocess


def check(cmd: str) -> bool:
    found = shutil.which(cmd) is not None
    print(f"{'[OK]' if found else '[MISSING]'} {cmd}")
    if found:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=8)
            first = (result.stdout or result.stderr).splitlines()[0]
            print(f"       {first[:100]}")
        except Exception:
            pass
    return found


if __name__ == "__main__":
    print("Book System OS environment check\n")
    ok = True
    ok &= check("python3") or check("python")
    ok &= check("pandoc")
    ok &= check("xelatex")
    raise SystemExit(0 if ok else 1)

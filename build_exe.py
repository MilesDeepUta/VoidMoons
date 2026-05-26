"""
One-shot build helper. Wraps PyInstaller for the common case.

    python build_exe.py            # builds dist/MoonScan/
    python build_exe.py --clean    # rebuilds from scratch

After building, zip dist/MoonScan/ and ship that to alliance mates. The
exe sits inside; they double-click MoonScan.exe to run.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true", help="Remove build/ and dist/ first")
    args = p.parse_args()

    if args.clean:
        for d in ("build", "dist"):
            path = HERE / d
            if path.exists():
                print(f"Removing {path}...")
                shutil.rmtree(path)

    if not (HERE / "data" / "eve_static.db").exists():
        print("ERROR: data/eve_static.db is missing. Run build_sde.py first.", file=sys.stderr)
        return 2

    cmd = [sys.executable, "-m", "PyInstaller", "moonscan.spec", "--noconfirm"]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=HERE)


if __name__ == "__main__":
    raise SystemExit(main())

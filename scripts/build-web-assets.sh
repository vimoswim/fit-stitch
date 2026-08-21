#!/usr/bin/env bash
# Build the Python wheels the browser build of fit-stitch loads into Pyodide.
#
# Produces web/public/wheels/ with three pure-Python wheels and a manifest:
#
#   fit_stitch-<ver>-py3-none-any.whl   built from this repo
#   fit_tool-<ver>-py3-none-any.whl     from PyPI, version pinned by poetry.lock
#   garmin_fit_sdk-<ver>-py3-none-any.whl
#
# The wheels are self-hosted rather than fetched from PyPI at runtime, so a
# deployed page depends on no third-party host and cannot be broken by an
# upstream release. Copy the directory into the website repo's public/ to
# publish a new engine version.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/web/public/wheels"

cd "$ROOT"
rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> building fit-stitch wheel"
rm -rf dist
poetry build --format wheel >/dev/null
cp dist/*.whl "$OUT/"

echo "==> downloading pinned dependency wheels"
python3 - "$OUT" <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path

out = Path(sys.argv[1])
lock = tomllib.loads(Path("poetry.lock").read_text())
pinned = {
    p["name"]: p["version"]
    for p in lock["package"]
    if p["name"] in {"fit-tool", "garmin-fit-sdk"}
}
if len(pinned) != 2:
    sys.exit(f"poetry.lock does not pin both runtime dependencies: {pinned}")

for name, version in sorted(pinned.items()):
    print(f"    {name}=={version}")
    subprocess.run(
        [sys.executable, "-m", "pip", "download", f"{name}=={version}",
         "--only-binary=:all:", "--no-deps", "--quiet", "--dest", str(out)],
        check=True,
    )
PY

echo "==> writing manifest"
python3 - "$OUT" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

out = Path(sys.argv[1])
version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
wheels = sorted(p.name for p in out.glob("*.whl"))
if len(wheels) != 3:
    sys.exit(f"expected 3 wheels, found {len(wheels)}: {wheels}")
(out / "manifest.json").write_text(
    json.dumps({"engine": version, "wheels": wheels}, indent=2) + "\n"
)
print(json.dumps({"engine": version, "wheels": wheels}, indent=2))
PY

echo
echo "wheels ready in $OUT"
echo "to publish, copy them into the website repo:"
echo "    cp $OUT/* <vimoswim-website>/public/wheels/"

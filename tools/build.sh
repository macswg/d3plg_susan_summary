#!/bin/sh
# Package the plugin for install.
#
# There is no compile step and there never should be (see CLAUDE.md): this only
# stages the files Designer actually loads into build/susan_summary/ and zips
# them, so the zip matches what the README tells people to unzip into their
# plugins folder. Everything else in the repo -- tests, tools, ref, CLAUDE.md --
# is development material and is deliberately left out.
#
#   sh tools/build.sh
#
# Fails the build if the test suite fails, so a broken snapshot.py cannot be
# packaged.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build"
STAGE="$OUT/susan_summary"
ZIP="$OUT/susan_summary.zip"

# The files the plugin loads at runtime: index.html pulls icon.svg and index.js,
# index.js posts snapshot.py to the director, Designer reads d3plugin.json, and
# README.md ships so the folder explains itself once it is installed.
FILES="d3plugin.json icon.svg index.html index.js snapshot.py README.md"

cd "$ROOT"

echo "==> tests"
python3 tests/test_snapshot.py >/dev/null || {
    echo "build aborted: tests failed (run python3 tests/test_snapshot.py)" >&2
    exit 1
}
echo "    ok"

echo "==> staging"
# Guard the rm: only ever remove a path inside this repo.
case "$STAGE" in
    "$ROOT"/build/*) rm -rf "$STAGE" ;;
    *) echo "refusing to remove $STAGE" >&2; exit 1 ;;
esac
mkdir -p "$STAGE"

for f in $FILES; do
    [ -f "$ROOT/$f" ] || { echo "missing $f" >&2; exit 1; }
    cp "$ROOT/$f" "$STAGE/$f"
done

# Sanity: a plugin that ships a stale snapshot.py is the failure that matters.
grep -q 'SCHEMA_VERSION' "$STAGE/snapshot.py" || {
    echo "staged snapshot.py looks wrong" >&2; exit 1; }
SCHEMA=$(sed -n 's/^SCHEMA_VERSION = \([0-9]*\)/\1/p' "$STAGE/snapshot.py")
# Printed together on purpose: the app's major version is bumped with every
# schema bump, and a build that shipped schema 7 as v3.0.0 is how that drift
# gets noticed too late.
APPV=$(sed -n "s/^const APP_VERSION = '\([^']*\)'.*/\1/p" "$STAGE/index.js")

echo "==> zipping"
rm -f "$ZIP"
# -X drops extended attributes so the same tree zips byte-identically.
( cd "$OUT" && zip -qrX "susan_summary.zip" "susan_summary" -x '*.DS_Store' )

echo
echo "susan_summary  v$APPV  (schema v$SCHEMA)"
ls -l "$STAGE" | awk 'NR>1 {printf "  %8s  %s\n", $5, $9}'
echo
echo "  zip  $ZIP  ($(wc -c < "$ZIP" | tr -d ' ') bytes)"
echo "  unzip into <d3 Projects>/common/plugins/ or <project>/plugins/"

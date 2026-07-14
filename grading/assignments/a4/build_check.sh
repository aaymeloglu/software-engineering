#!/usr/bin/env bash
# A4 build verification: for each materialized submission, npm install + npm run build.
# Captures pass/fail + tail of errors. This is the most objective "the app runs with
# npm install && npm run dev" signal available for a visual React app.
set -u
GRADING="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$GRADING/work/a4-src"
OUT="$GRADING/work/a4-build"
mkdir -p "$OUT"
RESULT="$OUT/results.txt"
: > "$RESULT"

for d in "$SRC"/*/; do
  h=$(basename "$d")
  log="$OUT/$h.log"
  echo "===== $h =====" | tee -a "$RESULT"
  if [ ! -f "$d/package.json" ]; then
    echo "$h: NO package.json" | tee -a "$RESULT"; continue
  fi
  ( cd "$d" || exit 1
    echo "--- npm install ---" > "$log"
    npm install --no-audit --no-fund --loglevel=error >> "$log" 2>&1
    ic=$?
    echo "--- npm run build ---" >> "$log"
    npm run build >> "$log" 2>&1
    bc=$?
    echo "install_exit=$ic build_exit=$bc" >> "$log"
    if [ $ic -ne 0 ]; then echo "$h: INSTALL_FAIL" ; fi
    if [ $bc -eq 0 ]; then echo "$h: BUILD_OK" ; else echo "$h: BUILD_FAIL (tail below)"; tail -n 12 "$log"; fi
  ) | tee -a "$RESULT"
done
echo "ALL DONE" | tee -a "$RESULT"

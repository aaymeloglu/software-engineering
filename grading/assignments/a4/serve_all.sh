#!/usr/bin/env bash
# Build each A4 app and serve its dist via `vite preview` on a dedicated port,
# so they can be screenshotted for the visual-design pass. Ports 4301..4314.
set -u
GRADING="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$GRADING/work/a4-src"
OUT="$GRADING/work/a4-serve"
mkdir -p "$OUT"
MAP="$OUT/ports.txt"; : > "$MAP"
port=4301
for d in "$SRC"/*/; do
  h=$(basename "$d")
  log="$OUT/$h.log"
  ( cd "$d" || exit 1
    [ -d node_modules ] || npm install --no-audit --no-fund --loglevel=error >>"$log" 2>&1
    VITE_API_BASE="http://127.0.0.1:8055" npx vite build >>"$log" 2>&1
    # vite preview serves dist/; --strictPort so we know the port
    nohup npx vite preview --port "$port" --strictPort --host 127.0.0.1 >>"$log" 2>&1 &
    echo "$h $port $!" >>"$MAP"
  )
  port=$((port+1))
done
echo "served:"; cat "$MAP"

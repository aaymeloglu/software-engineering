#!/usr/bin/env bash
# Launch one student's full A4 stack - their A2 backend + their A4 frontend - together.
# Ctrl-C takes both down.
#
#   bash run_student.sh <handle> [backend_port]
#   e.g. bash run_student.sh <handle>
#
# Backend runs on :8001 by default (8000 is held by the Google Workspace MCP); the frontend
# is pointed there via VITE_API_BASE. Open the http://localhost:5173 URL Vite prints.
set -u

HANDLE="${1:-}"
BE_PORT="${2:-8001}"
GRADING="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLASS="$(python3 "$GRADING/harness/config.py" --class-repo)"
if [ -z "$HANDLE" ]; then
  echo "usage: bash run_student.sh <handle> [backend_port]" >&2
  echo "  handles: $(ls "$GRADING/work/a4-src" 2>/dev/null | tr '\n' ' ')" >&2
  exit 1
fi

# The FRONTEND is the A4 submission (bbs-frontend-<handle>). The BACKEND is "their own A2" -
# which a few students put on a SEPARATE branch/PR, leaving the bbs-webserver/ copy on the
# frontend branch stale. Resolve the backend ref:  A4_BE_REF env  >  per-student override  >
# the frontend branch itself.
FE_BR="origin/bbs-frontend-$HANDLE"
git -C "$CLASS" rev-parse --verify -q "$FE_BR" >/dev/null || { echo "ERROR: no A4 branch $FE_BR" >&2; exit 1; }
# Per-student backend override (config.yaml -> overrides.<handle>.a4_backend_ref);
# default to the frontend branch itself.
_ovr="$(python3 "$GRADING/harness/config.py" --override "$HANDLE" a4_backend_ref)"
BE_DEFAULT="${_ovr:-$FE_BR}"
BE_BR="${A4_BE_REF:-$BE_DEFAULT}"

# --- frontend: materialized from the A4 branch ---
FE_DIR="$GRADING/work/a4-src/$HANDLE"
[ -d "$FE_DIR" ] || { echo "ERROR: no materialized A4 frontend at $FE_DIR" >&2; exit 1; }

# --- backend: find THIS student's backend dir on BE_BR (dir name may differ from the
#     handle; main.py may be nested, e.g. <handle>/webserver/main.py). ---
_norm() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[-_]//g'; }
HN="$(_norm "$HANDLE")"
BE_SUB=""
for d in $(git -C "$CLASS" ls-tree -r --name-only "$BE_BR" 2>/dev/null \
            | grep -E 'assignments/bbs-webserver/[^/]+/(.*/)?main\.py$' \
            | sed -E 's#.*/bbs-webserver/([^/]+)/.*#\1#' | sort -u); do
  [ "$(_norm "$d")" = "$HN" ] && BE_SUB="$d" && break
done
[ -z "$BE_SUB" ] && { echo "ERROR: no backend dir for $HANDLE found on $BE_BR" >&2; exit 1; }

# --- materialize backend (re-pull when the source ref changes) ---
BE_DIR="$GRADING/work/a4-backends/$HANDLE"
if [ "$(cat "$BE_DIR/.beref" 2>/dev/null)" != "$BE_BR" ] || [ -z "$(find "$BE_DIR" -name main.py 2>/dev/null)" ]; then
  echo ">> materializing backend $BE_BR:assignments/bbs-webserver/$BE_SUB ..."
  rm -rf "$BE_DIR"; mkdir -p "$BE_DIR"
  git -C "$CLASS" archive "$BE_BR" "assignments/bbs-webserver/$BE_SUB" \
    | tar -x -C "$BE_DIR" --strip-components=3
  echo "$BE_BR" > "$BE_DIR/.beref"
fi
MAIN_PY="$(find "$BE_DIR" -name main.py | head -1)"
[ -n "$MAIN_PY" ] || { echo "ERROR: no main.py in materialized backend" >&2; exit 1; }
RUN_DIR="$(dirname "$MAIN_PY")"

# --- backend venv (cached per student) ---
VENV="$GRADING/work/venvs/a4be/$HANDLE"
if [ ! -x "$VENV/bin/uvicorn" ]; then
  echo ">> setting up backend venv for $HANDLE ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  for reqdir in "$RUN_DIR" "$BE_DIR"; do
    [ -f "$reqdir/requirements.txt" ] && "$VENV/bin/pip" install -q -r "$reqdir/requirements.txt" && break
  done
  # ensure the essentials regardless of what their manifest pinned (multipart/Pillow needed for
  # image uploads even when a student's requirements.txt omits them)
  "$VENV/bin/pip" install -q fastapi "uvicorn[standard]" sqlalchemy pillow python-multipart 2>/dev/null
fi

# --- frontend deps (cached) ---
if [ ! -d "$FE_DIR/node_modules" ]; then
  echo ">> installing frontend deps for $HANDLE ..."
  ( cd "$FE_DIR" && npm install --no-audit --no-fund --loglevel=error )
fi

# --- start backend, tear down on exit ---
BE_PID=""
cleanup() {
  trap - INT TERM EXIT
  [ -n "$BE_PID" ] && kill "$BE_PID" 2>/dev/null
  [ -n "$BE_PID" ] && wait "$BE_PID" 2>/dev/null
  echo ""
  echo "<< stopped $HANDLE (backend + frontend)."
}
trap cleanup INT TERM EXIT

# Wrap the student's app with permissive CORS at launch (their A2 in the class repo lacks the
# CORS they added on their own branch, so a browser on :5173 would be blocked). Inspection only.
SHIM_DIR="$GRADING/assignments/a4"
# Be honest when the shim is masking a missing-CORS submission (grading-relevant: as submitted,
# a browser on :5173 would be CORS-blocked; the app only "works" here because we inject CORS).
if ! find "$RUN_DIR" -name '*.py' 2>/dev/null | xargs grep -liE "corsmiddleware|allow_origins" >/dev/null 2>&1; then
  echo "   !! this backend ships NO CORS of its own — the launcher is INJECTING it so the app is"
  echo "      viewable. As submitted, a browser would be CORS-blocked. (Don't use this run to judge"
  echo "      whether their CORS works.)"
fi
echo ">> backend : $RUN_DIR  ->  http://localhost:$BE_PORT  (ref $BE_BR; CORS-wrapped)"
# Some backends resolve their SQLite path relative to the class-repo layout (e.g. some backends share
# A1's bbs.db two dirs up); in our isolated materialization that dir doesn't exist -> "unable to
# open database file". Pin a writable local DB path (honored by any backend reading BBS_DB_PATH;
# harmless to the rest). Respect a user-provided override.
( cd "$RUN_DIR" && A4_APP="main:app" PYTHONPATH="$RUN_DIR:$SHIM_DIR" \
    BBS_DB_PATH="${BBS_DB_PATH:-$RUN_DIR/bbs.db}" \
    exec "$VENV/bin/uvicorn" cors_shim:app --port "$BE_PORT" ) &
BE_PID=$!

echo ">> frontend: $FE_DIR  ->  Vite will print a localhost URL (usually :5173)"
echo "   (Ctrl-C once to take both down)"
echo ""
( cd "$FE_DIR" && VITE_API_BASE="http://localhost:$BE_PORT" exec npm run dev )

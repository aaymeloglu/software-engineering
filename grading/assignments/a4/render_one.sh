#!/usr/bin/env bash
# Bring up ONE student's real A4-branch backend (seeded) + dev frontend for screenshotting.
#   bash render_one.sh <handle> <be_port> <fe_port>
set -u
H="$1"; BE_PORT="$2"; FE_PORT="$3"
GRADING="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; CLASS="$(python3 "$GRADING/harness/config.py" --class-repo)"

# Free the target ports before launching. We grade one student at a time and
# Vite/uvicorn both bind with --strictPort, so a previous student's still-running
# servers would silently win the port and you'd keep seeing the prior submission.
for P in "$BE_PORT" "$FE_PORT"; do
  pids=$(lsof -ti "tcp:$P" 2>/dev/null) && [ -n "$pids" ] && echo "freeing port $P (killing: $pids)" && kill $pids 2>/dev/null
done
sleep 1
BR="origin/bbs-frontend-$H"; SHIM="$GRADING/assignments/a4"
_norm() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[-_]//g'; }
HN="$(_norm "$H")"

# Locate THIS student's backend entry point. main.py may sit directly under
# bbs-webserver/<handle>/ OR be nested (e.g. bbs-webserver/<handle>/webserver/main.py).
# Match on the handle-dir component; prefer the shallowest main.py if several exist.
BE_PATH=""
while IFS= read -r p; do
  hdir=$(printf '%s' "$p" | sed -E 's#assignments/bbs-webserver/([^/]+)/.*#\1#')
  [ "$(_norm "$hdir")" = "$HN" ] && BE_PATH="${p%/main.py}" && break
done < <(git -C "$CLASS" ls-tree -r --name-only "$BR" | grep -E 'assignments/bbs-webserver/.+/main\.py$' | awk -F/ '{print NF, $0}' | sort -n | cut -d' ' -f2-)

# Fail loudly rather than silently archiving the whole bbs-webserver/ tree (which
# merges every other student's code AND their committed bbs.db into this dir).
if [ -z "$BE_PATH" ]; then
  echo "ERROR: no backend main.py found for handle '$H' on $BR." >&2
  echo "       backends present on the branch:" >&2
  git -C "$CLASS" ls-tree -r --name-only "$BR" | grep -E 'assignments/bbs-webserver/.+/main\.py$' | sed 's/^/         /' >&2
  exit 1
fi

BE="$GRADING/work/a4-backends/$H"; VENV="$GRADING/work/venvs/a4be/$H"; FE="$GRADING/work/a4-src/$H"
# Always clean-extract the exact backend dir — never reuse. A stale tree or DB from a
# prior run is exactly how the wrong code/schema leaks in. strip = depth of BE_PATH.
STRIP=$(printf '%s' "$BE_PATH" | awk -F/ '{print NF}')
rm -rf "$BE"; mkdir -p "$BE"
git -C "$CLASS" archive "$BR" "$BE_PATH" | tar -x -C "$BE" --strip-components="$STRIP"
if [ ! -x "$VENV/bin/uvicorn" ]; then
  python3 -m venv "$VENV"; "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  [ -f "$BE/requirements.txt" ] && "$VENV/bin/pip" install -q -r "$BE/requirements.txt"
  "$VENV/bin/pip" install -q fastapi "uvicorn[standard]" sqlalchemy pillow python-multipart 2>/dev/null
fi
[ -d "$FE/node_modules" ] || ( cd "$FE" && npm install --no-audit --no-fund --loglevel=error )

# start backend (CORS-wrapped) in background
( cd "$BE" && A4_APP="main:app" PYTHONPATH="$BE:$SHIM" nohup "$VENV/bin/uvicorn" cors_shim:app --port "$BE_PORT" >"$GRADING/work/a4-serve/be-$H.log" 2>&1 & echo $! >"$GRADING/work/a4-serve/be-$H.pid" )
# wait for backend
for i in $(seq 1 40); do curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$BE_PORT/posts" 2>/dev/null && break; sleep 0.5; done

# best-effort seed: a few users + posts (ignore shape mismatches)
for u in alice bob carol; do
  curl -s -o /dev/null -X POST "http://127.0.0.1:$BE_PORT/users" -H "Content-Type: application/json" -d "{\"username\":\"$u\"}" 2>/dev/null
done
seed_post() { curl -s -o /dev/null -X POST "http://127.0.0.1:$BE_PORT/posts" -H "Content-Type: application/json" -H "X-Username: $1" -d "{\"message\":\"$2\"}" 2>/dev/null; }
seed_post alice "first post on the new feed - looks clean"
seed_post bob "anyone else getting CORS errors? fixed with the middleware snippet"
seed_post carol "the mobile layout actually holds up at 320px, nice"
seed_post alice "optimistic delete + rollback is so satisfying when it works"
seed_post bob "dark mode that respects prefers-color-scheme >>>"
seed_post carol "load more vs infinite scroll - went with load more"

# start frontend dev pointed at the real backend.
# Bind to localhost (not 127.0.0.1): students are taught to whitelist
# http://localhost:5173 in their backend CORS config, and the browser treats
# localhost and 127.0.0.1 as distinct origins. Pass FE_PORT=5173 so the served
# origin matches what a correctly-configured submission allows.
( cd "$FE" && VITE_API_BASE="http://localhost:$BE_PORT" nohup npm run dev -- --port "$FE_PORT" --strictPort --host localhost >"$GRADING/work/a4-serve/fe-$H.log" 2>&1 & echo $! >"$GRADING/work/a4-serve/fe-$H.pid" )
for i in $(seq 1 40); do curl -s -o /dev/null --max-time 1 "http://localhost:$FE_PORT/" 2>/dev/null && break; sleep 0.5; done
echo "UP: $H  backend=:$BE_PORT (${BE_PATH#assignments/bbs-webserver/})  frontend=http://localhost:$FE_PORT"
echo "posts now in backend: $(curl -s "http://127.0.0.1:$BE_PORT/posts" 2>/dev/null | head -c 120)"

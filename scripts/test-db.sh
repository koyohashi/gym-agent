#!/usr/bin/env bash
# Local Supabase for tests and development: Postgres + the REST API in Docker, loaded with
# supabase/migrations and supabase/seed.sql. Production is never touched.
#
#   scripts/test-db.sh              # start, reset to migrations + seed, run pytest
#   scripts/test-db.sh -k pr        # same, passing arguments to pytest
#   scripts/test-db.sh app          # start, reset, run the app against the local database
#   scripts/test-db.sh stop         # stop the containers
#
# Needs Docker running and the Supabase CLI. The first start downloads the images.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

command -v supabase >/dev/null || fail "the Supabase CLI is not installed (brew install supabase/tap/supabase)."
docker info >/dev/null 2>&1 || fail "Docker is not running."

if [ "${1:-}" = "stop" ]; then
  exec supabase stop
fi

# Only Postgres, the REST API and auth (which issues the keys) are needed; skipping the rest keeps startup fast.
quiet() { local out; out="$("$@" 2>&1)" || { echo "$out" >&2; fail "'$*' failed."; }; }
quiet supabase start -x realtime,storage-api,imgproxy,studio,mailpit,postgres-meta,edge-runtime,logflare,vector,supavisor
quiet supabase db reset
echo "Local Supabase is up and reset (migrations + seed)."

case "${1:-}" in
  app)
    STATUS="$(supabase status -o env 2>/dev/null)"
    value() { echo "$STATUS" | sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p"; }
    # Exported values win over .env (load_dotenv doesn't override), so the app uses the local stack.
    SUPABASE_URL="$(value API_URL)" SUPABASE_SERVICE_KEY="$(value SERVICE_ROLE_KEY)" APP_USER_ID="" \
      exec "$PY" app.py
    ;;
  *)
    [ "${1:-}" = "pytest" ] && shift
    exec "$ROOT/.venv/bin/pytest" "$@"
    ;;
esac

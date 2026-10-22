#!/usr/bin/env bash
# Deploy: push the current commit to GitHub, sync it to the Hugging Face Spaces, and verify each one.
#
#   scripts/deploy.sh            # koyohashi/gym-agent-personal (private, the real app) and koyohashi/gym-agent (public template)
#   HF_SPACES="you/gym-agent" scripts/deploy.sh
#
# A configured Space must answer 401 (login required). An unconfigured one, like the public template,
# must show the setup page instead. Private Spaces are checked with your Hugging Face token.
#
# Refuses to run with uncommitted changes, so the Space always matches a GitHub commit.
set -euo pipefail

SPACES="${HF_SPACES:-koyohashi/gym-agent-personal koyohashi/gym-agent}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
HF="$(command -v hf || echo "$HOME/.local/bin/hf")"

step() { printf '\n==> %s\n' "$1"; }
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

step "Checking the working tree"
if [ -n "$(git status --porcelain)" ]; then
  git status --short
  fail "uncommitted changes. Commit them (or stash them) first."
fi
SHA="$(git rev-parse --short HEAD)"
echo "Deploying commit $SHA: $(git log -1 --format=%s)"

step "Import check (the app builds with placeholder settings)"
env -u SPACE_ID SUPABASE_URL=http://127.0.0.1:54321 SUPABASE_SERVICE_KEY=check MODEL_BACKEND=ollama MODEL_ID=check GRADIO_USER=check GRADIO_PASSWORD=check \
  "$PY" -c "import app" >/dev/null || fail "the app does not import; not deploying."
echo "ok"

step "Pushing to GitHub"
git push
ORIGIN="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"

# Upload one Space, wait for it to start, and check its login. (Body unindented so the heredoc stays at column 0.)
deploy_space() {
SPACE="$1"
step "Uploading to the Space $SPACE"
"$HF" upload "$SPACE" . --repo-type space \
  --exclude ".venv/**" --exclude "__pycache__/**" --exclude "**/__pycache__/**" --exclude ".env" \
  --exclude ".git/**" --exclude ".pytest_cache/**" --exclude "supabase/.temp/**" --exclude "supabase/.branches/**" --exclude ".claude/**" \
  --commit-message "Sync with github.com/$ORIGIN@$SHA"

step "Waiting for the Space to restart"
"$PY" -I - "$SPACE" <<'EOF'
import sys, time
from huggingface_hub import HfApi

space = sys.argv[1]
api = HfApi()
time.sleep(20)  # give the Space time to pick up the new commit
deadline = time.time() + 600
while True:
    stage = api.space_info(space).runtime.stage
    if stage not in ("BUILDING", "APP_STARTING", "RUNNING_BUILDING", "RUNNING_APP_STARTING"):
        break
    if time.time() > deadline:
        sys.exit(f"still {stage} after 10 minutes")
    time.sleep(10)
print(stage)
if stage != "RUNNING":
    sys.exit(f"Space is {stage}; read the logs with: hf spaces logs {space} --tail 100")
EOF

step "Checking that $SPACE requires login (or shows the setup page)"
HOST="$(echo "$SPACE" | tr '[:upper:]' '[:lower:]' | tr '/_.' '---')"
URLS="$URLS
App:    https://$HOST.hf.space"
HF_AUTH=()
if "$PY" -I -c "import sys; from huggingface_hub import HfApi; sys.exit(0 if HfApi().space_info(sys.argv[1]).private else 1)" "$SPACE"; then
  HF_AUTH=(-H "Authorization: Bearer $("$PY" -I -c "from huggingface_hub import get_token; print(get_token())")")
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST.hf.space/config")"
  echo "private Space, /config without a Hugging Face login: $CODE"
  [ "$CODE" = "404" ] || fail "expected 404 (hidden from anyone not logged in to Hugging Face), got $CODE."
fi
CONFIG="$(curl -s ${HF_AUTH[@]+"${HF_AUTH[@]}"} -w '\n%{http_code}' "https://$HOST.hf.space/config")"
CODE="$(tail -n1 <<<"$CONFIG")"
echo "/config without app login: $CODE"
if [ "$CODE" = "200" ] && grep -q "Gym Agent needs setup" <<<"$CONFIG"; then
  echo "not configured: showing the setup page"
else
  [ "$CODE" = "401" ] || fail "expected 401 (login required) or the setup page, got $CODE."
fi
}

URLS=""
for SPACE in $SPACES; do
  deploy_space "$SPACE"
done

step "Done"
echo "GitHub: https://github.com/$ORIGIN/commit/$SHA"
echo "Spaces: $SPACES"
echo "${URLS#?}"

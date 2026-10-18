#!/usr/bin/env bash
# Deploy: push the current commit to GitHub, sync it to the Hugging Face Space, and verify the Space.
#
#   scripts/deploy.sh            # Space defaults to koyohashi/gym-agent
#   HF_SPACE=you/gym-agent scripts/deploy.sh
#
# Refuses to run with uncommitted changes, so the Space always matches a GitHub commit.
set -euo pipefail

SPACE="${HF_SPACE:-koyohashi/gym-agent}"
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
env -u SPACE_ID DB_BACKEND=memory MODEL_BACKEND=ollama MODEL_ID=check GRADIO_USER=check GRADIO_PASSWORD=check \
  "$PY" -c "import app" >/dev/null || fail "the app does not import; not deploying."
echo "ok"

step "Pushing to GitHub"
git push
ORIGIN="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"

step "Uploading to the Space $SPACE"
"$HF" upload "$SPACE" . --repo-type space \
  --exclude ".venv/**" --exclude "__pycache__/**" --exclude "**/__pycache__/**" --exclude ".env" \
  --exclude ".git/**" --exclude ".pytest_cache/**" --exclude "supabase/.temp/**" --exclude ".claude/**" \
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

step "Checking that the app still requires login"
HOST="$(echo "$SPACE" | tr '[:upper:]' '[:lower:]' | tr '/_.' '---')"
CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST.hf.space/config")"
echo "/config without login: $CODE"
[ "$CODE" = "401" ] || fail "expected 401 (login required), got $CODE."

step "Done"
echo "GitHub: https://github.com/$ORIGIN/commit/$SHA"
echo "Space:  https://huggingface.co/spaces/$SPACE"
echo "App:    https://$HOST.hf.space"

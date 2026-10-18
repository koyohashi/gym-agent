---
name: deploy
description: Deploy the gym agent - commit the changes, push to GitHub, sync the Hugging Face Space, and verify it is running and still requires login. Use when the user asks to deploy, ship, release, push to the Space, or sync GitHub and the Space.
---

# Deploy

GitHub is the main copy; the Space gets the same commit. `scripts/deploy.sh` does the push, upload, and checks. Your job is the commit before it and the report after it.

## 1. Review what will ship

Run `git status --short` and `git diff`.

- Changes you made in this session: commit them.
- Changes you did not make (the user's, or another session's): list them for the user and ask whether to include them before committing. Never fold someone else's work into your commit unasked.
- Never commit `.env` or anything holding a key or token. `.gitignore` covers `.env`; check new files anyway.

## 2. Commit

Commit with a message that says what changed and why (subject line under ~70 characters, body if useful), ending with the attribution lines the session requires. One commit per logical change is better than one commit for everything.

## 3. Run the script

```bash
scripts/deploy.sh
```

Set `HF_SPACE=<owner>/<space>` to deploy somewhere other than `koyohashi/gym-agent`. The script:

1. Refuses to run with uncommitted changes.
2. Checks that the app imports with placeholder settings.
3. Pushes to GitHub.
4. Uploads to the Space (excluding `.venv`, `__pycache__`, `.env`, `.git`, `.pytest_cache`, `supabase/.temp`, `.claude`), with the commit message `Sync with github.com/<repo>@<sha>`.
5. Waits until the Space is `RUNNING` (up to 10 minutes).
6. Checks that `/config` returns 401, so the login still protects the app.

It needs the `hf` CLI logged in (`hf auth whoami`), `gh`/git push access, and the project's `.venv`.

## 4. Report

Tell the user the commit SHA and subject, that GitHub and the Space are updated, and the check results. If a step failed, say which one, then:

- Space not `RUNNING`: read `hf spaces logs <space> --tail 100`, find the first error, and report it.
- `/config` not 401: stop and tell the user. The app may be reachable without the password.

Pushing to GitHub and the Space is visible to everyone who can see them; deploy only when the user asked for it.

---
name: deploy
description: Deploy the gym agent - commit the changes, push to GitHub, sync the Hugging Face Space, and verify each is running and not open to strangers. Use when the user asks to deploy, ship, release, push to the Space, or sync GitHub and the Space.
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

By default it deploys to `koyohashi/gym-agent` (public, behind the owner-only Hugging Face sign-in in `signin.py`). Set `HF_SPACES="<owner>/<space> ..."` to deploy elsewhere. The script:

1. Refuses to run with uncommitted changes.
2. Checks that the app imports with placeholder settings.
3. Pushes to GitHub.
4. For each Space: uploads (excluding `.venv`, `__pycache__`, `.env`, `.git`, `.pytest_cache`, `supabase/.temp`, `supabase/.branches`, `.claude`) with the commit message `Sync with github.com/<repo>@<sha>`, then waits until it is `RUNNING` (up to 10 minutes).
5. Checks who can open each Space: the sign-in page loads, and without signing in the app's page redirects to it while `/app/config`, the API, and the app's files return 401. A private Space must also return 404 without a Hugging Face login. A Space with no config shows the setup page instead.

It needs the `hf` CLI logged in (`hf auth whoami`), `gh`/git push access, and the project's `.venv`.

## 4. Report

Tell the user the commit SHA and subject, that GitHub and the Space are updated, and the check results. If a step failed, say which one, then:

- Space not `RUNNING`: read `hf spaces logs <space> --tail 100`, find the first error, and report it.
- Access check failed: stop and tell the user. If the app answers without a sign-in, anyone can use it; make the Space private right away (`hf repos settings`/the Space settings) until it's fixed.

Pushing to GitHub and the Space is visible to everyone who can see them; deploy only when the user asked for it.

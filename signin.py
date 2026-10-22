"""Owner-only "Sign in with Hugging Face" in front of the whole app, for running on a Space.

The Gradio app is mounted at /app, and every request under it (page, files, API) must carry a Hugging Face
sign-in belonging to the Space's owner. Only the landing page, the sign-in routes and the PWA manifest are
open. The owner is matched by their permanent account id, not their username, so a renamed account's old
name can't be claimed by someone else. If the owner's id can't be looked up, nobody gets in.
"""

import html
import json
import os
import time
import urllib.request

import fastapi
import gradio as gr
import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from gradio.oauth import attach_oauth

APP_PATH = "/app"
# Open without signing in: harmless metadata the home-screen icon needs (fetched without cookies).
PUBLIC_APP_PATHS = (f"{APP_PATH}/manifest.json", f"{APP_PATH}/pwa_icon", f"{APP_PATH}/static/img/")
DUPLICATE_URL = "https://huggingface.co/spaces/{space_id}?duplicate=true"

_owner_id: str | None = None


def owner_id() -> str | None:
    """The Space owner's permanent Hugging Face account id, looked up once (retried until it works)."""
    global _owner_id
    if _owner_id is None:
        owner = os.environ.get("SPACE_AUTHOR_NAME", "")
        try:
            with urllib.request.urlopen(f"https://huggingface.co/api/users/{owner}/overview", timeout=10) as r:
                _owner_id = json.load(r)["_id"]
        except Exception as e:
            print(f"signin: could not look up the owner '{owner}' ({e}); refusing everyone until it works")
    return _owner_id


def signed_in_user(request: fastapi.Request) -> dict | None:
    """The Hugging Face account this browser signed in with, if the sign-in hasn't expired."""
    info = request.session.get("oauth_info") or {}
    if info.get("expires_at", 0) < time.time():
        return None
    return info.get("userinfo")


def is_owner(request: fastapi.Request) -> bool:
    user = signed_in_user(request)
    return bool(user) and user.get("sub") is not None and user.get("sub") == owner_id()


def _landing(body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gym Agent</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
         background: #1F1E1D; color: #ECEAE6; font-family: -apple-system, system-ui, sans-serif; }}
  main {{ max-width: 22rem; padding: 2rem; text-align: center; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 1.5rem; }}
  p {{ color: #9C9A94; line-height: 1.5; }}
  a.button {{ display: inline-block; padding: 0.8rem 1.4rem; border-radius: 0.75rem; background: #D97757;
              color: #1F1E1D; font-weight: 600; text-decoration: none; }}
  a {{ color: #D97757; }}
</style></head>
<body><main><h1>🏋️ Gym Agent</h1>{body}</main></body></html>""")


def build_app(demo: gr.Blocks, **launch_kwargs) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    space_id = os.environ.get("SPACE_ID", "")
    owner = html.escape(os.environ.get("SPACE_AUTHOR_NAME", "the Space's owner"))
    duplicate = f'<p>Want your own? <a href="{DUPLICATE_URL.format(space_id=space_id)}">Duplicate this Space</a>.</p>'

    @app.get("/")
    def landing(request: fastapi.Request):
        if is_owner(request):
            return RedirectResponse(f"{APP_PATH}/")
        user = signed_in_user(request)
        if user:
            name = html.escape(user.get("preferred_username", "another account"))
            return _landing(f"<p>You're signed in as <b>{name}</b>, but this app belongs to <b>{owner}</b>.</p>"
                            f'<p><a href="/logout">Sign out</a></p>{duplicate}')
        return _landing('<a class="button" href="/login/huggingface">Sign in with Hugging Face</a>'
                        f"<p>Only {owner} can use this copy.</p>{duplicate}")

    # Added before attach_oauth's session middleware, so it runs inside it and can read the sign-in.
    @app.middleware("http")
    async def owner_only(request: fastapi.Request, call_next):
        path = request.url.path
        if path == APP_PATH or path.startswith(APP_PATH + "/"):
            public = path.startswith(PUBLIC_APP_PATHS) and ".." not in path
            if not public and not is_owner(request):
                if request.method == "GET" and path.rstrip("/") == APP_PATH:
                    return RedirectResponse("/")
                return JSONResponse({"detail": "Sign in as the Space's owner."}, status_code=401)
        return await call_next(request)

    attach_oauth(app)  # /login/huggingface, /login/callback, /logout, and the signed session cookie
    return gr.mount_gradio_app(app, demo, path=APP_PATH, **launch_kwargs)


def serve(demo: gr.Blocks, **launch_kwargs) -> None:
    uvicorn.run(build_app(demo, **launch_kwargs), host=os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0"),
                port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")))

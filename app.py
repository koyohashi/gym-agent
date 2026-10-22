"""Entrypoint: checks config, builds the agent, launches the UI."""

import os
import sys
import urllib.error
import urllib.request

try:
    import spaces  # preinstalled on Spaces; ZeroGPU hardware requires one decorated function
except ImportError:
    spaces = None

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["MODEL_BACKEND", "MODEL_ID", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
LOGIN = ["GRADIO_USER", "GRADIO_PASSWORD"]
SETUP_URL = "https://github.com/koyohashi/gym-agent#deploy-your-own"
SETUP_HEADING = "Gym Agent needs setup"


def is_public_space(space_id: str) -> bool:
    """Whether anyone can open this Space. A private Space's API page needs a login; unsure counts as public."""
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/spaces/{space_id}", timeout=10):
            return True
    except urllib.error.HTTPError as e:
        return e.code not in (401, 404)
    except OSError:
        return True


def missing_env() -> list[str]:
    """Required settings that aren't set. The app login is optional, except on a public Space."""
    required = list(REQUIRED)
    if os.environ.get("MODEL_BACKEND") == "hf":
        required.append("HF_TOKEN")
    space_id = os.environ.get("SPACE_ID")
    if space_id and not all(os.environ.get(k) for k in LOGIN) and is_public_space(space_id):
        required += LOGIN
    return [k for k in required if not os.environ.get(k)]


def setup_page(missing: list[str]):
    """Shown on a Space that isn't configured yet (the public template, or a fresh duplicate) instead of crashing."""
    import gradio as gr

    names = "\n".join(f"- `{k}`" for k in missing)
    with gr.Blocks(title="Gym Agent setup") as page:
        gr.Markdown(f"## {SETUP_HEADING}\n\nThis Space is missing:\n\n{names}\n\n"
                    "Duplicate this Space (⋮ menu → **Duplicate this Space**), add these under "
                    "Settings → Variables and secrets, and restart it. A public Space needs the "
                    "`GRADIO_USER` / `GRADIO_PASSWORD` login; a private one can skip it. "
                    f"Full guide: [Deploy your own]({SETUP_URL}).")
    return page


if spaces is not None:
    @spaces.GPU
    def _unused_gpu_hook():
        """No-op: the model is hosted, but ZeroGPU Spaces need one GPU-decorated function to start."""


missing = missing_env()
if missing and not os.environ.get("SPACE_ID"):
    sys.exit(f"Missing required environment variables: {', '.join(missing)}. "
             "Set them as Space secrets, or in .env for local development.")

if missing:
    demo = setup_page(missing)
else:
    from agent import build_agent, build_model, setup_tracing
    from ui import build_ui, launch

    setup_tracing()
    model = build_model()
    demo = build_ui(lambda: build_agent(model=model))

if __name__ == "__main__":
    if missing:
        demo.launch()
    else:
        launch(demo, os.environ.get("GRADIO_USER"), os.environ.get("GRADIO_PASSWORD"))

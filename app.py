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
    required = list(REQUIRED)
    if os.environ.get("MODEL_BACKEND") == "hf":
        required.append("HF_TOKEN")
    return [k for k in required if not os.environ.get(k)]


def setup_page(missing: list[str], public: bool):
    """Shown instead of the app on a Space that isn't configured (the template, or a fresh duplicate), or is public.
    The app has no login of its own, so on a public Space anyone could read the data and spend the model budget."""
    import gradio as gr

    steps = []
    if public:
        steps.append("Make this Space **private** (Settings → Change Space visibility). The app has no login of its "
                     "own; a private Space is what keeps everyone else out.")
    if missing:
        names = ", ".join(f"`{k}`" for k in missing)
        steps.append(f"Add {names} under Settings → Variables and secrets.")
    todo = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    with gr.Blocks(title="Gym Agent setup") as page:
        gr.Markdown(f"## {SETUP_HEADING}\n\nDuplicate this Space (⋮ menu → **Duplicate this Space**), then:\n\n"
                    f"{todo}\n{len(steps) + 1}. Restart it.\n\nFull guide: [Deploy your own]({SETUP_URL}).")
    return page


if spaces is not None:
    @spaces.GPU
    def _unused_gpu_hook():
        """No-op: the model is hosted, but ZeroGPU Spaces need one GPU-decorated function to start."""


missing = missing_env()
space_id = os.environ.get("SPACE_ID")
if missing and not space_id:
    sys.exit(f"Missing required environment variables: {', '.join(missing)}. "
             "Set them as Space secrets, or in .env for local development.")
public = bool(space_id) and is_public_space(space_id)

if missing or public:
    demo = setup_page(missing, public)
else:
    from agent import build_agent, build_model, setup_tracing
    from ui import build_ui, launch

    setup_tracing()
    model = build_model()
    demo = build_ui(lambda: build_agent(model=model))

if __name__ == "__main__":
    if missing or public:
        demo.launch()
    else:
        launch(demo)

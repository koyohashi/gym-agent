"""Entrypoint: checks config, builds the agent, launches the UI."""

import os
import sys

try:
    import spaces  # preinstalled on Spaces; ZeroGPU hardware requires one decorated function
except ImportError:
    spaces = None

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["MODEL_BACKEND", "MODEL_ID", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
SETUP_URL = "https://github.com/koyohashi/gym-agent#deploy-your-own"
SETUP_HEADING = "Gym Agent needs setup"


def missing_env() -> list[str]:
    required = list(REQUIRED)
    if os.environ.get("MODEL_BACKEND") == "hf":
        required.append("HF_TOKEN")
    return [k for k in required if not os.environ.get(k)]


def setup_page(missing: list[str]):
    """Shown on a Space that isn't configured yet (a fresh duplicate) instead of crashing. It holds no data."""
    import gradio as gr

    names = ", ".join(f"`{k}`" for k in missing)
    with gr.Blocks(title="Gym Agent setup") as page:
        gr.Markdown(f"## {SETUP_HEADING}\n\nAdd {names} under Settings → Variables and secrets, then restart "
                    f"this Space.\n\nFull guide: [Deploy your own]({SETUP_URL}).")
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
        launch(demo)

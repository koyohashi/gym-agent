"""Entrypoint: checks config, builds the agent, launches the UI."""

import os
import sys

try:
    import spaces  # preinstalled on Spaces; ZeroGPU hardware requires one decorated function
except ImportError:
    spaces = None

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["MODEL_BACKEND", "MODEL_ID", "GRADIO_USER", "GRADIO_PASSWORD"]
REQUIRED_SUPABASE = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"]


def check_env() -> None:
    required = list(REQUIRED)
    if os.environ.get("DB_BACKEND", "supabase") == "memory":
        if os.environ.get("SPACE_ID"):
            sys.exit("DB_BACKEND=memory is for local development only; sets would be lost on restart.")
    else:
        required += REQUIRED_SUPABASE
    if os.environ.get("MODEL_BACKEND") == "hf":
        required.append("HF_TOKEN")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing required environment variables: {', '.join(missing)}. "
                 "Set them as Space secrets, or in .env for local development.")


if spaces is not None:
    @spaces.GPU
    def _unused_gpu_hook():
        """No-op: the model is hosted, but ZeroGPU Spaces need one GPU-decorated function to start."""


check_env()

from agent import build_agent, build_model  # noqa: E402
from ui import build_ui, launch  # noqa: E402

model = build_model()
demo = build_ui(lambda: build_agent(model=model))

if __name__ == "__main__":
    launch(demo, os.environ["GRADIO_USER"], os.environ["GRADIO_PASSWORD"])

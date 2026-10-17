"""Model config and agent construction, shared by app.py, tests, and the eval runner."""

import os
from pathlib import Path

import yaml
from smolagents import InferenceClientModel, LiteLLMModel, ToolCallingAgent
from smolagents.memory import TaskStep

from tools import ALL_TOOLS

PROMPTS_PATH = Path(__file__).parent / "prompts.yaml"
MAX_STEPS = 10
MAX_TURNS_IN_MEMORY = 6  # older turns are dropped; the database, not memory, is the source of truth


def build_model(backend: str | None = None, model_id: str | None = None):
    """Build the model from MODEL_BACKEND / MODEL_ID (or the given overrides)."""
    backend = backend or os.environ.get("MODEL_BACKEND", "ollama")
    model_id = model_id or os.environ.get("MODEL_ID", "qwen2:7b")
    if backend == "ollama":
        return LiteLLMModel(
            model_id=f"ollama_chat/{model_id}",
            api_base=os.environ.get("OLLAMA_API_BASE", "http://localhost:11434"),
            num_ctx=8192,
            temperature=0,
        )
    if backend == "hf":
        return InferenceClientModel(
            model_id=model_id,
            provider=os.environ.get("HF_PROVIDER") or None,
            token=os.environ.get("HF_TOKEN"),
            temperature=0,
        )
    if backend == "litellm":
        return LiteLLMModel(model_id=model_id, temperature=0)
    raise ValueError(f"Unknown MODEL_BACKEND '{backend}' (expected ollama, hf, or litellm)")


def load_prompts() -> tuple[dict, str]:
    with open(PROMPTS_PATH) as f:
        templates = yaml.safe_load(f)
    instructions = templates.pop("instructions")
    return templates, instructions


def build_agent(model=None, verbosity_level: int = 1) -> ToolCallingAgent:
    templates, instructions = load_prompts()
    return ToolCallingAgent(
        tools=ALL_TOOLS,
        model=model or build_model(),
        prompt_templates=templates,
        instructions=instructions,
        max_steps=MAX_STEPS,
        verbosity_level=verbosity_level,
    )


def chat(agent: ToolCallingAgent, message: str) -> str:
    """Run one user turn, keeping recent turns in memory so clarifying questions work."""
    steps = agent.memory.steps
    task_starts = [i for i, s in enumerate(steps) if isinstance(s, TaskStep)]
    if len(task_starts) >= MAX_TURNS_IN_MEMORY:
        del steps[: task_starts[-(MAX_TURNS_IN_MEMORY - 1)]]
    return str(agent.run(message, reset=False))

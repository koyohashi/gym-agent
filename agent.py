"""Model config and agent construction, shared by app.py, tests, and the eval runner."""

import os
from collections.abc import Iterator
from pathlib import Path

import yaml
from smolagents import InferenceClientModel, LiteLLMModel, ToolCallingAgent
from smolagents.memory import ActionStep, FinalAnswerStep, TaskStep

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


def _trim_memory(agent: ToolCallingAgent) -> None:
    steps = agent.memory.steps
    task_starts = [i for i, s in enumerate(steps) if isinstance(s, TaskStep)]
    if len(task_starts) >= MAX_TURNS_IN_MEMORY:
        del steps[: task_starts[-(MAX_TURNS_IN_MEMORY - 1)]]


def _format_call(call) -> str:
    args = call.arguments if isinstance(call.arguments, dict) else {"": call.arguments}
    return f"{call.name}(" + ", ".join(f"{k}={v!r}" if k else repr(v) for k, v in args.items()) + ")"


def chat_steps(agent: ToolCallingAgent, message: str) -> Iterator[dict]:
    """Run one user turn, yielding what the agent does as it happens.

    Yields {"kind": "step", "title", "body"} per tool-calling step, {"kind": "error", "title", "body"} per failed
    step, and finally {"kind": "answer", "body"}. Recent turns stay in memory so clarifying questions work.
    """
    _trim_memory(agent)
    for event in agent.run(message, stream=True, reset=False):
        if isinstance(event, ActionStep):
            calls = [c for c in (event.tool_calls or []) if c.name != "final_answer"]
            thought = (event.model_output or "").strip() if isinstance(event.model_output, str) else ""
            if calls:
                body = (f"{thought}\n\n" if thought else "") + (event.observations or "").strip()
                yield {"kind": "step", "title": "🛠️ " + "; ".join(_format_call(c) for c in calls), "body": body}
            if event.error:
                yield {"kind": "error", "title": "💥 Error", "body": (f"{thought}\n\n" if thought else "") + str(event.error)}
        elif isinstance(event, FinalAnswerStep):
            yield {"kind": "answer", "body": str(event.output)}


def chat(agent: ToolCallingAgent, message: str) -> str:
    """Run one user turn and return only the final reply."""
    answer = ""
    for step in chat_steps(agent, message):
        if step["kind"] == "answer":
            answer = step["body"]
    return answer

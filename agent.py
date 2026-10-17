"""Model config and agent construction, shared by app.py, tests, and the eval runner."""

import os
import re
from collections.abc import Iterator
from pathlib import Path

import yaml
from smolagents import CodeAgent, InferenceClientModel, LiteLLMModel
from smolagents.memory import ActionStep, FinalAnswerStep, TaskStep

from tools import ALL_TOOLS, today_line

PROMPTS_PATH = Path(__file__).parent / "prompts.yaml"
MAX_STEPS = 10
MAX_TURNS_IN_MEMORY = 6  # older turns are dropped; the database, not memory, is the source of truth
MAX_TITLE_CHARS = 120


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


def build_agent(model=None, verbosity_level: int = 1) -> CodeAgent:
    templates, instructions = load_prompts()
    return CodeAgent(
        tools=ALL_TOOLS,
        model=model or build_model(),
        prompt_templates=templates,
        instructions=instructions,
        additional_authorized_imports=["datetime"],
        max_steps=MAX_STEPS,
        verbosity_level=verbosity_level,
    )


def _trim_memory(agent: CodeAgent) -> None:
    steps = agent.memory.steps
    task_starts = [i for i, s in enumerate(steps) if isinstance(s, TaskStep)]
    if len(task_starts) >= MAX_TURNS_IN_MEMORY:
        del steps[: task_starts[-(MAX_TURNS_IN_MEMORY - 1)]]


def _thought(model_output) -> str:
    """The text before the code block, without the 'Thought:' label."""
    if not isinstance(model_output, str):
        return ""
    text = re.split(r"<code>|```", model_output, maxsplit=1)[0]
    return re.sub(r"^\s*Thought:\s*", "", text).strip()


def chat_steps(agent: CodeAgent, message: str) -> Iterator[dict]:
    """Run one user turn, yielding what the agent does as it happens.

    Yields {"kind": "step", "title", "body"} per step (title is the model's thought, body the code it ran and
    what it printed), {"kind": "error", "title", "body"} per failed step, and finally {"kind": "answer", "body"}.
    Recent turns stay in memory so clarifying questions work.
    """
    _trim_memory(agent)
    for event in agent.run(f"{today_line()}\n{message}", stream=True, reset=False):
        if isinstance(event, ActionStep):
            thought = _thought(event.model_output)
            code = (event.code_action or "").strip()
            only_answer = code.startswith("final_answer(") and code.count("\n") == 0
            if code and not only_answer:
                title = "🧠 " + (thought[:MAX_TITLE_CHARS] + ("…" if len(thought) > MAX_TITLE_CHARS else "")
                                if thought else "Running code")
                output = (event.observations or "").strip()
                yield {"kind": "step", "title": title,
                       "body": f"```python\n{code}\n```" + (f"\n{output}" if output else "")}
            if event.error:
                yield {"kind": "error", "title": "💥 Error",
                       "body": (f"{thought}\n\n" if thought else "") + str(event.error)}
        elif isinstance(event, FinalAnswerStep):
            yield {"kind": "answer", "body": str(event.output)}


def chat(agent: CodeAgent, message: str) -> str:
    """Run one user turn and return only the final reply."""
    answer = ""
    for step in chat_steps(agent, message):
        if step["kind"] == "answer":
            answer = step["body"]
    return answer

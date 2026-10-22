"""Model config and agent construction, shared by app.py, tests, and the eval runner."""

import os
import queue
import re
import threading
from collections.abc import Iterator
from contextlib import nullcontext
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


def setup_tracing() -> bool:
    """Send agent traces to Langfuse when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set. Returns whether it's on."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return False
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "production" if os.environ.get("SPACE_ID") else "development")
    from langfuse import get_client
    from openinference.instrumentation.smolagents import SmolagentsInstrumentor

    get_client()  # reads LANGFUSE_* and registers the OpenTelemetry exporter the instrumentor writes to
    SmolagentsInstrumentor().instrument()
    return True


def _trace_attributes(session_id: str | None):
    """Groups a turn's trace under its chat session in Langfuse (no-op when tracing is off)."""
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return nullcontext()
    from langfuse import propagate_attributes

    return propagate_attributes(session_id=session_id, user_id=os.environ.get("GRADIO_USER"), trace_name="chat turn")


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


_DONE = object()


def _run_events(agent: CodeAgent, task: str, session_id: str | None) -> Iterator:
    """agent.run's stream, produced on one thread so the turn's trace context holds for every step.
    (Gradio advances generators from changing worker threads, which would split a trace into pieces.)"""
    events: queue.Queue = queue.Queue()

    def run():
        try:
            with _trace_attributes(session_id):
                for event in agent.run(task, stream=True, reset=False):
                    events.put(event)
        except Exception as e:
            events.put(e)
        finally:
            events.put(_DONE)

    threading.Thread(target=run, daemon=True).start()
    while (event := events.get()) is not _DONE:
        if isinstance(event, Exception):
            raise event
        yield event


def chat_steps(agent: CodeAgent, message: str, session_id: str | None = None) -> Iterator[dict]:
    """Run one user turn, yielding what the agent does as it happens.

    Yields {"kind": "step", "title", "body"} per step (title is the model's thought, body the code it ran and
    what it printed), {"kind": "error", "title", "body"} per failed step, and finally {"kind": "answer", "body"}.
    Recent turns stay in memory so clarifying questions work. session_id groups the turn's trace in Langfuse.
    """
    _trim_memory(agent)
    for event in _run_events(agent, f"{today_line()}\n{message}", session_id):
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

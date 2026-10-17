"""Model config and agent construction, shared by app.py, tests, and the eval runner."""

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import yaml
from smolagents import InferenceClientModel, LiteLLMModel, ToolCallingAgent
from smolagents.memory import ActionStep, FinalAnswerStep, TaskStep
from smolagents.models import ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole, parse_json_if_needed

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


TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
BROKEN_MARKUP = re.compile(r"</?tool_call>|<\|im_(start|end)\|>")


def _tool_call(name: str, arguments) -> ChatMessageToolCall:
    return ChatMessageToolCall(id=str(uuid.uuid4()), type="function",
                               function=ChatMessageToolCallFunction(name=name, arguments=arguments))


def lenient_tool_call_parsing(model):
    """Make text-only model replies usable instead of failing the step.

    smolagents calls model.parse_tool_calls only when the provider returned no structured tool call. Then:
    1. Qwen-style <tool_call>{...}</tool_call> markup in the text is parsed as tool calls.
    2. Text containing a JSON blob goes to smolagents' own parser, as before.
    3. Plain prose is the model answering the user, so it becomes a final_answer call.
    4. Empty text or broken markup still raises, so smolagents retries the step.
    """
    if getattr(model, "_lenient_parsing", False):  # the UI shares one model across agents
        return model
    original = model.parse_tool_calls

    def parse_tool_calls(message):
        text = message.content if isinstance(message.content, str) else ""
        message.role = MessageRole.ASSISTANT
        blocks = TOOL_CALL_TAG.findall(text)
        if blocks:
            calls = []
            for block in blocks:
                data = json.loads(block, strict=False)
                calls.append(_tool_call(data["name"], parse_json_if_needed(data.get("arguments", {}))))
            message.tool_calls = calls
            return message
        if "{" in text:
            return original(message)
        prose = text.strip()
        if not prose or BROKEN_MARKUP.search(prose):
            raise ValueError("The output contained no tool call. Reply to the user by calling final_answer.")
        message.tool_calls = [_tool_call("final_answer", {"answer": prose})]
        return message

    model.parse_tool_calls = parse_tool_calls
    model._lenient_parsing = True
    return model


def load_prompts() -> tuple[dict, str]:
    with open(PROMPTS_PATH) as f:
        templates = yaml.safe_load(f)
    instructions = templates.pop("instructions")
    return templates, instructions


def build_agent(model=None, verbosity_level: int = 1) -> ToolCallingAgent:
    templates, instructions = load_prompts()
    return ToolCallingAgent(
        tools=ALL_TOOLS,
        model=lenient_tool_call_parsing(model or build_model()),
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
    if isinstance(call.arguments, dict):
        args = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
    else:
        args = repr(call.arguments) if call.arguments else ""
    return f"{call.name}({args})"


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

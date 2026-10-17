"""Gradio chat UI with password login. One agent per browser session so clarifying questions keep context.

Each tool call the agent makes is shown as a collapsed message above its reply, so you can see how it got there.
"""

from collections import OrderedDict
from collections.abc import Iterator
from typing import Callable

import gradio as gr

from agent import chat_steps

MAX_SESSIONS = 20


def build_ui(make_agent: Callable) -> gr.ChatInterface:
    agents: OrderedDict = OrderedDict()

    def respond(message: str, history: list, request: gr.Request) -> Iterator[list[gr.ChatMessage]]:
        """Send one message to the gym logging agent and stream its tool calls and reply."""
        key = request.session_hash if request else "default"
        if key not in agents:
            agents[key] = make_agent()
            if len(agents) > MAX_SESSIONS:
                agents.popitem(last=False)
        agents.move_to_end(key)

        shown: list[gr.ChatMessage] = [gr.ChatMessage(role="assistant", content="",
                                                      metadata={"title": "🤔 Thinking…", "status": "pending"})]
        yield shown
        try:
            for step in chat_steps(agents[key], message):
                if step["kind"] == "answer":
                    shown[-1:] = [gr.ChatMessage(role="assistant", content=step["body"])]
                else:
                    shown.insert(len(shown) - 1, gr.ChatMessage(
                        role="assistant", content=step["body"] or "(no output)",
                        metadata={"title": step["title"], "status": "done"}))
                yield shown
        except Exception as e:  # keep the chat usable if the model provider errors
            shown[-1:] = [gr.ChatMessage(role="assistant", content=f"Something went wrong: {e}")]
            yield shown

    return gr.ChatInterface(
        fn=respond,
        title="Gym Agent",
        description="Log sets like `bench 3x8 @135`. Also: `undo`, `another set`, `what's my bench PR?`, `done`.",
        examples=["bench 3x8 @135", "what's my bench PR?", "undo", "done"],
        cache_examples=False,
    )


def launch(demo: gr.ChatInterface, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False)

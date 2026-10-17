"""Gradio chat UI with password login. One agent per browser session so clarifying questions keep context."""

from collections import OrderedDict
from typing import Callable

import gradio as gr

from agent import chat

MAX_SESSIONS = 20


def build_ui(make_agent: Callable) -> gr.ChatInterface:
    agents: OrderedDict = OrderedDict()

    def respond(message: str, history: list, request: gr.Request) -> str:
        """Send one message to the gym logging agent and return its reply."""
        key = request.session_hash if request else "default"
        if key not in agents:
            agents[key] = make_agent()
            if len(agents) > MAX_SESSIONS:
                agents.popitem(last=False)
        agents.move_to_end(key)
        try:
            return chat(agents[key], message)
        except Exception as e:  # keep the chat usable if the model provider errors
            return f"Something went wrong: {e}"

    return gr.ChatInterface(
        fn=respond,
        title="Gym Agent",
        description="Log sets like `bench 3x8 @135`. Also: `undo`, `another set`, `what's my bench PR?`, `done`.",
        examples=["bench 3x8 @135", "what's my bench PR?", "undo", "done"],
        cache_examples=False,
    )


def launch(demo: gr.ChatInterface, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False)

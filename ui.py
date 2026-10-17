"""Gradio UI with password login: a chat tab, a sets table, and a session timer in the header.

One agent per browser session so clarifying questions keep context. Each tool call the agent makes is shown as a
collapsed message above its reply. The table and timer read through db.py and never change data.
"""

import os
from collections import OrderedDict
from collections.abc import Iterator
from typing import Callable
from zoneinfo import ZoneInfo

import gradio as gr

import db
import exercises
from agent import chat_steps

MAX_SESSIONS = 20
SETS_SHOWN = 200
REFRESH_SECONDS = 10
SETS_HEADERS = ["Day", "Exercise", "Set", "Note"]

# Ticks the header timer every second in the browser; the server only supplies the session start time.
TIMER_JS = """
<script>
setInterval(() => {
  const el = document.getElementById("session-timer");
  if (!el || !el.dataset.start) return;
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(el.dataset.start)) / 1000));
  const hms = [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60];
  el.textContent = "⏱ " + hms[0] + ":" + String(hms[1]).padStart(2, "0") + ":" + String(hms[2]).padStart(2, "0");
}, 1000);
</script>
"""

CSS = """
#topbar { align-items: center; flex-wrap: nowrap; }
#topbar h3 { margin: 0; }
#timer-box { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
"""


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC"))


def timer_html() -> str:
    session = db.get_db().active_session()
    if not session:
        return '<span id="session-timer">No active session</span>'
    return f'<span id="session-timer" data-start="{session["started_at"].isoformat()}">⏱ …</span>'


def sets_rows() -> list[list[str]]:
    names = exercises.get_index().by_id
    rows = []
    for s in db.get_db().recent_sets(SETS_SHOWN):
        name = names.get(s["exercise_id"], {}).get("name", s["exercise_id"])
        rows.append([s["logged_at"].astimezone(_tz()).strftime("%a %b %-d"), name,
                     f"{float(s['weight']):g} {s['unit']} × {s['reps']}", s.get("note") or ""])
    return rows


def build_ui(make_agent: Callable) -> gr.Blocks:
    agents: OrderedDict = OrderedDict()

    def respond(message: str, history: list, request: gr.Request) -> Iterator[list[gr.ChatMessage]]:
        """Send one message to the gym logging agent and stream its steps and reply."""
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

    with gr.Blocks(title="Gym Agent", fill_height=True) as demo:
        with gr.Row(elem_id="topbar"):
            gr.Markdown("### Gym Agent")
            timer = gr.HTML(timer_html, elem_id="timer-box")
        with gr.Tabs():
            with gr.Tab("Chat"):
                gr.ChatInterface(
                    fn=respond,
                    examples=["bench 3x8 @135", "what's my bench PR?", "undo", "done"],
                    cache_examples=False,
                    fill_height=True,
                )
            with gr.Tab("Sets") as sets_tab:
                table = gr.Dataframe(sets_rows, headers=SETS_HEADERS, interactive=False, wrap=True,
                                     show_label=False)

        poll = gr.Timer(REFRESH_SECONDS)
        poll.tick(timer_html, outputs=timer, show_progress="hidden")
        poll.tick(sets_rows, outputs=table, show_progress="hidden")
        sets_tab.select(sets_rows, outputs=table)

    return demo


def launch(demo: gr.Blocks, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False, css=CSS, head=TIMER_JS)

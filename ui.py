"""Mobile-first Gradio UI with password login: a full-screen chat, a sets list, and a session timer.

The header holds a pill button (top left) that switches between the chat and sets views, and the session timer (top
right). One agent per browser session so clarifying questions keep context. Each tool call the agent makes is shown as
a collapsed message above its reply. The sets list and timer read through db.py and never change data.
"""

import html
import os
from collections import OrderedDict
from collections.abc import Iterator
from itertools import groupby
from typing import Callable
from zoneinfo import ZoneInfo

import gradio as gr

import db
import exercises
from agent import chat_steps

MAX_SESSIONS = 20
SETS_SHOWN = 200
REFRESH_SECONDS = 10

THEME = gr.themes.Soft(
    primary_hue="indigo",
    neutral_hue="slate",
    radius_size="lg",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
)

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

HEADER_HEIGHT = "56px"
CSS = f"""
.gradio-container {{ max-width: 100% !important; padding: 0 !important; min-height: 100dvh; }}
.gradio-container > .main, .gradio-container .contain {{ padding: 0 !important; gap: 0 !important; }}

#topbar {{
  position: sticky; top: 0; z-index: 50; height: {HEADER_HEIGHT};
  display: flex; flex-wrap: nowrap; align-items: center; gap: 8px; padding: 0 16px;
  background: color-mix(in srgb, var(--background-fill-primary) 82%, transparent);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-color-primary);
}}
#fab-sets, #fab-chat {{
  flex: none !important; width: auto !important; min-width: 0 !important;
  border-radius: 999px !important; padding: 8px 14px !important; font-weight: 600;
  box-shadow: 0 4px 14px rgb(79 70 229 / 0.25);
}}
#title {{ flex: 1 1 auto; text-align: center; font-weight: 700; letter-spacing: -0.01em; min-width: 0; }}
#title p {{ margin: 0; }}
#timer-box {{ flex: none; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600;
  white-space: nowrap; font-size: 0.95rem; }}

#chat-view {{ height: calc(100dvh - {HEADER_HEIGHT}); padding: 0 8px 8px; }}
#chat-view textarea {{ font-size: 16px; }}  /* 16px stops iOS zooming into the input */

#sets-view {{ min-height: calc(100dvh - {HEADER_HEIGHT}); padding: 4px 16px 24px; }}
.sets-day {{ margin: 20px 0 6px; font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--body-text-color-subdued); }}
.sets-card {{ background: var(--background-fill-secondary); border-radius: 14px; overflow: hidden; }}
.set-row {{ padding: 12px 14px; border-bottom: 1px solid var(--border-color-primary); }}
.set-row:last-child {{ border-bottom: none; }}
.set-main {{ display: flex; justify-content: space-between; gap: 12px; }}
.set-name {{ font-weight: 600; }}
.set-load {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.set-note {{ margin-top: 2px; font-size: 0.85rem; color: var(--body-text-color-subdued); }}
.sets-empty {{ margin-top: 40px; text-align: center; color: var(--body-text-color-subdued); }}
"""


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC"))


def timer_html() -> str:
    session = db.get_db().active_session()
    if not session:
        return '<span id="session-timer">No session</span>'
    return f'<span id="session-timer" data-start="{session["started_at"].isoformat()}">⏱ …</span>'


def sets_html() -> str:
    """Recent sets grouped under day headings, newest first."""
    sets = db.get_db().recent_sets(SETS_SHOWN)
    if not sets:
        return '<div class="sets-empty">No sets yet. Log one from the chat.</div>'
    names = exercises.get_index().by_id
    tz = _tz()
    parts = []
    for day, day_sets in groupby(sets, key=lambda s: s["logged_at"].astimezone(tz).strftime("%a %b %-d")):
        rows = []
        for s in day_sets:
            name = names.get(s["exercise_id"], {}).get("name", s["exercise_id"])
            note = f'<div class="set-note">{html.escape(s["note"])}</div>' if s.get("note") else ""
            rows.append(f'<div class="set-row"><div class="set-main"><span class="set-name">{html.escape(name)}</span>'
                        f'<span class="set-load">{float(s["weight"]):g} {s["unit"]} × {s["reps"]}</span></div>'
                        f"{note}</div>")
        parts.append(f'<div class="sets-day">{day}</div><div class="sets-card">{"".join(rows)}</div>')
    return "".join(parts)


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
            fab_sets = gr.Button("📋 Sets", elem_id="fab-sets", variant="primary", size="sm", scale=0)
            fab_chat = gr.Button("💬 Chat", elem_id="fab-chat", variant="primary", size="sm", scale=0, visible=False)
            gr.Markdown("Gym Agent", elem_id="title")
            timer = gr.HTML(timer_html, elem_id="timer-box")

        with gr.Column(elem_id="chat-view") as chat_view:
            gr.ChatInterface(
                fn=respond,
                chatbot=gr.Chatbot(layout="bubble", show_label=False, container=False,
                                   placeholder="**Log a set**<br>bench 3x8 @135 · undo · what's my bench PR?"),
                textbox=gr.Textbox(placeholder="bench 3x8 @135", submit_btn=True, container=False,
                                   show_label=False),
                examples=["bench 3x8 @135", "what's my bench PR?", "undo", "done"],
                cache_examples=False,
                fill_height=True,
            )

        with gr.Column(elem_id="sets-view", visible=False) as sets_view:
            sets_list = gr.HTML(sets_html)

        fab_sets.click(lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False),
                                gr.update(visible=True), sets_html()),
                       outputs=[chat_view, sets_view, fab_sets, fab_chat, sets_list], show_progress="hidden")
        fab_chat.click(lambda: (gr.update(visible=True), gr.update(visible=False), gr.update(visible=True),
                                gr.update(visible=False)),
                       outputs=[chat_view, sets_view, fab_sets, fab_chat], show_progress="hidden")

        poll = gr.Timer(REFRESH_SECONDS)
        poll.tick(timer_html, outputs=timer, show_progress="hidden")
        poll.tick(sets_html, outputs=sets_list, show_progress="hidden")

    return demo


def launch(demo: gr.Blocks, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False, theme=THEME, css=CSS, head=TIMER_JS,
                footer_links=[], pwa=True)

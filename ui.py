"""Mobile-first Gradio UI with password login, styled after a dark, minimal chat app.

Header: a round icon button (top left) toggles between the chat and the sets list; a pill (top right) starts a
session, then shows its running time, and opens an "End session" dialog when tapped. One agent per browser session
so clarifying questions keep context. Each tool call the agent makes is shown as a collapsed message above its reply.
"""

import base64
import html
import os
from collections import OrderedDict
from collections.abc import Iterator
from itertools import groupby
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import gradio as gr

import db
import exercises
import tools
from agent import chat_steps

MAX_SESSIONS = 20
SETS_SHOWN = 200
REFRESH_SECONDS = 10
ASSETS = Path(__file__).parent / "assets"
SETS_ICON = str(ASSETS / "clipboard-list.svg")  # Lucide (ISC)
GREETING_ICON = "data:image/svg+xml;base64," + base64.b64encode((ASSETS / "dumbbell.svg").read_bytes()).decode()

BG, SURFACE, SURFACE_2, BORDER = "#1F1E1D", "#2A2927", "#33322F", "#3A3936"
TEXT, SUBDUED, ACCENT = "#ECEAE6", "#9C9A94", "#D97757"

THEME = gr.themes.Base(
    primary_hue="orange",
    neutral_hue="stone",
    radius_size="lg",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
).set(
    body_background_fill_dark=BG,
    background_fill_primary_dark=BG,
    background_fill_secondary_dark=SURFACE,
    block_background_fill_dark=BG,
    border_color_primary_dark=BORDER,
    body_text_color_dark=TEXT,
    body_text_color_subdued_dark=SUBDUED,
    color_accent_soft_dark=SURFACE_2,
    input_background_fill_dark=SURFACE,
    input_background_fill_focus_dark=SURFACE,
    input_background_fill_hover_dark=SURFACE,
    button_primary_background_fill_dark=TEXT,
    button_primary_background_fill_hover_dark="#FFFFFF",
    button_primary_text_color_dark=BG,
    button_secondary_background_fill_dark=SURFACE,
    button_secondary_background_fill_hover_dark=SURFACE_2,
    button_secondary_text_color_dark=TEXT,
)

# Always dark (the design is dark-only), and tick the session pill every second in the browser.
HEAD_JS = """
<script>
(() => {
  const url = new URL(window.location);
  if (url.searchParams.get("__theme") !== "dark") {
    url.searchParams.set("__theme", "dark");
    window.location.replace(url.href);
  }
})();
setInterval(() => {
  const data = document.getElementById("session-start");
  const btn = document.getElementById("session-btn");
  if (!data || !btn || !data.dataset.start) return;
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(data.dataset.start)) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
  btn.textContent = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(sec).padStart(2, "0");
}, 1000);
</script>
"""

HEADER = "60px"
CSS = f"""
.gradio-container {{ max-width: 100% !important; padding: 0 !important; min-height: 100dvh; }}
.gradio-container > .main, .gradio-container .contain, .gradio-container .contain > .column {{
  padding: 0 !important; gap: 0 !important; }}

#topbar {{ position: sticky; top: 0; z-index: 50; height: {HEADER}; display: flex; flex-wrap: nowrap;
  align-items: center; justify-content: space-between; padding: 0 16px; background: {BG}; }}
#sets-btn, #chat-btn {{ flex: none !important; width: 44px !important; min-width: 44px !important; height: 44px;
  padding: 0 !important; border-radius: 999px !important; background: {SURFACE} !important;
  border: 1px solid {BORDER} !important; box-shadow: none !important; }}
#sets-btn img, #chat-btn img {{ width: 20px; height: 20px; margin: 0 !important; }}
#chat-btn {{ font-size: 20px; color: {TEXT} !important; }}
#session-btn {{ flex: none !important; width: auto !important; min-width: 0 !important; height: 44px;
  padding: 0 18px !important; border-radius: 999px !important; background: {SURFACE} !important;
  border: 1px solid {BORDER} !important; color: {TEXT} !important; font-weight: 600;
  font-variant-numeric: tabular-nums; box-shadow: none !important; }}
#session-start-box {{ display: none !important; }}

#chat-view {{ height: calc(100dvh - {HEADER}); padding: 0 12px calc(12px + env(safe-area-inset-bottom)); }}
#chatbot {{ flex: 1 1 auto !important; height: auto !important; min-height: 0; border: none !important;
  background: transparent !important; }}
#chat-view .bubble-wrap, #chat-view .wrapper {{ background: transparent !important; }}
#chat-view .gr-group, #chat-view .styler {{ background: transparent !important; border: none !important; }}
#chat-input {{ background: {SURFACE} !important; border: 1px solid {BORDER} !important; border-radius: 26px !important;
  padding: 6px 6px 6px 16px !important; }}
#chat-input textarea {{ font-size: 16px !important; background: transparent !important; border: none !important;
  box-shadow: none !important; color: {TEXT}; }}
#chat-input textarea::placeholder {{ color: {SUBDUED}; }}
#chat-input button {{ border-radius: 999px !important; }}
.greeting {{ display: flex; flex-direction: column; align-items: center; gap: 14px; }}
.greeting img {{ width: 34px; height: 34px; }}
.greeting h2 {{ margin: 0; font-family: Georgia, "Times New Roman", serif; font-weight: 400; font-size: 1.6rem;
  color: {TEXT}; }}
.greeting p {{ margin: 0; color: {SUBDUED}; font-size: 0.9rem; }}

#sets-view {{ min-height: calc(100dvh - {HEADER}); padding: 0 16px 24px; }}
.sets-title {{ margin: 4px 0 4px; font-family: Georgia, "Times New Roman", serif; font-size: 1.5rem; }}
.sets-day {{ margin: 22px 0 8px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em; color: {SUBDUED}; }}
.sets-card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; overflow: hidden; }}
.set-row {{ padding: 13px 16px; border-bottom: 1px solid {BORDER}; }}
.set-row:last-child {{ border-bottom: none; }}
.set-main {{ display: flex; justify-content: space-between; gap: 12px; }}
.set-name {{ font-weight: 600; }}
.set-load {{ font-variant-numeric: tabular-nums; white-space: nowrap; color: {TEXT}; }}
.set-note {{ margin-top: 3px; font-size: 0.85rem; color: {SUBDUED}; }}
.sets-empty {{ margin-top: 30vh; text-align: center; color: {SUBDUED}; }}

#end-modal {{ position: fixed; inset: 0; z-index: 100; background: rgba(0, 0, 0, 0.6);
  align-items: center; justify-content: center; padding: 24px; }}
#end-card {{ width: 100%; max-width: 340px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 22px;
  padding: 22px 18px 18px; flex-grow: 0 !important; }}
#end-card h3 {{ margin: 0 0 4px; font-size: 1.1rem; }}
#end-card p {{ margin: 0; color: {SUBDUED}; }}
#end-card .row {{ flex-wrap: nowrap !important; gap: 10px; margin-top: 18px; }}
#end-confirm {{ background: {ACCENT} !important; color: #FFFFFF !important; border: none !important; }}
#end-cancel {{ background: transparent !important; border: 1px solid {BORDER} !important; color: {TEXT} !important; }}
#end-cancel, #end-confirm {{ border-radius: 999px !important; min-width: 0 !important; height: 46px; }}
"""

GREETING = (f'<div class="greeting"><img src="{GREETING_ICON}" alt=""><h2>Let\'s lift</h2>'
            "<p>bench 3x8 @135 · undo · what's my bench PR?</p></div>")


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC"))


def session_state() -> tuple[str, str]:
    """(pill label, hidden start-time element) for the current session."""
    session = db.get_db().active_session()
    if not session:
        return "Start session", '<span id="session-start"></span>'
    return "0:00", f'<span id="session-start" data-start="{session["started_at"].isoformat()}"></span>'


def sets_html() -> str:
    """Recent sets grouped under day headings, newest first."""
    sets = db.get_db().recent_sets(SETS_SHOWN)
    if not sets:
        return '<div class="sets-empty">No sets yet. Log one from the chat.</div>'
    names = exercises.get_index().by_id
    tz = _tz()
    parts = ['<div class="sets-title">Your sets</div>']
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

    def refresh_session():
        label, start = session_state()
        return gr.update(value=label), start

    def session_pressed():
        """No session: start one. Session running: ask whether to end it."""
        if db.get_db().active_session():
            return gr.update(), gr.update(), gr.update(visible=True)
        tools.start_session("")
        label, start = session_state()
        return gr.update(value=label), start, gr.update(visible=False)

    def end_pressed():
        gr.Info(tools.end_session())
        label, start = session_state()
        return gr.update(value=label), start, gr.update(visible=False)

    with gr.Blocks(title="Gym Agent", fill_height=True) as demo:
        label, start = session_state()
        with gr.Row(elem_id="topbar"):
            sets_btn = gr.Button("", icon=SETS_ICON, elem_id="sets-btn", scale=0)
            chat_btn = gr.Button("←", elem_id="chat-btn", scale=0, visible=False)
            session_btn = gr.Button(label, elem_id="session-btn", scale=0)
            session_start = gr.HTML(start, elem_id="session-start-box", padding=False)

        with gr.Column(elem_id="chat-view") as chat_view:
            gr.ChatInterface(
                fn=respond,
                chatbot=gr.Chatbot(layout="bubble", show_label=False, container=False, placeholder=GREETING,
                                   elem_id="chatbot"),
                textbox=gr.Textbox(placeholder="Log a set…", submit_btn=True, container=False, show_label=False,
                                   elem_id="chat-input"),
                fill_height=True,
            )

        with gr.Column(elem_id="sets-view", visible=False) as sets_view:
            sets_list = gr.HTML(sets_html)

        with gr.Column(elem_id="end-modal", visible=False) as end_modal:
            with gr.Column(elem_id="end-card"):
                gr.HTML("<h3>End session?</h3><p>You can start a new one any time.</p>")
                with gr.Row():
                    end_cancel = gr.Button("Cancel", elem_id="end-cancel", min_width=0)
                    end_confirm = gr.Button("End session", elem_id="end-confirm", min_width=0)

        sets_btn.click(lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False),
                                gr.update(visible=True), sets_html()),
                       outputs=[chat_view, sets_view, sets_btn, chat_btn, sets_list], show_progress="hidden")
        chat_btn.click(lambda: (gr.update(visible=True), gr.update(visible=False), gr.update(visible=True),
                                gr.update(visible=False)),
                       outputs=[chat_view, sets_view, sets_btn, chat_btn], show_progress="hidden")
        session_btn.click(session_pressed, outputs=[session_btn, session_start, end_modal], show_progress="hidden")
        end_cancel.click(lambda: gr.update(visible=False), outputs=end_modal, show_progress="hidden")
        end_confirm.click(end_pressed, outputs=[session_btn, session_start, end_modal], show_progress="hidden")

        poll = gr.Timer(REFRESH_SECONDS)
        poll.tick(refresh_session, outputs=[session_btn, session_start], show_progress="hidden")
        poll.tick(sets_html, outputs=sets_list, show_progress="hidden")
        demo.load(refresh_session, outputs=[session_btn, session_start], show_progress="hidden")

    return demo


def launch(demo: gr.Blocks, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False, theme=THEME, css=CSS, head=HEAD_JS,
                footer_links=[], pwa=True)

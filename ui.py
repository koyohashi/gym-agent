"""Mobile-first Gradio UI with password login, styled after a dark, minimal chat app.

Header: a round icon button (top left) toggles between the chat and the sets list; a pill (top right) starts a
session, then shows its running time, and opens an "End session" dialog when tapped. One agent per browser session
so clarifying questions keep context. While the agent works, its steps are tucked into one collapsed box (an
animated "Working" title) above its reply; tapping the box expands them.
"""

import base64
import html
import os
import time
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
SESSIONS_SHOWN = 30
REFRESH_SECONDS = 10
ASSETS = Path(__file__).parent / "assets"
SETS_ICON = str(ASSETS / "clipboard-list.svg")  # Lucide (ISC)
GREETING_ICON = "data:image/svg+xml;base64," + base64.b64encode((ASSETS / "dumbbell.svg").read_bytes()).decode()

BG, SURFACE, SURFACE_2, BORDER = "#1F1E1D", "#2A2927", "#33322F", "#3A3936"
TEXT, SUBDUED, ACCENT = "#ECEAE6", "#9C9A94", "#D97757"

# Dark-only design: light and dark mode get the same colors, so even the login page (which loads the theme but
# not the app's CSS or scripts) is dark.
_COLORS = {
    "body_background_fill": BG,
    "background_fill_primary": BG,
    "background_fill_secondary": SURFACE,
    "block_background_fill": SURFACE,
    "block_border_color": BORDER,
    "block_label_text_color": SUBDUED,
    "block_title_text_color": TEXT,
    "border_color_primary": BORDER,
    "border_color_accent": BORDER,
    "border_color_accent_subdued": BORDER,
    "body_text_color": TEXT,
    "body_text_color_subdued": SUBDUED,
    "color_accent_soft": SURFACE_2,
    "input_background_fill": SURFACE_2,
    "input_background_fill_focus": SURFACE_2,
    "input_background_fill_hover": SURFACE_2,
    "input_border_color": BORDER,
    "input_border_color_focus": SUBDUED,
    "button_primary_background_fill": TEXT,
    "button_primary_background_fill_hover": "#FFFFFF",
    "button_primary_text_color": BG,
    "button_secondary_background_fill": SURFACE,
    "button_secondary_background_fill_hover": SURFACE_2,
    "button_secondary_text_color": TEXT,
}
THEME = gr.themes.Base(
    primary_hue="orange",
    neutral_hue="stone",
    radius_size="lg",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
).set(
    input_text_size="16px",  # iOS Safari zooms into any field with smaller text, including the login form
    **_COLORS,
    **{f"{k}_dark": v for k, v in _COLORS.items()},
)

# Ticks the session pill every second in the browser.
HEAD_JS = """
<script>
// The pill's label is owned here (Gradio never changes it): elapsed time while a session runs, else "Start session".
const renderSessionPill = () => {
  const data = document.getElementById("session-start");
  const btn = document.getElementById("session-btn");
  if (!btn) return;
  let label = "Start session";
  if (data && data.dataset.start) {
    const s = Math.max(0, Math.floor((Date.now() - Date.parse(data.dataset.start)) / 1000));
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
    label = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(sec).padStart(2, "0");
  }
  if (btn.textContent !== label) btn.textContent = label;
};
setInterval(renderSessionPill, 250);
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

#chat-view {{ height: calc(100dvh - {HEADER}); padding: 0 12px calc(12px + env(safe-area-inset-bottom));
  overflow: hidden; }}
/* Let every flex container down to the message list shrink, so the list scrolls instead of growing the page. */
#chat-view > .column, #chatbot, #chatbot > .wrapper {{ min-height: 0 !important; }}
#chat-view > .column {{ flex: 1 1 0 !important; overflow: hidden; }}
#chatbot {{ flex: 1 1 0 !important; height: auto !important; border: none !important;
  background: transparent !important; }}
#chatbot > .wrapper {{ height: 100%; }}
#chatbot .bubble-wrap {{ flex: 1 1 0; min-height: 0; height: 100%; overflow-y: auto; overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch; }}
#chat-view .bubble-wrap, #chat-view .wrapper {{ background: transparent !important; }}
#chat-view .gr-group, #chat-view .styler {{ background: transparent !important; border: none !important; }}
/* Agent replies read as plain text (no bubble); the user's messages keep theirs. */
#chatbot .message.bot {{ background: transparent !important; border: none !important; box-shadow: none !important;
  padding: 2px 0 !important; max-width: 100% !important; }}
/* Soft blur where messages scroll up under the header. */
#chat-view {{ position: relative; }}
#chat-view::before {{ content: ""; position: absolute; top: 0; left: 0; right: 0; height: 32px; z-index: 10;
  pointer-events: none; background: linear-gradient(to bottom, {BG}, transparent);
  backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  mask-image: linear-gradient(to bottom, black, transparent);
  -webkit-mask-image: linear-gradient(to bottom, black, transparent); }}
/* The agent's steps: one rounded box, collapsed, whose title animates while it works. */
#chatbot .thought-group {{ background: {SURFACE} !important; border: 1px solid {BORDER} !important;
  border-radius: 16px !important; padding: 6px 12px !important; }}
#chatbot .thought-group .thought-group {{ background: transparent !important; border: none !important;
  padding: 2px 0 !important; }}
#chatbot .thought-group .title {{ color: {SUBDUED}; }}
.working {{ display: inline-flex; align-items: baseline; gap: 3px; color: {TEXT};
  background: linear-gradient(90deg, {SUBDUED} 0%, {TEXT} 50%, {SUBDUED} 100%) 0 0 / 200% 100%;
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  animation: working-shimmer 2s linear infinite; }}
.working i {{ width: 5px; height: 5px; border-radius: 50%; background: {ACCENT}; margin-left: 1px;
  animation: working-hop 1.1s ease-in-out infinite; }}
.working i:nth-of-type(2) {{ animation-delay: 0.15s; }}
.working i:nth-of-type(3) {{ animation-delay: 0.3s; }}
@keyframes working-shimmer {{ to {{ background-position: -200% 0; }} }}
@keyframes working-hop {{ 0%, 60%, 100% {{ transform: translateY(0); opacity: 0.4; }}
  30% {{ transform: translateY(-5px); opacity: 1; }} }}
/* 16px+ text in every field: iOS Safari zooms in on focus below that (it was zooming on the login form). */
input, textarea, select {{ font-size: 16px !important; }}
@media (max-width: 768px) {{  /* phones: drop the chat toolbar (share, clear, copy conversation) */
  #chatbot .icon-button-wrapper.top-panel {{ display: none !important; }}
}}
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
.hist-title-page {{ margin: 4px 0 0; font-family: Georgia, "Times New Roman", serif; font-size: 1.5rem; }}
.hist-month {{ margin: 22px 0 8px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em; color: {SUBDUED}; }}
.hist-card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; margin-bottom: 10px; }}
.hist-card.active {{ border-color: {ACCENT}; }}
.hist-card summary {{ list-style: none; cursor: pointer; padding: 14px 16px; }}
.hist-card summary::-webkit-details-marker {{ display: none; }}
.hist-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
.hist-title {{ font-weight: 600; font-size: 1.05rem; }}
.hist-date {{ margin-top: 2px; font-size: 0.85rem; color: {SUBDUED}; }}
.hist-chev {{ flex: none; width: 8px; height: 8px; margin-top: 6px; border-right: 2px solid {SUBDUED};
  border-bottom: 2px solid {SUBDUED}; transform: rotate(45deg); transition: transform 0.15s; }}
.hist-card[open] .hist-chev {{ transform: rotate(-135deg); margin-top: 10px; }}
.hist-stats {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 10px;
  font-size: 0.85rem; color: {SUBDUED}; font-variant-numeric: tabular-nums; }}
.hist-live {{ color: {ACCENT}; font-weight: 600; }}
.hist-badge {{ padding: 1px 8px; border-radius: 999px; background: {ACCENT}; color: #FFFFFF; font-size: 0.72rem;
  font-weight: 700; }}
.hist-summary {{ margin-top: 12px; padding-top: 10px; border-top: 1px solid {BORDER}; }}
.hist-card[open] .hist-summary {{ display: none; }}
.hist-line {{ display: flex; justify-content: space-between; gap: 12px; padding: 3px 0; font-size: 0.92rem; }}
.hist-load {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.hist-line .hist-load {{ color: {SUBDUED}; }}
.hist-detail {{ padding: 0 16px 8px; }}
.hist-block {{ padding: 12px 0; border-top: 1px solid {BORDER}; }}
.hist-block .hist-ex {{ font-weight: 600; margin-bottom: 6px; }}
.hist-set {{ display: flex; align-items: center; gap: 12px; padding: 3px 0; }}
.hist-num {{ width: 22px; height: 22px; flex: none; display: inline-flex; align-items: center;
  justify-content: center; border-radius: 6px; background: {SURFACE_2}; font-size: 0.78rem; color: {SUBDUED}; }}
.hist-note {{ margin: 0 0 4px 34px; font-size: 0.85rem; color: {SUBDUED}; }}
.hist-summary .hist-note {{ margin: 0; }}
.hist-empty {{ margin-top: 30vh; text-align: center; color: {SUBDUED}; }}

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

WORKING = '<span class="working">Working<i></i><i></i><i></i></span>'

GREETING = (f'<div class="greeting"><img src="{GREETING_ICON}" alt=""><h2>Let\'s lift</h2>'
            "<p>bench 3x8 @135 · undo · what's my bench PR?</p></div>")


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC"))


def session_start_html() -> str:
    """Hidden element carrying the active session's start time; the browser script renders the pill from it."""
    session = db.get_db().active_session()
    if not session:
        return '<span id="session-start"></span>'
    return f'<span id="session-start" data-start="{session["started_at"].isoformat()}"></span>'


def _pr_set_ids(sets: list[dict]) -> set[str]:
    """Ids of each session's top set per exercise when it beats (in lbs) that exercise's best from earlier sessions.
    Warm-up ramps within one session don't count, and neither does the first session an exercise is logged in."""
    tops: dict[tuple, dict] = {}  # (session, exercise) -> heaviest set, in order of first appearance
    for s in sorted(sets, key=lambda s: s["logged_at"]):
        key = (s["session_id"], s["exercise_id"])
        if key not in tops or db.weight_in_lbs(s) > db.weight_in_lbs(tops[key]):
            tops[key] = s
    best: dict[str, float] = {}
    prs = set()
    for (_, exercise_id), top in tops.items():
        weight, prev = db.weight_in_lbs(top), best.get(exercise_id)
        if prev is not None and weight > prev:
            prs.add(top["id"])
        if prev is None or weight > prev:
            best[exercise_id] = weight
    return prs


def _load(s: dict) -> str:
    return f'{float(s["weight"]):g} {s["unit"]} × {s["reps"]}'


def _duration(session: dict) -> str:
    minutes = int((session["ended_at"] - session["started_at"]).total_seconds() // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _session_card(session: dict, sets: list[dict], pr_ids: set[str], names: dict, tz: ZoneInfo) -> str:
    """One workout: title, date, stats and a line per exercise; tapping it expands to every set."""
    started = session["started_at"].astimezone(tz)
    part_of_day = "Morning" if started.hour < 12 else "Afternoon" if started.hour < 17 else "Evening"
    title = html.escape(session.get("label") or f"{part_of_day} Workout")
    active = not session.get("ended_at")

    by_exercise: dict[str, list[dict]] = {}
    for s in sets:
        by_exercise.setdefault(s["exercise_id"], []).append(s)
    unit = max(("lbs", "kg"), key=lambda u: sum(s["unit"] == u for s in sets))
    volume = sum(db.weight_in_lbs(s) * s["reps"] for s in sets) / (db.KG_TO_LBS if unit == "kg" else 1)
    prs = sum(s["id"] in pr_ids for s in sets)

    stats = ['<span class="hist-live">In progress</span>' if active else f"<span>{_duration(session)}</span>",
             f'<span>{len(sets)} set{"" if len(sets) == 1 else "s"}</span>']
    if sets:
        stats.append(f"<span>{round(volume):,} {unit}</span>")
    if prs:
        stats.append(f'<span class="hist-badge">{prs} PR{"" if prs == 1 else "s"}</span>')

    summary, detail = [], []
    for exercise_id, ex_sets in by_exercise.items():
        name = html.escape(names.get(exercise_id, {}).get("name", exercise_id))
        top = max(ex_sets, key=lambda s: (db.weight_in_lbs(s), s["reps"]))
        summary.append(f'<div class="hist-line"><span class="hist-ex">{len(ex_sets)} × {name}</span>'
                       f'<span class="hist-load">{_load(top)}</span></div>')
        rows = []
        for i, s in enumerate(ex_sets, 1):
            badge = '<span class="hist-badge">PR</span>' if s["id"] in pr_ids else ""
            note = f'<div class="hist-note">{html.escape(s["note"])}</div>' if s.get("note") else ""
            rows.append(f'<div class="hist-set"><span class="hist-num">{i}</span>'
                        f'<span class="hist-load">{_load(s)}</span>{badge}</div>{note}')
        detail.append(f'<div class="hist-block"><div class="hist-ex">{name}</div>{"".join(rows)}</div>')
    if not sets:
        summary.append('<div class="hist-note">No sets yet</div>')

    return (f'<details class="hist-card{" active" if active else ""}"><summary>'
            f'<div class="hist-head"><div><div class="hist-title">{title}</div>'
            f'<div class="hist-date">{started.strftime("%a, %b %-d · %-I:%M %p")}</div></div>'
            f'<span class="hist-chev"></span></div>'
            f'<div class="hist-stats">{"".join(stats)}</div>'
            f'<div class="hist-summary">{"".join(summary)}</div></summary>'
            f'<div class="hist-detail">{"".join(detail)}</div></details>')


def history_html() -> str:
    """Workout history: one card per session under month headings, newest first."""
    database = db.get_db()
    sessions = database.recent_sessions(SESSIONS_SHOWN)
    all_sets = database.find_sets()  # every set, so PRs are judged against the full history
    by_session: dict[str, list[dict]] = {}
    for s in sorted(all_sets, key=lambda s: s["logged_at"]):
        by_session.setdefault(s["session_id"], []).append(s)
    sessions = [x for x in sessions if by_session.get(x["id"]) or not x.get("ended_at")]
    if not sessions:
        return '<div class="hist-empty">No workouts yet. Log a set from the chat.</div>'

    names = exercises.get_index().by_id
    tz = _tz()
    pr_ids = _pr_set_ids(all_sets)
    parts = ['<div class="hist-title-page">History</div>']
    for month, month_sessions in groupby(sessions, key=lambda x: x["started_at"].astimezone(tz).strftime("%B %Y")):
        cards = "".join(_session_card(x, by_session.get(x["id"], []), pr_ids, names, tz) for x in month_sessions)
        parts.append(f'<div class="hist-month">{month}</div>{cards}')
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

        # Steps nest under one box. It's "done" from the start because Gradio auto-expands pending boxes; the
        # animated title is what shows it's still working.
        work_id = f"work-{time.time_ns()}"  # unique per turn, so steps never nest under an earlier turn's box
        work = gr.ChatMessage(role="assistant", content="",
                              metadata={"id": work_id, "title": WORKING, "status": "done"})
        shown: list[gr.ChatMessage] = [work]
        started = time.monotonic()
        yield shown
        try:
            for step in chat_steps(agents[key], message, session_id=key):
                if step["kind"] == "answer":
                    steps = len(shown) - 1
                    if steps:
                        work.metadata = {"id": work_id, "status": "done", "duration": round(time.monotonic() - started),
                                         "title": f"Worked through {steps} step{'s' if steps > 1 else ''}"}
                    else:
                        shown.remove(work)
                    shown.append(gr.ChatMessage(role="assistant", content=step["body"]))
                else:
                    shown.append(gr.ChatMessage(
                        role="assistant", content=step["body"] or "(no output)",
                        metadata={"parent_id": work_id, "title": step["title"], "status": "done"}))
                yield shown
        except Exception as e:  # keep the chat usable if the model provider errors
            if len(shown) == 1:
                shown.remove(work)
            else:
                work.metadata = {"id": work_id, "status": "done", "title": "Stopped"}
            shown.append(gr.ChatMessage(role="assistant", content=f"Something went wrong: {e}"))
            yield shown

    def session_pressed():
        """No session: start one. Session running: ask whether to end it."""
        if db.get_db().active_session():
            return gr.update(), gr.update(visible=True)
        tools.start_session("")
        return session_start_html(), gr.update(visible=False)

    def end_pressed():
        gr.Info(tools.end_session(), duration=2, title="")
        return session_start_html(), gr.update(visible=False)

    with gr.Blocks(title="Gym Agent", fill_height=True) as demo:
        with gr.Row(elem_id="topbar"):
            sets_btn = gr.Button("", icon=SETS_ICON, elem_id="sets-btn", scale=0)
            chat_btn = gr.Button("←", elem_id="chat-btn", scale=0, visible=False)
            session_btn = gr.Button("Start session", elem_id="session-btn", scale=0)
            session_start = gr.HTML("", elem_id="session-start-box", padding=False)

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
            sets_list = gr.HTML("")

        with gr.Column(elem_id="end-modal", visible=False) as end_modal:
            with gr.Column(elem_id="end-card"):
                gr.HTML("<h3>End session?</h3><p>You can start a new one any time.</p>")
                with gr.Row():
                    end_cancel = gr.Button("Cancel", elem_id="end-cancel", min_width=0)
                    end_confirm = gr.Button("End session", elem_id="end-confirm", min_width=0)

        sets_btn.click(lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False),
                                gr.update(visible=True), history_html()),
                       outputs=[chat_view, sets_view, sets_btn, chat_btn, sets_list], show_progress="hidden")
        chat_btn.click(lambda: (gr.update(visible=True), gr.update(visible=False), gr.update(visible=True),
                                gr.update(visible=False)),
                       outputs=[chat_view, sets_view, sets_btn, chat_btn], show_progress="hidden")
        session_btn.click(session_pressed, outputs=[session_start, end_modal], show_progress="hidden")
        end_cancel.click(lambda: gr.update(visible=False), outputs=end_modal, show_progress="hidden")
        end_confirm.click(end_pressed, outputs=[session_start, end_modal], show_progress="hidden")

        # Filled on page load rather than at build time, so building the UI never touches the database. History isn't
        # polled (a refresh would collapse an open card); it re-renders each time the sets button opens it.
        demo.load(lambda: (session_start_html(), history_html()), outputs=[session_start, sets_list],
                  show_progress="hidden")
        poll = gr.Timer(REFRESH_SECONDS)
        poll.tick(session_start_html, outputs=session_start, show_progress="hidden")

    return demo


def launch(demo: gr.Blocks, user: str, password: str) -> None:
    demo.launch(auth=(user, password), ssr_mode=False, theme=THEME, css=CSS, head=HEAD_JS,
                footer_links=[], pwa=True)

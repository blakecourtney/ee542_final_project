import hashlib
import hmac
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import pandas as pd
import streamlit as st
from garmin_ingest.analytics import analyze
from garmin_ingest import context as context_mod
from garmin_ingest.recommend import recommend

# get pathname
APP_DIR = Path(__file__).resolve().parent 

# fake account setup
PEOPLE = {
    "Anchal": ["Blake", "Kendal"],
    "Lily": ["Riley", "Bryn"],
}

# setup databases
CLIENT_DBS = {
    "Blake": str(APP_DIR.parent / "garmin.db"),
}
FEEDBACK_DB = str(APP_DIR / "data" / "feedback.db")

# use ten most recent workouts
RECENT = 10  

# types of activities that should show pace
RUN_TYPES = {"running", "track_running", "treadmill_running", "trail_running"}

# get garmin database
def _open_garmin(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

# get new sensor updates
@st.cache_data()
def get_workouts(db_path: str, limit: Optional[int] = RECENT) -> List[dict]:
    if not Path(db_path).exists():
        return []
    conn = _open_garmin(db_path)
    try:
        rows = conn.execute(
            """SELECT activity_id, activity_type, start_time_local, distance_m,
                      moving_duration_s, avg_hr, max_hr, training_load, aerobic_te
               FROM activities ORDER BY start_time_local DESC LIMIT ?""",
            (limit if limit is not None else -1,), 
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

# get recommendation (using recommend.py and analyze.py)
def draft_feedback(db_path: str, w: dict) -> str:
    conn = _open_garmin(db_path)
    try:
        return "\n".join(recommend(analyze(conn, w["activity_type"])))
    finally:
        conn.close()

# sync new data 
@st.cache_resource
def _locks() -> dict:
    return {"context": threading.Lock(), "sync": threading.Lock()}  

@contextmanager
def _db_path_override(module, path: str, lock_name: str):
    with _locks()[lock_name]:
        original = module.DB_PATH
        module.DB_PATH = path
        try:
            yield
        finally:
            module.DB_PATH = original

def sync_client_data(client: str) -> Optional[str]:
    db_path = CLIENT_DBS.get(client)
    try:
        import garmin_ingest.sync as sync_mod
        with _db_path_override(sync_mod, db_path, "sync"):
            result = sync_mod.run_sync()
        get_workouts.clear()  
        return (f"Synced: {result['activities_written']} new activities.")
    except Exception:
        logging.exception("Sync failed for %s", client)
        return "Couldn't update. Showing only your last saved data."


# put trainer feedback in database
def _feedback_conn() -> sqlite3.Connection:
    Path(FEEDBACK_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(FEEDBACK_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        client      TEXT NOT NULL,
        activity_id INTEGER NOT NULL,
        trainer     TEXT NOT NULL,
        ai_draft    TEXT,
        final_text  TEXT,
        status      TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (client, activity_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS direct_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trainer     TEXT NOT NULL,
        client      TEXT NOT NULL,
        sender      TEXT NOT NULL,
        message     TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        is_read     INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        username      TEXT PRIMARY KEY,
        display_name  TEXT NOT NULL,   -- unique; used as the client/trainer name everywhere
        role          TEXT NOT NULL,   -- 'trainer' or 'client'
        trainer       TEXT,            -- clients only: display_name of their coach
        salt          BLOB NOT NULL,
        password_hash TEXT NOT NULL
    )""")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "trainer" not in cols: 
        conn.execute("ALTER TABLE users ADD COLUMN trainer TEXT")
    return conn

# get the feedback for a specific workout
def get_feedback(client: str, activity_id: int) -> Optional[dict]:
    conn = _feedback_conn()
    try:
        row = conn.execute("SELECT * FROM feedback WHERE client = ? AND activity_id = ?",
                           (client, activity_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

# get all feedback for a specific client
def get_feedback_map(client: str) -> dict:
    conn = _feedback_conn()
    try:
        rows = conn.execute("SELECT * FROM feedback WHERE client = ?", (client,)).fetchall()
        return {r["activity_id"]: dict(r) for r in rows}
    finally:
        conn.close()

# get workouts that trainer has given feedback on
def approved_activity_ids(client: str) -> set:
    conn = _feedback_conn()
    try:
        rows = conn.execute("SELECT activity_id FROM feedback WHERE client = ? AND status = 'Approved'",
                            (client,)).fetchall()
        return {r["activity_id"] for r in rows}
    finally:
        conn.close()

# update feedback when trainer submits
def save_feedback(client, activity_id, trainer, ai_draft, final_text) -> None:
    if not is_coach_of(trainer, client):
        raise PermissionError(f"{trainer} is not {client}'s coach.")
    conn = _feedback_conn()
    try:
        conn.execute(
            """INSERT INTO feedback (client, activity_id, trainer, ai_draft, final_text, status, updated_at)
               VALUES (?, ?, ?, ?, ?, 'Approved', ?)
               ON CONFLICT(client, activity_id) DO UPDATE SET
                   trainer = excluded.trainer, final_text = excluded.final_text,
                   status = 'Approved', updated_at = excluded.updated_at""",
            (client, activity_id, trainer, ai_draft, final_text, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()

# send message between trainer and client
def send_direct_message(trainer: str, client: str, sender: str, message: str) -> None:
    if not is_coach_of(trainer, client):
        raise PermissionError("This trainer/client relationship is not valid.")
    body = message.strip()
    if not body:
        return
    if sender not in {trainer, client}:
        raise PermissionError("Sender is not part of this conversation.")
    conn = _feedback_conn()
    try:
        conn.execute(
            "INSERT INTO direct_messages (trainer, client, sender, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (trainer, client, sender, body, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()

# get message from trainer/client
def get_direct_messages(trainer: str, client: str) -> List[dict]:
    if not is_coach_of(trainer, client):
        raise PermissionError("This trainer/client relationship is not valid.")
    conn = _feedback_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM direct_messages WHERE trainer = ? AND client = ? ORDER BY id",
            (trainer, client),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# create message ui
def render_direct_messages(trainer: str, client: str, current_user: str) -> None:
    st.subheader(f"Conversation with {'your trainer' if current_user == client else client}")
    try:
        messages = get_direct_messages(trainer, client)
    except PermissionError as exc:
        st.error(str(exc))
        return
    if not messages:
        st.info("No messages yet. Start the conversation below.")
    for item in messages:
        who = "You" if item["sender"] == current_user else item["sender"]
        with st.chat_message("user" if item["sender"] == current_user else "assistant"):
            st.caption(f"{who} · {item['created_at'][:16].replace('T', ' ')}")
            st.write(item["message"])
    with st.form(f"direct_message_form_{trainer}_{client}_{current_user}", clear_on_submit=True):
        message = st.text_area("Message", placeholder="Write a message...", height=90)
        submitted = st.form_submit_button("Send message")
    if submitted:
        if message.strip():
            send_direct_message(trainer, client, current_user, message)
            st.rerun()
        else:
            st.info("Enter a message before sending.")


# setup logins
DEFAULT_PASSWORD = "demo1234" 
TRAINER_SIGNUP_CODE = "coach-2026" 

def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()

def _username_for(name: str) -> str:
    return name.lower().replace(" ", "_")  # "Kendal" -> "kendal"

# create default accounts
def seed_users(roster: dict) -> None:
    conn = _feedback_conn()
    try:
        existing = {r["username"] for r in conn.execute("SELECT username FROM users")}
        people = []
        for trainer, clients in roster.items():
            people.append((trainer, "trainer", None))
            people.extend((c, "client", trainer) for c in clients)
        for name, role, trainer in people:
            username = _username_for(name)
            if username in existing:
                if role == "client":
                    conn.execute(
                        "UPDATE users SET trainer = ? WHERE username = ? AND role = 'client'",
                        (trainer, username),
                    )
                continue
            salt = os.urandom(16)
            conn.execute(
                "INSERT INTO users (username, display_name, role, trainer, salt, password_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, name, role, trainer, salt, _hash_password(DEFAULT_PASSWORD, salt)),
            )
        conn.commit()
    finally:
        conn.close()

# get all users
def get_roster() -> dict:
    conn = _feedback_conn()
    try:
        rows = conn.execute(
            "SELECT display_name, role, trainer FROM users ORDER BY display_name"
        ).fetchall()
    finally:
        conn.close()
    roster = {trainer: list(clients) for trainer, clients in PEOPLE.items()}
    for row in rows:
        if row["role"] == "trainer":
            roster.setdefault(row["display_name"], [])
    for row in rows:
        if row["role"] == "client" and row["trainer"] in roster:
            clients = roster[row["trainer"]]
            if row["display_name"] not in clients:
                clients.append(row["display_name"])
    return roster

# get client's coach
def is_coach_of(trainer: str, client: str) -> bool:
    conn = _feedback_conn()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE display_name = ? AND role = 'client' AND trainer = ?",
                           (client, trainer)).fetchone()
        return row is not None
    finally:
        conn.close()

# create new accounts
def create_user(username: str, display_name: str, password: str, role: str,
                trainer: Optional[str] = None) -> Optional[str]:
    username = username.strip().lower()
    display_name = " ".join(display_name.split())
    if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        return "Username must be 3-30 characters: lowercase letters, numbers, underscores."
    if not display_name:
        return "Please enter your name."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if role == "client" and not trainer:
        return "Please choose a coach."
    conn = _feedback_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            return "That username is taken."
        if conn.execute("SELECT 1 FROM users WHERE lower(display_name) = lower(?)", (display_name,)).fetchone():
            return "Someone with that name already has an account."
        salt = os.urandom(16)
        conn.execute(
            "INSERT INTO users (username, display_name, role, trainer, salt, password_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, display_name, role, trainer if role == "client" else None,
             salt, _hash_password(password, salt)),
        )
        conn.commit()
        return None
    finally:
        conn.close()

# check password when logging in
def authenticate(username: str, password: str) -> Optional[dict]:
    conn = _feedback_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?",
                           (username.strip().lower(),)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    attempt = _hash_password(password, row["salt"])
    if not hmac.compare_digest(attempt, row["password_hash"]):
        return None
    return {"username": row["username"], "name": row["display_name"], "role": row["role"]}

# sync data when logging in
def _start_session(user: dict) -> None:
    if user["role"] == "client" and CLIENT_DBS.get(user["name"]):
        with st.spinner("Syncing your latest workouts..."):
            st.session_state["sync_msg"] = sync_client_data(user["name"])
    st.session_state.user = user
    st.rerun()

# log in page
def render_login() -> None:
    st.title("Fitness Training Platform")
    _, col, _ = st.columns([1, 2, 1])
    with col:
        tab_login, tab_signup = st.tabs(["Log in", "Create account"])
        with tab_login:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in")
            if submitted:
                user = authenticate(username, password)
                if user:
                    _start_session(user)
                else:
                    time.sleep(1)
                    st.error("Invalid username or password.")
        with tab_signup:
            render_signup()

# create account page
def render_signup() -> None:
    role = st.radio("I am a", ["Client", "Trainer"], horizontal=True, key="signup_role").lower()
    trainers = list(get_roster().keys())
    with st.form("signup_form"):
        name = st.text_input("Full name")
        username = st.text_input("Choose a username")
        password = st.text_input("Password (8+ characters)", type="password")
        confirm = st.text_input("Confirm password", type="password")
        coach, code = None, ""
        if role == "client":
            coach = st.selectbox("Your coach", trainers) if trainers else None
            st.caption("By choosing a coach, you allow them to view your workout and health "
                       "data and to send you feedback.")
        else:
            code = st.text_input("Trainer sign-up code", type="password")
        submitted = st.form_submit_button("Create account")
    if not submitted:
        return
    if password != confirm:
        st.error("Passwords don't match.")
    elif role == "trainer" and not hmac.compare_digest(code, TRAINER_SIGNUP_CODE):
        time.sleep(1)
        st.error("Invalid trainer sign-up code.")
    else:
        error = create_user(username, name, password, role, coach)
        if error:
            st.error(error)
        else:
            _start_session({"username": username.strip().lower(),
                            "name": " ".join(name.split()), "role": role})


# get workout data
def load_context(client: str, workout: dict) -> Optional[dict]:
    db_path = CLIENT_DBS.get(client)
    if not db_path:
        return None
    try:
        as_of = datetime.fromisoformat(workout["start_time_local"])
    except (TypeError, ValueError):
        as_of = None
    try:
        with _db_path_override(context_mod, db_path, "context"):
            return context_mod.get_athlete_context(as_of=as_of)
    except Exception:
        logging.exception("Could not load athlete context for %s", client)
        return None

# display workout data
def render_context(ctx: Optional[dict]) -> None:
    with st.expander("Training context (what the AI clone will see)"):
        if not ctx:
            st.caption("Training context isn't available for this workout.")
            return
        w7 = ctx.get("last_7_days") or {}
        w42 = ctx.get("last_42_days") or {}
        rec = ctx.get("recovery") or {}
        if "data" in rec and rec["data"] is None:
            st.caption(f"No sleep or recovery data was recorded for {rec.get('date', 'this day')}.")

        score = rec.get("sleep_score")
        hrv_note = {"below": "below normal", "within": "within normal",
                    "above": "above normal"}.get(rec.get("hrv_vs_normal"))
        hr_diff = rec.get("resting_hr_vs_avg")

        c = st.columns(6)
        c[0].metric("Last 7 days", f"{w7.get('sessions', '—')} sessions",
                    f"{w7.get('hours', '—')} h · load {w7.get('training_load', '—')}", delta_color="off")
        c[1].metric("Weekly avg (6 wk)", fmt_num(w42.get("weekly_avg_hours"), " h", 1),
                    f"load {w42.get('weekly_avg_load', '—')}", delta_color="off")
        c[2].metric("Load ratio", fmt_num(ctx.get("load_ratio"), digits=2))
        c[3].metric("Sleep", fmt_num(rec.get("sleep_hours"), " h", 1),
                    f"score {score:.0f}" if score is not None else None, delta_color="off")
        c[4].metric("HRV", fmt_num(rec.get("hrv_last_night"), " ms"), hrv_note, delta_color="off")
        c[5].metric("Resting HR", fmt_num(rec.get("resting_hr"), " bpm"),
                    f"{hr_diff:+.1f} vs 30-day avg" if hr_diff is not None else None, delta_color="off")

# format activity type
def pretty_type(t: Optional[str]) -> str:
    return (t or "unknown").replace("_", " ").title()

# format values
def fmt_duration(seconds) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
def fmt_num(v, suffix="", digits=0) -> str:
    return "—" if v is None else f"{v:.{digits}f}{suffix}"
def pace_or_speed(w: dict) -> Tuple[str, str]:
    d, t = w["distance_m"], w["moving_duration_s"]
    if not d or not t:
        return "Pace", "—"
    if w["activity_type"] in RUN_TYPES:
        pace = t / 60 / (d / 1000)
        return "Pace", f"{int(pace)}:{int((pace % 1) * 60):02d} /km"
    return "Avg Speed", f"{(d / 1000) / (t / 3600):.1f} km/h"

# display workout data 
def render_workout_stats(w: dict) -> None:
    st.markdown(f"**{pretty_type(w['activity_type'])}** · {(w['start_time_local'] or '')[:16]}")
    pace_label, pace_val = pace_or_speed(w)
    c = st.columns(6)
    c[0].metric("Distance", fmt_num((w["distance_m"] or 0) / 1000 if w["distance_m"] else None, " km", 2))
    c[1].metric("Duration", fmt_duration(w["moving_duration_s"]))
    c[2].metric(pace_label, pace_val)
    c[3].metric("Avg / Max HR", f"{fmt_num(w['avg_hr'])} / {fmt_num(w['max_hr'])}")
    c[4].metric("Training Load", fmt_num(w["training_load"]))
    c[5].metric("Aerobic TE", fmt_num(w["aerobic_te"], digits=1))

# main page once logged in
def main():
    st.set_page_config(page_title="Fitness Training Platform", layout="wide")
    seed_users(PEOPLE)

    user = st.session_state.get("user")
    if not user:
        render_login()
        return

    st.sidebar.title("Fitness Training Platform")
    st.sidebar.caption(f"Signed in as **{user['name']}**")
    if st.session_state.get("sync_msg"):
        st.sidebar.caption(st.session_state["sync_msg"])
    if st.sidebar.button("Log out"):
        del st.session_state["user"]
        st.session_state.pop("sync_msg", None)
        st.rerun()
    st.sidebar.markdown("---")

    if user["role"] == "client":
        trainer = next((t for t, clist in get_roster().items() if user["name"] in clist), None)
        if trainer is None:
            st.error("Your account isn't assigned to a coach yet.")
            return
        st.sidebar.caption(f"Assigned Coach: **{trainer}**")
        render_client_portal(user["name"], trainer)
    else:
        render_trainer_dashboard(user["name"], get_roster())

# display recent data
FEED_PAGE = 10
RANGES = {"30 days": 30, "90 days": 90, "6 months": 182, "1 year": 365, "All time": None}

# workout data to show
def _workout_summary(w: dict) -> str:
    parts = []
    if w["distance_m"]:
        parts.append(f"{w['distance_m'] / 1000:.2f} km")
    if w["moving_duration_s"]:
        parts.append(fmt_duration(w["moving_duration_s"]))
    if w["avg_hr"] is not None:
        parts.append(f"{w['avg_hr']:.0f} bpm avg")
    if w["training_load"] is not None:
        parts.append(f"load {w['training_load']:.0f}")
    return " · ".join(parts)

# extend feedback shown
def _more_feedback(limit_key: str, limit: int) -> None:
    st.session_state[limit_key] = limit + FEED_PAGE

# display table showing completed feedback
def _render_feedback_feed(client: str, db_path: str) -> None:
    sent = [f for f in get_feedback_map(client).values() if f["status"] == "Approved"]
    if not sent:
        st.info("Your coach hasn't sent any feedback yet.")
        return
    sent.sort(key=lambda f: f["updated_at"], reverse=True)
    by_id = {w["activity_id"]: w for w in get_workouts(db_path, limit=None)}

    limit_key = f"feed_limit_{client}"
    limit = st.session_state.get(limit_key, FEED_PAGE)
    for f in sent[:limit]:
        w = by_id.get(f["activity_id"])
        with st.container(border=True):
            if w:
                st.markdown(f"**{pretty_type(w['activity_type'])}** · {(w['start_time_local'] or '')[:10]}")
                st.caption(_workout_summary(w))
            st.write(f["final_text"])
            st.caption(f"From {f['trainer']} · {f['updated_at'][:16].replace('T', ' ')}")
    if len(sent) > limit:
        st.button("Load more", key=f"feed_more_{client}", on_click=_more_feedback, args=(limit_key, limit))

# organize history related data
def _history_frame(workouts: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(workouts)
    df["date"] = pd.to_datetime(df["start_time_local"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["type"] = df["activity_type"].apply(lambda t: pretty_type(t if isinstance(t, str) else None))
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_min"] = df["moving_duration_s"] / 60
    return df.sort_values("date")

# display client history
def _render_client_history(client: str, db_path: str) -> None:
    workouts = get_workouts(db_path, limit=None)
    if not workouts:
        st.info("No workout history yet.")
        return
    df = _history_frame(workouts)

    c1, c2 = st.columns([1, 2])
    pick = c1.selectbox("Activity", ["All activities"] + sorted(df["type"].unique()), key=f"hist_type_{client}")
    span = c2.radio("Period", list(RANGES), index=1, horizontal=True, key=f"hist_range_{client}")

    if pick != "All activities":
        df = df[df["type"] == pick]
    days = RANGES[span]
    if days:
        df = df[df["date"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=days)]
    if df.empty:
        st.info("No workouts in this period.")
        return

    m = st.columns(4)
    m[0].metric("Workouts", len(df))
    m[1].metric("Distance", f"{df['distance_km'].sum():.1f} km")
    m[2].metric("Time", f"{df['duration_min'].sum() / 60:.1f} h")
    m[3].metric("Total load", f"{df['training_load'].sum():.0f}")

    weekly = df.set_index("date").resample("W")[["distance_km", "training_load"]].sum()
    st.subheader("Weekly distance (km)")
    st.bar_chart(weekly["distance_km"])
    if weekly["training_load"].sum() > 0:
        st.subheader("Weekly training load")
        st.bar_chart(weekly["training_load"])

    hr = df.set_index("date")["avg_hr"].dropna()
    if not hr.empty:
        st.subheader("Average heart rate per workout (bpm)")
        st.line_chart(hr)

    if pick != "All activities": 
        valid = df[(df["distance_km"] > 0) & (df["duration_min"] > 0)].set_index("date")
        if not valid.empty:
            if df["activity_type"].isin(RUN_TYPES).all():
                st.subheader("Pace (min/km, lower is faster)")
                st.line_chart(valid["duration_min"] / valid["distance_km"])
            else:
                st.subheader("Average speed (km/h)")
                st.line_chart(valid["distance_km"] / (valid["duration_min"] / 60))

# display client portal
def render_client_portal(client_name: str, trainer_name: str):
    st.header(f"Client Portal")
    st.caption(f"Your assigned coach is **{trainer_name}**.")

    view = st.sidebar.radio(
        "Navigation",
        ["Latest Workout", "Coach Feedback", "History", "AI Coach Chat", "Message Trainer"],
        key=f"client_view_{client_name}",
    )
    db_path = CLIENT_DBS.get(client_name)
    latest_list = get_workouts(db_path, limit=1) if db_path else []

    if view == "Latest Workout":
        if not latest_list:
            st.info("No workouts synced yet. Once your data is synced, it will show up here.")
            return
        latest = latest_list[0]
        st.subheader("Most Recent Workout")
        render_workout_stats(latest)
        st.subheader("Coach Feedback")
        fb = get_feedback(client_name, latest["activity_id"])
        if fb and fb["status"] == "Approved":
            st.success(fb["final_text"])
            st.caption(f"From {fb['trainer']} · {fb['updated_at']}")
        else:
            st.info(f"{trainer_name} hasn't reviewed this workout yet.")
    elif view == "Coach Feedback":
        if db_path:
            _render_feedback_feed(client_name, db_path)
        else:
            st.info("Workout feedback will appear here once workout data is connected.")
    elif view == "History":
        if db_path:
            _render_client_history(client_name, db_path)
        else:
            st.info("Workout history will appear here once workout data is connected.")
    elif view == "AI Coach Chat":
        st.subheader(f"Chat with {trainer_name}'s AI Coach")
        st.info(
            "Chat with your AI coach!"
        )
        #st.caption("No AI response is generated or simulated in this placeholder.")
        st.chat_input("Ask your AI coach a question...", disabled=True, key=f"ai_chat_input_{client_name}")
    elif view == "Message Trainer":
        render_direct_messages(trainer_name, client_name, client_name)

# display trainer portal
def render_trainer_dashboard(trainer_name: str, roster: dict):
    st.header(f"Trainer Dashboard")
    clients = roster.get(trainer_name, [])
    if not clients:
        st.info("No clients have selected you as their coach yet.")
        return

    data = {}
    for c in clients:
        db_path = CLIENT_DBS.get(c)
        show_all = st.session_state.get(f"show_all_{c}", False)
        workouts = get_workouts(db_path, limit=None if show_all else RECENT) if db_path else []
        done = approved_activity_ids(c)
        pending = sum(1 for w in workouts if w["activity_id"] not in done)
        data[c] = (db_path, workouts, pending, show_all)

    active_key = f"active_client_{trainer_name}"
    radio_key = f"client_radio_{trainer_name}"
    if st.session_state.get(active_key) not in clients:
        st.session_state[active_key] = clients[0]
    if st.session_state.get(radio_key) not in clients:
        st.session_state.pop(radio_key, None)

    def remember_client():
        st.session_state[active_key] = st.session_state[radio_key]

    st.sidebar.subheader("Your Clients")
    selected = st.sidebar.radio(
        "Select a client", clients,
        index=clients.index(st.session_state[active_key]),
        format_func=lambda c: (
            f"{c} · {data[c][2]} to review" if data[c][2]
            else f"{c} · No data" if not data[c][0]
            else c
        ),
        key=radio_key, on_change=remember_client, label_visibility="collapsed",
    )
    st.session_state[active_key] = selected
    page = st.sidebar.radio(
        "Trainer Navigation", ["Review Workouts", "Workout History", "Client Messages", "AI / Knowledge Base"],
        key=f"trainer_page_{trainer_name}",
    )

    db_path, workouts, pending, show_all = data[selected]
    st.subheader(f"Client: {selected}")
    if page == "Client Messages":
        render_direct_messages(trainer_name, selected, trainer_name)
    elif page == "AI / Knowledge Base":
        st.subheader("Digital Clone Knowledge Base")
        st.info(
            "Upload your files here!"
        )
        st.file_uploader("Trainer coaching materials", type=["pdf", "txt", "docx"],
                         disabled=True, key=f"trainer_knowledge_upload_{trainer_name}")
    elif page == "Workout History":
        if not db_path:
            st.info("No workouts synced for this client yet.")
        else:
            _render_history(selected, db_path, trainer_name)
    else:
        if not db_path:
            st.info("No workouts synced for this client yet.")
        else:
            render_client_workouts(trainer_name, selected, db_path, workouts, pending, view="Review")

# button to save edited feedback and show next workout
def _approve_and_advance(trainer_name, client, aid, draft, workout_ids, sel_key, active_key, edit_key):
    save_feedback(client, aid, trainer_name, draft, st.session_state[edit_key])
    done = approved_activity_ids(client)
    pending = [i for i in workout_ids if i not in done]
    later = [i for i in pending if workout_ids.index(i) > workout_ids.index(aid)]
    nxt = (later or pending or [None])[0]
    if nxt is None:
        st.session_state["flash"] = f"Feedback sent to {client}. All caught up!"
    else:
        st.session_state[active_key] = nxt
        st.session_state.pop(sel_key, None)  
        st.session_state["flash"] = f"Feedback sent to {client}. Showing the next workout to review."

def _set_show_all(client, widget_key):
    st.session_state[f"show_all_{client}"] = st.session_state[widget_key]
def show_table(df) -> None:
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except Exception: 
        st.dataframe(df, use_container_width=True, hide_index=True)

# show workout history
def _history_rows(workouts: List[dict], fb: dict) -> List[dict]:
    rows = []
    for w in workouts:
        f = fb.get(w["activity_id"])
        reviewed = bool(f and f["status"] == "Approved")
        rows.append({
            "_id": w["activity_id"],
            "_reviewed": reviewed,
            "Date": (w["start_time_local"] or "")[:10],
            "Type": pretty_type(w["activity_type"]),
            "Distance (km)": round(w["distance_m"] / 1000, 2) if w["distance_m"] else None,
            "Duration": fmt_duration(w["moving_duration_s"]),
            "Avg HR": w["avg_hr"],
            "Load": round(w["training_load"]) if w["training_load"] is not None else None,
            "Status": "✅ Reviewed" if reviewed else "⏳ Needs review",
            "Feedback sent": (f["updated_at"][:10] if reviewed else ""),
        })
    return rows

# button to review selected workout
def _open_in_review(trainer_name: str, client: str, aid: int) -> None:
    st.session_state[f"show_all_{client}"] = True
    st.session_state.pop(f"showall_widget_{client}", None)
    st.session_state[f"active_workout_{client}"] = aid
    st.session_state.pop(f"sel_{client}", None)
    st.session_state[f"trainer_page_{trainer_name}"] = "Review Workouts"

# display workout history
def _render_history(client: str, db_path: str, trainer_name: str) -> None:
    workouts = get_workouts(db_path, limit=None) 
    if not workouts:
        st.info("No workouts synced for this client yet.")
        return
    rows = _history_rows(workouts, get_feedback_map(client))

    c1, c2 = st.columns([2, 1])
    types = sorted({r["Type"] for r in rows})
    picked = c1.multiselect("Activity type (leave empty for all)", types, key=f"hist_types_{client}")
    status = c2.radio("Show", ["All", "Reviewed", "Needs review"], key=f"hist_status_{client}")

    shown = [r for r in rows
             if (not picked or r["Type"] in picked)
             and (status == "All" or (status == "Reviewed") == r["_reviewed"])]
    st.caption(f"{len(shown)} of {len(rows)} workouts")
    if not shown:
        st.info("No workouts match these filters.")
        return

    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in shown])
    show_table(df)

    by_id = {r["_id"]: r for r in shown}
    ids = list(by_id)
    open_key = f"hist_open_{client}"
    if st.session_state.get(open_key) not in by_id:
        st.session_state.pop(open_key, None)
    aid = st.selectbox("Open a workout", ids, key=open_key,
                       format_func=lambda i: f"{by_id[i]['Date']} · {by_id[i]['Type']} · {by_id[i]['Status']}")
    workout = next(w for w in workouts if w["activity_id"] == aid)
    render_workout_stats(workout)

    f = get_feedback(client, aid)
    if f and f["status"] == "Approved":
        st.markdown("**Feedback sent to the client:**")
        st.success(f["final_text"])
        st.caption(f"Sent by {f['trainer']} · {f['updated_at']}")
        if f["ai_draft"]:
            with st.expander("AI draft that was generated for this workout"):
                st.text(f["ai_draft"])
    else:
        st.info("No feedback has been sent for this workout yet.")
    st.button("Open in Review to edit", key=f"hist_edit_{client}_{aid}",
              on_click=_open_in_review, args=(trainer_name, client, aid))

# display client workouts
def render_client_workouts(trainer_name, client, db_path, workouts, pending=0, view="Review"):
    if not is_coach_of(trainer_name, client):
        st.error("You don't have access to this client.")
        return

    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)

    show_all = st.session_state.get(f"show_all_{client}", False)
    showall_key = f"showall_widget_{client}"
    st.checkbox("Show all workouts", value=show_all, key=showall_key,
                on_change=_set_show_all, args=(client, showall_key))
    if not workouts:
        st.info("No workouts synced for this client yet.")
        return
    st.caption(f"{len(workouts)} {'workouts' if show_all else 'most recent workouts'} · "
               f"{pending} awaiting your review")

    by_id = {w["activity_id"]: w for w in workouts}
    ids = list(by_id)
    done = approved_activity_ids(client)

    sel_key = f"sel_{client}"
    active_key = f"active_workout_{client}"
    if st.session_state.get(active_key) not in by_id:
        st.session_state[active_key] = next((i for i in ids if i not in done), ids[0])
    if st.session_state.get(sel_key) not in by_id:
        st.session_state.pop(sel_key, None)

    def remember_workout():
        st.session_state[active_key] = st.session_state[sel_key]

    def option_label(i):
        w = by_id[i]
        return f"{'✅' if i in done else '⏳'} {(w['start_time_local'] or '')[:10]} · {pretty_type(w['activity_type'])}"

    aid = st.selectbox("Workout", ids, index=ids.index(st.session_state[active_key]),
                       format_func=option_label, key=sel_key, on_change=remember_workout)
    st.session_state[active_key] = aid
    chosen = by_id[aid]
    render_workout_stats(chosen)
    render_context(load_context(client, chosen))

    existing = get_feedback(client, aid)
    draft = (existing or {}).get("ai_draft") or draft_feedback(db_path, chosen)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**AI Draft:**")
        st.text_area("AI draft", value=draft, height=150, disabled=True,
                     key=f"orig_{client}_{aid}", label_visibility="collapsed")
    with col2:
        st.markdown("**Your Feedback (edit before sending):**")
        edit_key = f"edit_{client}_{aid}"
        st.text_area("Your feedback", value=(existing or {}).get("final_text") or draft, height=150,
                     key=edit_key, label_visibility="collapsed")

    st.button("Approve & Send", key=f"save_{client}_{aid}", on_click=_approve_and_advance,
              args=(trainer_name, client, aid, draft, ids, sel_key, active_key, edit_key))
    if existing and existing["status"] == "Approved":
        st.caption(f"Last sent {existing['updated_at']}")

if __name__ == "__main__":
    main()
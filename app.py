# ── Gevent monkey patch — must be first, before all other imports ─────────────
from gevent import monkey
monkey.patch_all()

"""
app.py — Flask + Socket.IO server for The Resistance: Avalon

Environment variables:
  SECRET_KEY    Flask secret key (change in production)
  PORT          Port to bind to (default 5000)
  REDIS_URL     Optional Redis URL for multi-process scaling
                e.g. redis://redis:6379
                When unset, the app runs in single-process mode (fine for dev / small deploys)
"""

import os
import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

from game import AvalonGame, GamePhase

# ─── App & SocketIO setup ─────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "avalon-super-secret-change-me")

# Redis message queue is optional.
# Without it the app runs fine on a single process (gevent async).
# With it you can run multiple workers (e.g. gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 4)
_redis_url = os.environ.get("REDIS_URL", None)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
    message_queue=_redis_url,      # None → single-process; URL → Redis pub/sub
)

# ── In-memory stores ──────────────────────────────────────────────────────────
# For multi-process/Redis deployments you would also want to externalise these
# (e.g. Redis hashes). For now they live in memory on the single process.
games:        dict[str, AvalonGame] = {}   # room_code → AvalonGame
player_rooms: dict[str, str]        = {}   # sid       → room_code


# ─── Helpers ─────────────────────────────────────────────────────────────────

def generate_room_code() -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=6))
        if code not in games:
            return code


def emit_game_state(room_code: str):
    """
    Push a personalised game_state to every player in the room.
    Each player's secret role info is only in their own copy.
    """
    game = games.get(room_code)
    if not game:
        return
    for sid in list(game.players.keys()):
        socketio.emit("game_state", game.get_player_state(sid), to=sid)


def notify(room_code: str, message: str, kind: str = "info", skip_sid: str = None):
    """
    Broadcast a toast notification to all players in a room.
    kind: "info" | "success" | "error" | "warning"
    """
    payload = {"message": message, "kind": kind}
    if skip_sid:
        # Iterate and skip one sid manually (socketio.emit skip_sid kwarg is unreliable cross-version)
        game = games.get(room_code)
        if game:
            for sid in list(game.players.keys()):
                if sid != skip_sid:
                    socketio.emit("notification", payload, to=sid)
    else:
        socketio.emit("notification", payload, to=room_code)


# ─── HTTP Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/game")
def game_page():
    return render_template("game.html")


# ─── Socket.IO lifecycle ──────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    join_room(request.sid)   # private unicast room for this client


@socketio.on("disconnect")
def on_disconnect():
    sid       = request.sid
    room_code = player_rooms.pop(sid, None)
    if room_code and room_code in games:
        game = games[room_code]
        if sid in game.players:
            name = game.players[sid].name
            game.players[sid].connected = False
            emit_game_state(room_code)
            notify(room_code, f"⚠ {name} disconnected.", "warning", skip_sid=sid)


# ─── Lobby ────────────────────────────────────────────────────────────────────

@socketio.on("create_room")
def on_create_room(data):
    name = (data.get("name") or "").strip()
    if not name or len(name) > 20:
        emit("error", {"message": "Name must be 1–20 characters."})
        return

    room_code        = generate_room_code()
    game             = AvalonGame(room_code)
    games[room_code] = game

    ok, err = game.add_player(request.sid, name)
    if not ok:
        emit("error", {"message": err})
        return

    player_rooms[request.sid] = room_code
    join_room(room_code)
    emit("room_created", {"room_code": room_code})
    emit_game_state(room_code)


@socketio.on("join_room_request")
def on_join_room(data):
    name      = (data.get("name") or "").strip()
    room_code = (data.get("room_code") or "").strip().upper()

    if not name or len(name) > 20:
        emit("error", {"message": "Name must be 1–20 characters."})
        return
    if room_code not in games:
        emit("error", {"message": "Room not found. Check the code and try again."})
        return

    game = games[room_code]

    # Reconnection: name matches an existing player
    existing = next(
        (p for p in game.players.values() if p.name.lower() == name.lower()), None
    )
    if existing:
        old_sid = existing.sid
        if old_sid != request.sid:
            game.reconnect_player(old_sid, request.sid)
            player_rooms.pop(old_sid, None)
        player_rooms[request.sid] = room_code
        join_room(room_code)
        emit("joined_room", {"room_code": room_code, "reconnected": True})
        emit_game_state(room_code)
        notify(room_code, f"🔄 {name} reconnected.", "info", skip_sid=request.sid)
        return

    # New player
    ok, err = game.add_player(request.sid, name)
    if not ok:
        emit("error", {"message": err})
        return

    player_rooms[request.sid] = room_code
    join_room(room_code)
    emit("joined_room", {"room_code": room_code, "reconnected": False})
    emit_game_state(room_code)
    notify(room_code, f"👤 {name} joined the room.", "info", skip_sid=request.sid)


@socketio.on("start_game")
def on_start_game():
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)

    if not game:
        emit("error", {"message": "You are not in a room."})
        return
    if sid != game.host_sid:
        emit("error", {"message": "Only the host can start the game."})
        return

    ok, err = game.start_game(sid)
    if not ok:
        emit("error", {"message": err})
        return

    if game.phase == GamePhase.MODERATOR_CONFIG:
        notify(room_code, "🎮 Host is setting up the moderator role…")
    elif game.phase == GamePhase.ROLE_CONFIG:
        notify(room_code, "🎲 Host is choosing the optional roles…")
    else:
        notify(room_code, "🎮 Game starting! Check your role card.")

    emit_game_state(room_code)


# ─── Role Configuration (8+ players only) ────────────────────────────────────

@socketio.on("configure_roles")
def on_configure_roles(data):
    """
    Host submits which optional evil roles to include.
    data = { "chosen_roles": ["Mordred"] }  (list of Role.value strings)
    """
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)

    if not game:
        emit("error", {"message": "You are not in a room."})
        return
    if sid != game.host_sid:
        emit("error", {"message": "Only the host can configure roles."})
        return

    chosen = data.get("chosen_roles", [])
    ok, err = game.configure_roles(sid, chosen)
    if not ok:
        emit("error", {"message": err})
        return

    chosen_names = chosen if chosen else ["none — plain Minions only"]
    notify(room_code, f"🎮 Optional roles configured. Game starting! Check your role card.")
    emit_game_state(room_code)


# ─── Moderator Configuration (6+ players) ────────────────────────────────────

@socketio.on("configure_moderator")
def on_configure_moderator(data):
    """
    Host chooses moderator mode and nominates a moderator.
    data = { "mode": "active"|"passive", "moderator_sid": "<sid>" }
    """
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        emit("error", {"message": "You are not in a room."})
        return

    mode          = data.get("mode", "")
    moderator_sid = data.get("moderator_sid", "")
    ok, err       = game.configure_moderator(sid, mode, moderator_sid)
    if not ok:
        emit("error", {"message": err})
        return

    mod_name = game.players[moderator_sid].name
    if mode == "passive":
        notify(room_code,
               f"🖥 {mod_name} is the passive moderator (big screen). "
               f"Game starting! Check your role card.")
    else:
        notify(room_code,
               f"⚙ {mod_name} is the active moderator. Game starting! Check your role card.")

    if game.phase == GamePhase.ROLE_CONFIG:
        notify(room_code, "🎲 Host is choosing the optional roles…")

    emit_game_state(room_code)


@socketio.on("assign_moderator")
def on_assign_moderator(data):
    """
    Transfer moderator status to another player.
    data = { "new_moderator_sid": "<sid>" }
    Only callable by host or current moderator, in LOBBY or PREGAME.
    """
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        emit("error", {"message": "You are not in a room."})
        return

    new_mod_sid = data.get("new_moderator_sid", "")
    ok, err     = game.assign_moderator(sid, new_mod_sid)
    if not ok:
        emit("error", {"message": err})
        return

    new_name = game.players[new_mod_sid].name
    notify(room_code, f"⚙ {new_name} is now the moderator.", "info")
    emit_game_state(room_code)


# ─── Play Again ───────────────────────────────────────────────────────────────

@socketio.on("play_again")
def on_play_again():
    """
    Host resets the game state after GAME_OVER. Players stay in the room.
    Transitions to PREGAME so new players can still join before the next start.
    """
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        emit("error", {"message": "You are not in a room."})
        return

    ok, err = game.reset_for_next_game(sid)
    if not ok:
        emit("error", {"message": err})
        return

    notify(room_code, "🔄 New game starting! Waiting for host to begin…", "info")
    emit_game_state(room_code)


# ─── Role Reveal ──────────────────────────────────────────────────────────────

@socketio.on("player_ready")
def on_player_ready():
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return

    all_ready = game.mark_player_ready(sid)
    emit_game_state(room_code)
    if all_ready:
        notify(room_code, "⚔ All players ready, let the game begin!")


# ─── Team Proposal ────────────────────────────────────────────────────────────

@socketio.on("propose_team")
def on_propose_team(data):
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return

    team_sids = data.get("team", [])
    ok, err   = game.propose_team(sid, team_sids)
    if not ok:
        emit("error", {"message": err})
        return

    leader_name  = game.players[sid].name
    team_names   = ", ".join(game.players[s].name for s in team_sids)
    notify(room_code,
           f"📋 {leader_name} proposed: {team_names}. Vote now!",
           "info", skip_sid=sid)
    emit_game_state(room_code)


# ─── Team Vote ────────────────────────────────────────────────────────────────

@socketio.on("vote_team")
def on_vote_team(data):
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return

    approve = bool(data.get("approve", False))
    ok, err = game.submit_team_vote(sid, approve)
    if not ok:
        emit("error", {"message": err})
        return

    if game.all_team_votes_in():
        result = game.resolve_team_vote()
        if result["approved"]:
            team = ", ".join(result["proposed_team_names"])
            notify(room_code,
                   f"✓ Team approved ({result['approvals']}–{result['rejections']})! "
                   f"Mission begins: {team}",
                   "success")
        else:
            left = 5 - result["consecutive_rejections"]
            if left > 0:
                notify(room_code,
                       f"✗ Team rejected ({result['approvals']}–{result['rejections']}). "
                       f"{left} rejection(s) left before Evil auto-wins.",
                       "warning")
            # game_over case handled by phase transition

    emit_game_state(room_code)


@socketio.on("advance_from_vote_result")
def on_advance_from_vote_result():
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return
    if not game.can_advance(sid):
        emit("error", {"message": "Only the host or moderator can advance."})
        return
    game.advance_from_vote_result()
    emit_game_state(room_code)


# ─── Mission ──────────────────────────────────────────────────────────────────

@socketio.on("vote_mission")
def on_vote_mission(data):
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return

    success = bool(data.get("success", True))
    ok, err = game.submit_mission_vote(sid, success)
    if not ok:
        emit("error", {"message": err})
        return

    if game.all_mission_votes_in():
        result = game.resolve_mission()
        n      = result["mission_number"]
        if result["succeeded"]:
            notify(room_code,
                   f"✓ Mission {n} succeeded! Good leads {result['good_wins']}–{result['evil_wins']}.",
                   "success")
        else:
            notify(room_code,
                   f"✗ Mission {n} failed! Evil leads {result['evil_wins']}–{result['good_wins']}.",
                   "error")

        if result["next_phase"] == "assassination":
            notify(room_code,
                   "🗡 Good wins 3 missions! The Assassin must now identify Merlin…",
                   "warning")

    emit_game_state(room_code)


@socketio.on("advance_from_mission_result")
def on_advance_from_mission_result():
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return
    if not game.can_advance(sid):
        emit("error", {"message": "Only the host or moderator can advance."})
        return
    game.advance_from_mission_result()
    emit_game_state(room_code)


# ─── Assassination ────────────────────────────────────────────────────────────

@socketio.on("assassinate")
def on_assassinate(data):
    sid       = request.sid
    room_code = player_rooms.get(sid)
    game      = games.get(room_code)
    if not game:
        return

    target_sid = data.get("target_sid", "")
    ok, result = game.submit_assassination(sid, target_sid)
    if not ok:
        emit("error", {"message": result.get("error", "Assassination failed.")})
        return

    if result["hit_merlin"]:
        notify(room_code,
               f"💀 The Assassin found Merlin! Evil wins!",
               "error")
    else:
        notify(room_code,
               f"🎉 The Assassin missed! Good wins!",
               "success")

    emit_game_state(room_code)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Avalon server on port {port}")
    if _redis_url:
        print(f"Redis message queue: {_redis_url}")
    else:
        print("Running in single-process mode (no Redis)")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)

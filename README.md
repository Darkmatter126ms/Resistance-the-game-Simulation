# The Resistance: Avalon, Online Edition

A real-time multiplayer game engine built from scratch in Python. The interesting part is not the game itself but the engineering underneath: a pure state machine with server-enforced information asymmetry, concurrent session management, and a WebSocket event bus that keeps 11 clients consistent without a single client holding privileged state.

---

## Why this project

Most multiplayer game repos are thin wrappers around a game loop. This one treats correctness as a first-class constraint.

Every player receives a personalised view of the game state, computed server-side, scoped strictly to what their role is permitted to know. Merlin sees evil players but not Mordred. Percival's label changes dynamically depending on whether Morgana is in the game. The passive moderator gets a dashboard view with no role information at all. None of this logic lives on the client.

The result is a system where cheating by inspecting network traffic yields nothing useful, and where the game engine can be unit-tested completely independently of Flask, sockets, or any I/O.

---

## Technical highlights

**Pure game engine (`game.py`)**

The core logic has zero web framework dependencies. It is a deterministic state machine: given a state and an action, it produces a new state and a result. Every phase transition, vote resolution, mission outcome, and role assignment is a pure function that can be called in a test without spinning up a server.

```python
# All business logic is testable in isolation
g = AvalonGame("room_001")
for i in range(7): g.add_player(f"s{i}", f"Player{i}")
g.start_game("s0")
g.configure_moderator("s0", "passive", "s6")
g.configure_roles("s0", ["Mordred"])
```

**Information asymmetry, enforced server-side**

Each client receives a personalised copy of game state via `get_player_state(sid)`. The server computes what each player is allowed to see before emitting:

- Merlin: all evil players except Mordred
- Percival: Merlin only (6 players), or Merlin and Morgana indistinguishably (7+ players)
- Evil: each other, but not Oberon
- Oberon: nobody
- Passive moderator: public game state only, no role information

No secret information ever reaches the wrong client.

**Concurrent session management**

Multiple rooms run simultaneously in a single process. Each room is an independent `AvalonGame` instance with its own state. Socket.IO rooms handle message routing; each player joins both the shared room channel and a private unicast channel for personalised state delivery.

**Redis pub/sub for horizontal scaling**

Socket.IO is configured to use Redis as a message queue when `REDIS_URL` is set. This allows multiple worker processes to handle connections while still delivering personalised state to the correct client, regardless of which worker holds that connection.

**Role configuration as a decision tree**

Roles unlock progressively by active player count and optional roles are chosen by the host before each game. The configuration system separates mandatory roles from optional ones, validates constraints (e.g. 11 players requires a passive moderator), and falls back to plain Minions for unchosen optional slots.

| Active players | Evil count | Optional roles available |
|----------------|-----------|--------------------------|
| 5 | 2 | none |
| 6 | 2 | none |
| 7 | 3 | none |
| 8-9 | 3 | Mordred |
| 10 | 4 | Mordred, Oberon |

**Advisory timer system**

Timers are computed client-side against a per-phase duration that scales with player count. The server never enforces them. This keeps the server stateless with respect to time and avoids race conditions between timer expiry and legitimate game actions, while still providing social pressure to keep the game moving.

| Players | Proposal timer | Vote timer |
|---------|---------------|------------|
| 5 | 2:30 | 1:00 |
| 7 | 3:30 | 1:30 |
| 10 | 5:00 | 2:00 |

---

## Stack

- **Python 3.12**, Flask, Flask-SocketIO
- **gevent** for async I/O and WebSocket handling
- **Redis** for optional horizontal scaling via pub/sub
- Vanilla JS frontend, no client-side framework
- Docker + Docker Compose for one-command deployment

---

## Running it

```bash
git clone https://github.com/yourusername/avalon
cd avalon
docker compose up --build
# open http://localhost:5000
```

Without Docker:

```bash
pip install -r requirements.txt
python app.py
```

Redis is optional. Without `REDIS_URL` set, the server runs single-process, which handles multiple simultaneous rooms comfortably at friend-group scale.

For remote players via ngrok:

```bash
# terminal 1
docker compose up --build

# terminal 2
ngrok http 5000
# share the https://xxx.ngrok-free.app URL
```

---

## Project structure

```
avalon/
├── game.py           # State machine: zero Flask dependencies, fully unit-testable
├── app.py            # Flask + Socket.IO: event handlers, session routing
├── templates/
│   ├── index.html    # Lobby
│   └── game.html     # Game interface
├── static/
│   ├── css/style.css
│   └── js/game.js
├── Dockerfile
└── docker-compose.yml
```

---

## Testing the engine

Because `game.py` has no I/O dependencies, the full game loop is testable without a running server:

```python
from game import AvalonGame, GamePhase, Role

def test_full_loop(n=7):
    g = AvalonGame("test")
    for i in range(n): g.add_player(f"s{i}", f"P{i}")
    g.start_game("s0")
    g.configure_moderator("s0", "active", "s1")

    for _ in range(5):
        if g.phase != GamePhase.TEAM_PROPOSAL: break
        leader = g.current_leader.sid
        team   = g.player_order[:g.mission_team_size]
        g.propose_team(leader, team)
        for sid in g.players: g.submit_team_vote(sid, True)
        g.resolve_team_vote()
        g.advance_from_vote_result()
        for sid in team: g.submit_mission_vote(sid, True)
        g.resolve_mission()
        g.advance_from_mission_result()
```

---

## License

MIT

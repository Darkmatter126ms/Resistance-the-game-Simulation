"""
game.py — Core game logic for The Resistance: Avalon
No Flask dependencies; can be unit-tested independently.
"""

import random
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ─── Enums ────────────────────────────────────────────────────────────────────

class Role(Enum):
    MERLIN          = "Merlin"
    PERCIVAL        = "Percival"
    LOYAL_SERVANT   = "Loyal Servant"
    ASSASSIN        = "Assassin"
    MORGANA         = "Morgana"
    MORDRED         = "Mordred"
    OBERON          = "Oberon"
    MINION          = "Minion of Mordred"


class GamePhase(Enum):
    LOBBY               = "lobby"
    PREGAME             = "pregame"           # between games — players stay, host restarts
    MODERATOR_CONFIG    = "moderator_config"  # host picks mod mode + nominates (6+ players)
    ROLE_CONFIG         = "role_config"       # host picks optional evil roles (8+ active players)
    ROLE_REVEAL         = "role_reveal"
    TEAM_PROPOSAL       = "team_proposal"
    TEAM_VOTE           = "team_vote"
    TEAM_VOTE_RESULT    = "team_vote_result"
    MISSION             = "mission"
    MISSION_RESULT      = "mission_result"
    ASSASSINATION       = "assassination"
    GAME_OVER           = "game_over"


# ─── Constants ────────────────────────────────────────────────────────────────

ROLE_TEAM: Dict[Role, str] = {
    Role.MERLIN:        "good",
    Role.PERCIVAL:      "good",
    Role.LOYAL_SERVANT: "good",
    Role.ASSASSIN:      "evil",
    Role.MORGANA:       "evil",
    Role.MORDRED:       "evil",
    Role.OBERON:        "evil",
    Role.MINION:        "evil",
}

ROLE_DESCRIPTIONS: Dict[Role, str] = {
    Role.MERLIN: (
        "You know who the Evil players are...except the Mordred, who is hidden from you. "
        "Guide the Good side to 3 mission successes, but stay hidden. "
        "If Good wins, the Assassin gets one shot at identifying you. If they succeed, Evil wins."
    ),
    Role.PERCIVAL: (
        "You can see two players labelled 'Merlin?'. One is truly Merlin, the other is Morgana. "
        "Your job is to figure out which is which and protect the real Merlin."
    ),
    Role.LOYAL_SERVANT: (
        "You are a Loyal Servant of Arthur. You have no special information. "
        "Use logic, observation, and social deduction to identify and expose the Evil players."
    ),
    Role.ASSASSIN: (
        "You know your Evil teammates (except Oberon). "
        "Help Evil fail 3 missions or, if Good wins, you get one final chance: "
        "correctly identify and assassinate Merlin to steal the victory for Evil."
    ),
    Role.MORGANA: (
        "You appear as 'Merlin?' to Percival, sowing confusion and making it harder "
        "for him to identify the real Merlin. You know your Evil teammates (except Oberon). "
        "Help Evil sabotage missions."
    ),
    Role.MORDRED: (
        "You are the most dangerous Evil player: Merlin cannot see you. "
        "He doesn't know you are Evil. You know your Evil teammates (except Oberon). "
        "Use this hidden advantage to manipulate missions without drawing Merlin's suspicion."
    ),
    Role.OBERON: (
        "You are Evil, but you are isolated. You do not know who your Evil teammates are, "
        "and they do not know you. Act alone to sabotage missions without drawing "
        "attention to the others."
    ),
    Role.MINION: (
        "You are a Minion of Mordred. You know your Evil teammates (except Oberon). "
        "Work with the Assassin and other Evil players to fail 3 missions "
        "without being detected."
    ),
}

OPTIONAL_ROLE_NOTES: Dict[Role, dict] = {
    Role.MORDRED: {
        "headline":   "Merlin's blind spot",
        "detail": (
            "Merlin cannot see Mordred as Evil. While every other Evil player is visible "
            "to Merlin during the night phase, Mordred operates freely without suspicion. "
            "Recommended once players are comfortable with the base game."
        ),
        "difficulty": "Harder for Good",
    },
    Role.OBERON: {
        "headline":   "The wild card",
        "detail": (
            "Oberon is Evil but completely isolated: he does not see his Evil allies "
            "and they cannot see him. He must sabotage missions alone, making him "
            "unpredictable for both teams. Best for groups that want maximum chaos."
        ),
        "difficulty": "Chaotic for both sides",
    },
}

# ── Role assignments per ACTIVE player count (max 10 active at once) ──────────
PLAYER_CONFIG: Dict[int, dict] = {
    5:  {"evil_count": 2, "good_specials": [Role.MERLIN],
         "evil_specials": [Role.ASSASSIN], "optional_evil": []},
    6:  {"evil_count": 2, "good_specials": [Role.MERLIN, Role.PERCIVAL],
         "evil_specials": [Role.ASSASSIN], "optional_evil": []},
    7:  {"evil_count": 3, "good_specials": [Role.MERLIN, Role.PERCIVAL],
         "evil_specials": [Role.ASSASSIN, Role.MORGANA], "optional_evil": []},
    8:  {"evil_count": 3, "good_specials": [Role.MERLIN, Role.PERCIVAL],
         "evil_specials": [Role.ASSASSIN, Role.MORGANA], "optional_evil": [Role.MORDRED]},
    9:  {"evil_count": 3, "good_specials": [Role.MERLIN, Role.PERCIVAL],
         "evil_specials": [Role.ASSASSIN, Role.MORGANA], "optional_evil": [Role.MORDRED]},
    10: {"evil_count": 4, "good_specials": [Role.MERLIN, Role.PERCIVAL],
         "evil_specials": [Role.ASSASSIN, Role.MORGANA],
         "optional_evil": [Role.MORDRED, Role.OBERON]},
}

# ── Mission sizes per ACTIVE player count ─────────────────────────────────────
# (team_size, fails_needed). Mission 4 at 7+ players needs 2 fails.
MISSION_CONFIG: Dict[int, List[Tuple[int, int]]] = {
    5:  [(2,1), (3,1), (2,1), (3,1), (3,1)],
    6:  [(2,1), (3,1), (4,1), (3,1), (4,1)],
    7:  [(2,1), (3,1), (3,1), (4,2), (4,1)],
    8:  [(3,1), (4,1), (4,1), (5,2), (5,1)],
    9:  [(3,1), (4,1), (4,1), (5,2), (5,1)],
    10: [(3,1), (4,1), (4,1), (5,2), (5,1)],
}

# ── Advisory timers in seconds, per active player count ───────────────────────
# Client displays only — server never enforces.
TIMER_CONFIG: Dict[int, dict] = {
    5:  {"proposal": 150, "vote": 60},
    6:  {"proposal": 180, "vote": 75},
    7:  {"proposal": 210, "vote": 90},
    8:  {"proposal": 240, "vote": 90},
    9:  {"proposal": 270, "vote": 120},
    10: {"proposal": 300, "vote": 120},
}

MAX_CONSECUTIVE_REJECTIONS = 5
MIN_ACTIVE_PLAYERS         = 5
MAX_TOTAL_PLAYERS          = 11   # 10 active + 1 passive moderator


# ─── Player ───────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, sid: str, name: str):
        self.sid          = sid
        self.name         = name
        self.role:        Optional[Role] = None
        self.connected    = True
        self.is_spectator = False   # True only for passive moderator


# ─── Game ─────────────────────────────────────────────────────────────────────

class AvalonGame:
    def __init__(self, room_code: str):
        self.room_code     = room_code
        self.players:      Dict[str, Player] = {}
        self.player_order: List[str] = []        # active (non-spectator) sids only
        self.phase         = GamePhase.LOBBY
        self.host_sid:     Optional[str] = None

        # ── Moderator ─────────────────────────────────────────────────────────
        # mode: "none" | "active" | "passive"
        self.moderator_mode: str           = "none"
        self.moderator_sid:  Optional[str] = None

        # ── Optional role choices (set during ROLE_CONFIG) ────────────────────
        self.optional_roles_chosen: List[Role] = []

        # ── Mission tracking ──────────────────────────────────────────────────
        self.current_mission_index = 0
        self.mission_results:      List[str] = []

        # ── Round state ───────────────────────────────────────────────────────
        self.leader_index           = 0
        self.consecutive_rejections = 0
        self.proposed_team:  List[str] = []
        self.team_votes:     Dict[str, bool] = {}
        self.mission_votes:  Dict[str, str]  = {}

        # ── Stored results ────────────────────────────────────────────────────
        self.last_vote_result:    Optional[dict] = None
        self.last_mission_result: Optional[dict] = None

        # ── Ready tracking ────────────────────────────────────────────────────
        self._role_reveal_ready: set = set()

        # ── Assassination ─────────────────────────────────────────────────────
        self.assassin_sid: Optional[str] = None

        # ── Outcome ───────────────────────────────────────────────────────────
        self.winner:     Optional[str] = None
        self.win_reason: Optional[str] = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def num_players(self) -> int:
        return len(self.players)

    @property
    def active_player_count(self) -> int:
        """Players who actually play — excludes passive moderator."""
        return sum(1 for p in self.players.values() if not p.is_spectator)

    @property
    def current_leader(self) -> Optional[Player]:
        if not self.player_order:
            return None
        return self.players[self.player_order[self.leader_index % len(self.player_order)]]

    @property
    def current_mission_config(self) -> Tuple[int, int]:
        n = self.active_player_count
        if n < 5 or n > 10:
            return (0, 1)
        return MISSION_CONFIG[n][self.current_mission_index]

    @property
    def mission_team_size(self) -> int:
        return self.current_mission_config[0]

    @property
    def mission_fails_required(self) -> int:
        return self.current_mission_config[1]

    def can_advance(self, sid: str) -> bool:
        """True if this sid may advance game phases (host or moderator)."""
        return sid in (self.host_sid, self.moderator_sid)

    # ── Lobby & Pregame ───────────────────────────────────────────────────────

    def add_player(self, sid: str, name: str) -> Tuple[bool, str]:
        if self.phase not in (GamePhase.LOBBY, GamePhase.PREGAME):
            return False, "Game already in progress."
        if len(self.players) >= MAX_TOTAL_PLAYERS:
            return False, f"Room is full (max {MAX_TOTAL_PLAYERS} players)."
        if any(p.name.lower() == name.lower() for p in self.players.values()):
            return False, "That name is already taken."
        if not name or len(name) > 20:
            return False, "Name must be 1–20 characters."
        player = Player(sid, name)
        self.players[sid] = player
        if self.host_sid is None:
            self.host_sid = sid
        return True, ""

    def reconnect_player(self, old_sid: str, new_sid: str) -> bool:
        if old_sid not in self.players:
            return False
        player           = self.players.pop(old_sid)
        player.sid       = new_sid
        player.connected = True
        self.players[new_sid] = player

        if old_sid in self.player_order:
            self.player_order[self.player_order.index(old_sid)] = new_sid
        if self.host_sid      == old_sid: self.host_sid      = new_sid
        if self.assassin_sid  == old_sid: self.assassin_sid  = new_sid
        if self.moderator_sid == old_sid: self.moderator_sid = new_sid
        if old_sid in self.proposed_team:
            self.proposed_team[self.proposed_team.index(old_sid)] = new_sid
        if old_sid in self.team_votes:
            self.team_votes[new_sid] = self.team_votes.pop(old_sid)
        if old_sid in self.mission_votes:
            self.mission_votes[new_sid] = self.mission_votes.pop(old_sid)
        if old_sid in self._role_reveal_ready:
            self._role_reveal_ready.discard(old_sid)
            self._role_reveal_ready.add(new_sid)
        return True

    # ── Game Start ────────────────────────────────────────────────────────────

    def start_game(self, requester_sid: str) -> Tuple[bool, str]:
        if self.phase not in (GamePhase.LOBBY, GamePhase.PREGAME):
            return False, "Game already in progress."
        if requester_sid != self.host_sid:
            return False, "Only the host can start the game."
        if self.num_players < MIN_ACTIVE_PLAYERS:
            return False, f"Need at least {MIN_ACTIVE_PLAYERS} players."
        if self.num_players > MAX_TOTAL_PLAYERS:
            return False, f"Maximum {MAX_TOTAL_PLAYERS} players."

        if self.num_players >= 6:
            # Host must choose moderator mode for 6+ players
            self.phase = GamePhase.MODERATOR_CONFIG
        else:
            # 5 players — skip moderator config entirely
            self.moderator_mode = "none"
            self._advance_past_moderator_config()
        return True, ""

    # ── Moderator Configuration ───────────────────────────────────────────────

    def configure_moderator(
        self,
        requester_sid: str,
        mode:          str,
        moderator_sid: str,
    ) -> Tuple[bool, str]:
        """
        Host nominates a moderator and chooses active vs passive.
        mode="active"  → moderator plays a role, also manages game pace.
        mode="passive" → moderator is a spectator (no role, no vote, big screen).
        """
        if self.phase != GamePhase.MODERATOR_CONFIG:
            return False, "Not in moderator configuration phase."
        if requester_sid != self.host_sid:
            return False, "Only the host can configure the moderator."
        if mode not in ("active", "passive"):
            return False, "Mode must be 'active' or 'passive'."
        if moderator_sid not in self.players:
            return False, "Invalid moderator selection."
        if self.num_players == 11 and mode != "passive":
            return False, "With 11 players a passive moderator is required."
        if mode == "passive" and (self.num_players - 1) < MIN_ACTIVE_PLAYERS:
            return False, f"Need at least {MIN_ACTIVE_PLAYERS} active players after removing moderator."

        # Clear any spectator state from a previous game
        for p in self.players.values():
            p.is_spectator = False

        self.moderator_mode = mode
        self.moderator_sid  = moderator_sid
        if mode == "passive":
            self.players[moderator_sid].is_spectator = True

        self._advance_past_moderator_config()
        return True, ""

    def assign_moderator(self, requester_sid: str, new_moderator_sid: str) -> Tuple[bool, str]:
        """Transfer moderator title in LOBBY or PREGAME. Host always gets it back after game."""
        if self.phase not in (GamePhase.LOBBY, GamePhase.PREGAME):
            return False, "Moderator can only be reassigned in the lobby or pregame."
        if requester_sid not in (self.host_sid, self.moderator_sid):
            return False, "Only the host or current moderator can reassign."
        if new_moderator_sid not in self.players:
            return False, "Invalid player."
        self.moderator_sid = new_moderator_sid
        return True, ""

    def _advance_past_moderator_config(self):
        """Pick next phase based on active player count."""
        n = self.active_player_count
        if PLAYER_CONFIG.get(n, {}).get("optional_evil"):
            self.phase = GamePhase.ROLE_CONFIG
        else:
            self._assign_roles()
            self.leader_index = random.randint(0, n - 1)
            self.phase        = GamePhase.ROLE_REVEAL

    # ── Role Configuration ────────────────────────────────────────────────────

    def configure_roles(self, requester_sid: str, chosen_role_values: List[str]) -> Tuple[bool, str]:
        if self.phase != GamePhase.ROLE_CONFIG:
            return False, "Not in role configuration phase."
        if requester_sid != self.host_sid:
            return False, "Only the host can configure roles."

        n         = self.active_player_count
        available = PLAYER_CONFIG[n]["optional_evil"]
        self.optional_roles_chosen = [r for r in available if r.value in chosen_role_values]

        self._assign_roles()
        self.leader_index = random.randint(0, n - 1)
        self.phase        = GamePhase.ROLE_REVEAL
        return True, ""

    def _assign_roles(self):
        """Assign roles to active players only. player_order excludes spectator."""
        active_sids = [sid for sid, p in self.players.items() if not p.is_spectator]
        n           = len(active_sids)
        config      = PLAYER_CONFIG[n]
        evil_count  = config["evil_count"]
        good_count  = n - evil_count

        good_roles    = list(config["good_specials"]) + \
                        [Role.LOYAL_SERVANT] * (good_count - len(config["good_specials"]))
        evil_specials = list(config["evil_specials"]) + list(self.optional_roles_chosen)
        evil_roles    = evil_specials + [Role.MINION] * (evil_count - len(evil_specials))

        all_roles = good_roles + evil_roles
        random.shuffle(all_roles)
        random.shuffle(active_sids)
        self.player_order = active_sids

        for i, sid in enumerate(self.player_order):
            self.players[sid].role = all_roles[i]
            if all_roles[i] == Role.ASSASSIN:
                self.assassin_sid = sid

    # ── Night Knowledge ───────────────────────────────────────────────────────

    def get_night_knowledge(self, sid: str) -> dict:
        player = self.players.get(sid)
        if not player or not player.role:
            return {"known_players": {}}
        role  = player.role
        known: Dict[str, dict] = {}

        if role == Role.MERLIN:
            for s, p in self.players.items():
                if s != sid and p.role and ROLE_TEAM[p.role] == "evil" and p.role != Role.MORDRED:
                    known[s] = {"name": p.name, "label": "Evil"}
        elif role == Role.PERCIVAL:
            # Check if Morgana is actually in this game.
            # At 6p Morgana is NOT included — Percival sees only Merlin (confirmed).
            # At 7p+ Morgana IS included — both are ambiguous, labelled "Merlin?".
            morgana_in_game = any(p.role == Role.MORGANA for p in self.players.values())
            for s, p in self.players.items():
                if s != sid and p.role in (Role.MERLIN, Role.MORGANA):
                    label = "Merlin?" if morgana_in_game else "Merlin"
                    known[s] = {"name": p.name, "label": label}
        elif role in (Role.ASSASSIN, Role.MORGANA, Role.MORDRED, Role.MINION):
            for s, p in self.players.items():
                if s != sid and p.role and ROLE_TEAM[p.role] == "evil" and p.role != Role.OBERON:
                    known[s] = {"name": p.name, "label": "Evil Ally"}
        return {"known_players": known}

    # ── Role Reveal ───────────────────────────────────────────────────────────

    def mark_player_ready(self, sid: str) -> bool:
        if self.phase != GamePhase.ROLE_REVEAL:
            return False
        player = self.players.get(sid)
        if not player or player.is_spectator:
            return False
        self._role_reveal_ready.add(sid)
        if len(self._role_reveal_ready) >= self.active_player_count:
            self._role_reveal_ready.clear()
            self._start_team_proposal()
            return True
        return False

    def _start_team_proposal(self):
        self.proposed_team = []
        self.team_votes    = {}
        self.mission_votes = {}
        self.phase         = GamePhase.TEAM_PROPOSAL

    # ── Team Proposal ─────────────────────────────────────────────────────────

    def propose_team(self, sid: str, team_sids: List[str]) -> Tuple[bool, str]:
        if self.phase != GamePhase.TEAM_PROPOSAL:
            return False, "Not in team proposal phase."
        if self.current_leader is None or sid != self.current_leader.sid:
            return False, "Only the current leader can propose a team."
        if len(team_sids) != self.mission_team_size:
            return False, f"Team must have exactly {self.mission_team_size} player(s)."
        if len(set(team_sids)) != len(team_sids):
            return False, "Duplicate players in proposal."
        if not all(s in self.players for s in team_sids):
            return False, "Unknown player in proposal."
        if any(self.players[s].is_spectator for s in team_sids):
            return False, "Cannot include the moderator in a mission team."
        self.proposed_team = team_sids
        self.phase         = GamePhase.TEAM_VOTE
        return True, ""

    # ── Team Vote ─────────────────────────────────────────────────────────────

    def submit_team_vote(self, sid: str, approve: bool) -> Tuple[bool, str]:
        if self.phase != GamePhase.TEAM_VOTE:
            return False, "Not in team vote phase."
        player = self.players.get(sid)
        if not player:
            return False, "Unknown player."
        if player.is_spectator:
            return False, "The moderator does not vote on teams."
        if sid in self.team_votes:
            return False, "Already voted."
        self.team_votes[sid] = approve
        return True, ""

    def all_team_votes_in(self) -> bool:
        return len(self.team_votes) >= self.active_player_count

    def resolve_team_vote(self) -> dict:
        approvals  = sum(1 for v in self.team_votes.values() if v)
        rejections = self.active_player_count - approvals
        approved   = approvals > rejections

        result = {
            "approvals":  approvals,
            "rejections": rejections,
            "approved":   approved,
            "votes":      {self.players[s].name: v for s, v in self.team_votes.items()},
            "proposed_team_names": [self.players[s].name for s in self.proposed_team],
        }

        if approved:
            self.consecutive_rejections = 0
            result["next_phase"] = "mission"
        else:
            self.consecutive_rejections += 1
            if self.consecutive_rejections >= MAX_CONSECUTIVE_REJECTIONS:
                self.winner     = "evil"
                self.win_reason = "Five consecutive team proposals were rejected. Evil wins!"
                result["next_phase"] = "game_over"
            else:
                result["next_phase"] = "team_proposal"
                result["next_leader"] = self.players[
                    self.player_order[(self.leader_index + 1) % len(self.player_order)]
                ].name

        result["consecutive_rejections"] = self.consecutive_rejections
        self.last_vote_result = result
        self.phase            = GamePhase.TEAM_VOTE_RESULT
        return result

    def advance_from_vote_result(self):
        if self.phase != GamePhase.TEAM_VOTE_RESULT or not self.last_vote_result:
            return
        nxt = self.last_vote_result["next_phase"]
        if nxt == "mission":
            self.phase = GamePhase.MISSION
        elif nxt == "team_proposal":
            self.leader_index = (self.leader_index + 1) % len(self.player_order)
            self._start_team_proposal()
        elif nxt == "game_over":
            self.phase = GamePhase.GAME_OVER

    # ── Mission ───────────────────────────────────────────────────────────────

    def submit_mission_vote(self, sid: str, success: bool) -> Tuple[bool, str]:
        if self.phase != GamePhase.MISSION:
            return False, "Not in mission phase."
        if sid not in self.proposed_team:
            return False, "You are not on this mission."
        if sid in self.mission_votes:
            return False, "Already submitted your mission card."
        if ROLE_TEAM[self.players[sid].role] == "good" and not success:
            return False, "Good players cannot play a Fail card."
        self.mission_votes[sid] = "success" if success else "fail"
        return True, ""

    def all_mission_votes_in(self) -> bool:
        return len(self.mission_votes) >= len(self.proposed_team)

    def resolve_mission(self) -> dict:
        fail_count        = sum(1 for v in self.mission_votes.values() if v == "fail")
        _, fails_required = self.current_mission_config
        succeeded         = fail_count < fails_required

        self.mission_results.append("success" if succeeded else "fail")
        good_wins = self.mission_results.count("success")
        evil_wins = self.mission_results.count("fail")

        result = {
            "mission_number": self.current_mission_index + 1,
            "team":           [self.players[s].name for s in self.proposed_team],
            "succeeded":      succeeded,
            "fail_count":     fail_count,
            "fails_required": fails_required,
            "good_wins":      good_wins,
            "evil_wins":      evil_wins,
        }

        if good_wins >= 3:
            result["next_phase"] = "assassination"
        elif evil_wins >= 3:
            self.winner     = "evil"
            self.win_reason = "Evil successfully failed 3 missions."
            result["next_phase"] = "game_over"
        else:
            self.current_mission_index += 1
            self.leader_index = (self.leader_index + 1) % len(self.player_order)
            result["next_phase"] = "team_proposal"

        self.last_mission_result = result
        self.phase               = GamePhase.MISSION_RESULT
        return result

    def advance_from_mission_result(self):
        if self.phase != GamePhase.MISSION_RESULT or not self.last_mission_result:
            return
        nxt = self.last_mission_result["next_phase"]
        if nxt == "assassination":
            self.phase = GamePhase.ASSASSINATION
        elif nxt == "game_over":
            self.phase = GamePhase.GAME_OVER
        elif nxt == "team_proposal":
            self._start_team_proposal()

    # ── Assassination ─────────────────────────────────────────────────────────

    def submit_assassination(self, assassin_sid: str, target_sid: str) -> Tuple[bool, dict]:
        if self.phase != GamePhase.ASSASSINATION:
            return False, {"error": "Not in assassination phase."}
        if assassin_sid != self.assassin_sid:
            return False, {"error": "Only the Assassin can assassinate."}
        if target_sid not in self.players:
            return False, {"error": "Invalid target."}
        if self.players[target_sid].is_spectator:
            return False, {"error": "Cannot target the moderator."}

        target     = self.players[target_sid]
        hit_merlin = (target.role == Role.MERLIN)
        self.winner = "evil" if hit_merlin else "good"
        self.win_reason = (
            f"The Assassin correctly identified {target.name} as Merlin. Evil wins!"
            if hit_merlin else
            f"The Assassin wrongly accused {target.name}. Merlin survives and Good wins!"
        )
        self.phase = GamePhase.GAME_OVER
        return True, {
            "target_name": target.name,
            "hit_merlin":  hit_merlin,
            "winner":      self.winner,
            "win_reason":  self.win_reason,
        }

    # ── Play Again ────────────────────────────────────────────────────────────

    def reset_for_next_game(self, requester_sid: str) -> Tuple[bool, str]:
        """
        Keep all players, reset all game state.
        Host always regains control. Moderator cleared for re-configuration.
        Transitions to PREGAME.
        """
        if self.phase != GamePhase.GAME_OVER:
            return False, "Can only play again from the game over screen."
        if requester_sid != self.host_sid:
            return False, "Only the host can start a new game."

        self.current_mission_index  = 0
        self.mission_results        = []
        self.leader_index           = 0
        self.consecutive_rejections = 0
        self.proposed_team          = []
        self.team_votes             = {}
        self.mission_votes          = {}
        self.last_vote_result       = None
        self.last_mission_result    = None
        self._role_reveal_ready     = set()
        self.assassin_sid           = None
        self.winner                 = None
        self.win_reason             = None
        self.optional_roles_chosen  = []
        self.player_order           = []
        self.moderator_mode         = "none"
        self.moderator_sid          = None

        for p in self.players.values():
            p.role         = None
            p.is_spectator = False

        self.phase = GamePhase.PREGAME
        return True, ""

    # ── State Serialisation ───────────────────────────────────────────────────

    def get_public_state(self) -> dict:
        active_order   = self.player_order if self.player_order else []
        spectator_sids = [sid for sid, p in self.players.items() if p.is_spectator]
        # Display order: active players first, spectator (moderator) at end
        if not active_order:
            display_order = list(self.players.keys())
        else:
            display_order = active_order + spectator_sids

        players_list = [
            {
                "sid":                 sid,
                "name":                self.players[sid].name,
                "connected":           self.players[sid].connected,
                "is_spectator":        self.players[sid].is_spectator,
                "is_moderator":        (sid == self.moderator_sid),
                "is_leader":           (self.current_leader is not None and
                                        sid == self.current_leader.sid),
                "is_on_proposed_team": sid in self.proposed_team,
                "has_team_voted":      sid in self.team_votes,
                "has_mission_voted":   sid in self.mission_votes,
            }
            for sid in display_order
        ]

        leader = self.current_leader
        n      = self.active_player_count
        config = PLAYER_CONFIG.get(n, {})
        optional_role_data = [
            {
                "value":      r.value,
                "headline":   OPTIONAL_ROLE_NOTES[r]["headline"],
                "detail":     OPTIONAL_ROLE_NOTES[r]["detail"],
                "difficulty": OPTIONAL_ROLE_NOTES[r]["difficulty"],
            }
            for r in config.get("optional_evil", [])
        ]
        timer = TIMER_CONFIG.get(n, {"proposal": 180, "vote": 90})

        return {
            "room_code":              self.room_code,
            "phase":                  self.phase.value,
            "host_sid":               self.host_sid,
            "moderator_sid":          self.moderator_sid,
            "moderator_mode":         self.moderator_mode,
            "players":                players_list,
            "num_players":            self.num_players,
            "active_player_count":    n,
            "current_mission_number": self.current_mission_index + 1,
            "mission_results":        self.mission_results,
            "mission_team_size":      self.mission_team_size if n >= 5 else 0,
            "mission_fails_required": self.mission_fails_required if n >= 5 else 1,
            "consecutive_rejections": self.consecutive_rejections,
            "proposed_team":          self.proposed_team,
            "leader_sid":             leader.sid  if leader else None,
            "leader_name":            leader.name if leader else None,
            "winner":                 self.winner,
            "win_reason":             self.win_reason,
            "votes_in":               len(self.team_votes),
            "mission_votes_in":       len(self.mission_votes),
            "last_vote_result":       self.last_vote_result,
            "last_mission_result":    self.last_mission_result,
            "optional_role_data":     optional_role_data,
            "chosen_optional_roles":  [r.value for r in self.optional_roles_chosen],
            "must_be_passive":        (self.num_players == 11),
            "timer_proposal":         timer["proposal"],
            "timer_vote":             timer["vote"],
        }

    def get_player_state(self, sid: str) -> dict:
        state  = self.get_public_state()
        player = self.players.get(sid)

        state["my_sid"]      = sid
        state["is_host"]     = (sid == self.host_sid)
        state["is_moderator"]= (sid == self.moderator_sid)
        state["is_spectator"]= (player.is_spectator if player else False)
        # can_advance: True if this player may click Continue on result screens
        state["can_advance"] = self.can_advance(sid)

        # Passive moderator (spectator): give them a proper role card description
        # instead of falling through to the no-role early return below.
        if player and player.is_spectator:
            state["my_name"]          = player.name
            state["my_role"]          = "Moderator"
            state["my_team"]          = "moderator"
            state["role_description"] = (
                "You are the Moderator. You are not an active player. "
                "You have no role, you do not vote on teams, and you are not sent "
                "on missions. Your job is to manage the game pace: advance phases "
                "when the table is ready, and display this screen for all to see."
            )
            state["night_knowledge"]   = {"known_players": {}}
            state["is_leader"]         = False
            state["is_on_mission"]     = False
            state["is_assassin"]       = False
            state["has_team_voted"]    = False
            state["has_mission_voted"] = False
            state["ready_count"]       = len(self._role_reveal_ready)
            if self.phase == GamePhase.GAME_OVER:
                state["all_roles"] = [
                    {
                        "name":         self.players[s].name,
                        "role":         self.players[s].role.value if self.players[s].role else "Moderator",
                        "team":         ROLE_TEAM[self.players[s].role] if self.players[s].role else "moderator",
                        "is_spectator": self.players[s].is_spectator,
                    }
                    for s in (self.player_order or list(self.players.keys()))
                ]
            return state

        if not player or not player.role:
            return state

        state["my_name"]           = player.name
        state["my_role"]           = player.role.value
        state["my_team"]           = ROLE_TEAM[player.role]
        state["night_knowledge"]   = self.get_night_knowledge(sid)

        # Percival's description depends on whether Morgana is actually in this game.
        if player.role == Role.PERCIVAL:
            morgana_in_game = any(p.role == Role.MORGANA for p in self.players.values())
            if morgana_in_game:
                state["role_description"] = ROLE_DESCRIPTIONS[Role.PERCIVAL]
            else:
                state["role_description"] = (
                    "The Merlin you are seeing is real. There is no Morgana in this game, "
                    "so the player you see is definitely Merlin. Protect him at all costs."
                )
        else:
            state["role_description"] = ROLE_DESCRIPTIONS[player.role]
        state["is_leader"]         = (self.current_leader is not None and
                                      sid == self.current_leader.sid)
        state["is_on_mission"]     = sid in self.proposed_team
        state["is_assassin"]       = (sid == self.assassin_sid)
        state["has_team_voted"]    = sid in self.team_votes
        state["has_mission_voted"] = sid in self.mission_votes
        state["ready_count"]       = len(self._role_reveal_ready)

        if self.phase == GamePhase.GAME_OVER:
            state["all_roles"] = [
                {
                    "name":         self.players[s].name,
                    "role":         self.players[s].role.value if self.players[s].role else "Moderator",
                    "team":         ROLE_TEAM[self.players[s].role] if self.players[s].role else "moderator",
                    "is_spectator": self.players[s].is_spectator,
                }
                for s in (self.player_order or list(self.players.keys()))
            ]
        return state

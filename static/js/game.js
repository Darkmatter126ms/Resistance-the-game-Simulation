/* ════════════════════════════════════════════════════════════════════════════
   game.js  —  The Resistance: Avalon  —  Client-side game logic
   ════════════════════════════════════════════════════════════════════════════ */

// ─── Identity ─────────────────────────────────────────────────────────────────
let mySid     = "";
let myName    = sessionStorage.getItem("avalon_name")      || "";
let roomCode  = sessionStorage.getItem("avalon_room_code") || "";
let lastState = null;

// ─── Socket ───────────────────────────────────────────────────────────────────
const socket = io();

socket.on("connect", () => {
  mySid = socket.id;
  // Re-join the room on every (re)connect so the server knows who we are
  if (myName && roomCode) {
    socket.emit("join_room_request", { name: myName, room_code: roomCode });
  } else {
    window.location.href = "/";
  }
});

socket.on("joined_room", data => {
  roomCode = data.room_code;
  sessionStorage.setItem("avalon_room_code", roomCode);
});

socket.on("error", data => showToast(data.message, "error"));

// ─── Notification / Toast system ──────────────────────────────────────────────
// Server pushes "notification" events for important game moments.
// Client also calls showToast() directly for immediate feedback.

socket.on("notification", data => {
  showToast(data.message, data.kind || "info");
});

/**
 * showToast(message, kind)
 * kind: "info" | "success" | "error" | "warning"
 * Toasts stack, auto-dismiss after 4.5 s, and are capped at 5 visible at once.
 */
function showToast(message, kind = "info") {
  const container = document.getElementById("toast-container");

  // Cap: remove oldest if already at 5
  const existing = container.querySelectorAll(".toast");
  if (existing.length >= 5) existing[0].remove();

  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = message;
  container.appendChild(t);

  // Auto-dismiss
  const tid = setTimeout(() => t.remove(), 4500);
  // Allow click-to-dismiss
  t.addEventListener("click", () => { clearTimeout(tid); t.remove(); });
}

// ─── Static maps ─────────────────────────────────────────────────────────────
const ROLE_ICONS = {
  "Merlin":            "🧙",
  "Percival":          "🛡",
  "Loyal Servant":     "⚔",
  "Assassin":          "🗡",
  "Morgana":           "🔮",
  "Mordred":           "💀",
  "Oberon":            "🌑",
  "Minion of Mordred": "👁",
};

// Mission team sizes per player count (mirrors game.py MISSION_CONFIG)
const MISSION_SIZES = {
  5:  [2,3,2,3,3],
  6:  [2,3,4,3,4],
  7:  [2,3,3,4,4],
  8:  [3,4,4,5,5],
  9:  [3,4,4,5,5],
  10: [3,4,4,5,5],
};
// Missions that require 2 fails at 7+ players (1-indexed mission number)
const DOUBLE_FAIL_MISSIONS = { 7: 4, 8: 4, 9: 4, 10: 4 };

// ─── Phase routing ────────────────────────────────────────────────────────────
const PHASES = [
  "role_config",
  "role_reveal",
  "team_proposal",
  "team_vote",
  "team_vote_result",
  "mission",
  "mission_result",
  "assassination",
  "game_over",
];

function showPhase(phase) {
  PHASES.forEach(p => {
    const el = document.getElementById(`phase-${p}`);
    if (el) el.classList.toggle("hidden", p !== phase);
  });
}

// ─── Main state handler ───────────────────────────────────────────────────────
socket.on("game_state", state => {
  mySid     = state.my_sid || socket.id;
  lastState = state;

  if (state.phase === "lobby") { window.location.href = "/"; return; }

  showPhase(state.phase);

  switch (state.phase) {
    case "role_config":       renderRoleConfig(state);       break;
    case "role_reveal":       renderRoleReveal(state);       break;
    case "team_proposal":     renderTeamProposal(state);     break;
    case "team_vote":         renderTeamVote(state);         break;
    case "team_vote_result":  renderTeamVoteResult(state);   break;
    case "mission":           renderMission(state);          break;
    case "mission_result":    renderMissionResult(state);    break;
    case "assassination":     renderAssassination(state);    break;
    case "game_over":         renderGameOver(state);         break;
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
//  REUSABLE UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

/** Returns the two-letter initials for a name. */
function initials(name) {
  return name.split(" ").map(w => w[0]).join("").substring(0, 2).toUpperCase();
}

/**
 * playerChip({ sid, name, connected, badges, extra, clickable, selected })
 * Returns an HTML string for a player row.
 * badges: [{ type: "leader"|"me"|"host"|"good"|"evil"|"selected"|"voted", text: string }]
 */
function playerChip({ sid, name, connected = true, badges = [], extra = "",
                       clickable = false, selected = false }) {
  const isMe = sid === mySid;
  let cls = "player-chip";
  if (isMe)       cls += " is-me";
  if (selected)   cls += " is-selected";
  if (clickable)  cls += " clickable";
  if (!connected) cls += " disconnected";

  const badgeHTML = badges.map(b =>
    `<span class="player-badge badge-${b.type}">${b.text}</span>`
  ).join("");

  return `
    <div class="${cls}" data-sid="${sid}">
      <div class="player-avatar">${initials(name)}</div>
      <div class="player-name">${name}</div>
      ${badgeHTML}
      ${extra}
    </div>`;
}

/**
 * Render the 5-pip mission track into a container element.
 */
function renderMissionTrack(containerId, state) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";

  const sizes   = MISSION_SIZES[state.num_players] || MISSION_SIZES[5];
  const results = state.mission_results || [];
  const current = state.current_mission_number - 1;  // 0-indexed

  for (let i = 0; i < 5; i++) {
    const pip     = document.createElement("div");
    const isDouble = DOUBLE_FAIL_MISSIONS[state.num_players] === (i + 1);
    let   cls      = "mission-pip";

    let icon = "";
    if (results[i] === "success") { cls += " success"; icon = "✓"; }
    else if (results[i] === "fail") { cls += " fail";  icon = "✗"; }
    else if (i === current)        { cls += " current"; icon = "●"; }
    else                           { cls += " pending"; icon = sizes[i]; }

    pip.className = cls;
    pip.innerHTML = `
      <span>${icon}</span>
      ${isDouble ? '<span class="double-fail-marker">2✗</span>' : ""}`;
    pip.title = `Mission ${i + 1}: ${sizes[i]} players${isDouble ? " — needs 2 Fail cards" : ""}`;
    el.appendChild(pip);
  }
}

/**
 * Render the 5-dot rejection meter (red dots = used rejections).
 */
function renderRejectionMeter(containerId, count) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";
  for (let i = 0; i < 5; i++) {
    const pip = document.createElement("div");
    pip.className = "rejection-pip" + (i < count ? " used" : "");
    pip.title     = i < count ? "Rejected" : "Available";
    el.appendChild(pip);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: ROLE_CONFIG
// ═══════════════════════════════════════════════════════════════════════════════

// Track which optional roles the host has toggled ON
let roleConfigSelected = new Set();

function renderRoleConfig(state) {
  const isHost = state.is_host;

  document.getElementById("role-config-host-panel").classList.toggle("hidden", !isHost);
  document.getElementById("role-config-waiting-panel").classList.toggle("hidden", isHost);

  if (isHost) {
    renderRoleConfigHostPanel(state);
  } else {
    // Waiting panel: show player list so non-hosts know who's in the game
    const list = document.getElementById("role-config-player-list");
    list.innerHTML = state.players.map(p => playerChip({
      sid: p.sid, name: p.name, connected: p.connected,
      badges: [
        ...(p.sid === state.host_sid ? [{ type: "host", text: "HOST" }] : []),
        ...(p.sid === mySid          ? [{ type: "me",   text: "YOU"  }] : []),
      ],
    })).join("");
  }
}

function renderRoleConfigHostPanel(state) {
  const container = document.getElementById("role-config-options");
  container.innerHTML = "";

  const options = state.optional_role_data || [];

  if (options.length === 0) {
    container.innerHTML = `<div class="text-muted text-center">No optional roles available.</div>`;
    return;
  }

  options.forEach(opt => {
    const isSelected = roleConfigSelected.has(opt.value);
    const card       = document.createElement("div");

    card.className = "player-chip clickable" + (isSelected ? " is-selected" : "");
    card.dataset.role = opt.value;
    card.innerHTML = `
      <div class="player-avatar">${ROLE_ICONS[opt.value] || "?"}</div>
      <div style="flex:1;">
        <div style="font-weight:600; color:var(--text);">${opt.value}</div>
        <div style="font-size:0.78rem; color:var(--gold); margin-bottom:0.2rem;">${opt.headline}</div>
        <div style="font-size:0.8rem; color:var(--text-muted); line-height:1.4;">${opt.detail}</div>
        <div style="font-size:0.75rem; color:var(--red); margin-top:0.25rem;">
          ${opt.difficulty}
        </div>
      </div>
      <div style="margin-left:0.75rem;">
        <span class="player-badge ${isSelected ? "badge-evil" : "badge-voted"}">
          ${isSelected ? "✓ Include" : "Exclude"}
        </span>
      </div>`;

    card.addEventListener("click", () => {
      if (roleConfigSelected.has(opt.value)) {
        roleConfigSelected.delete(opt.value);
      } else {
        roleConfigSelected.add(opt.value);
      }
      // Re-render only the options area so the toggle feels instant
      renderRoleConfigHostPanel(state);
    });

    container.appendChild(card);
  });
}

document.getElementById("btn-confirm-roles").addEventListener("click", () => {
  socket.emit("configure_roles", { chosen_roles: Array.from(roleConfigSelected) });
  roleConfigSelected.clear();
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: ROLE_REVEAL
// ═══════════════════════════════════════════════════════════════════════════════

let readyClicked = false;

function renderRoleReveal(state) {
  const role = state.my_role || "—";
  const team = state.my_team || "—";
  const desc = state.role_description || "—";
  const icon = ROLE_ICONS[role] || "?";

  document.getElementById("role-icon").textContent = icon;
  document.getElementById("role-name").textContent = role;
  document.getElementById("role-desc").textContent = desc;
  document.getElementById("role-card").className   = `role-card team-${team}`;

  const teamEl = document.getElementById("role-team");
  teamEl.textContent = team === "good" ? "⚔ Good" : "💀 Evil";
  teamEl.className   = `role-team team-${team}`;

  // Night knowledge (Merlin, Percival, Evil)
  const known    = state.night_knowledge?.known_players || {};
  const knownIDs = Object.keys(known);
  const kPanel   = document.getElementById("knowledge-panel");
  const kList    = document.getElementById("knowledge-list");

  if (knownIDs.length > 0) {
    kPanel.classList.remove("hidden");
    kList.innerHTML = knownIDs.map(sid => {
      const entry = known[sid];
      return playerChip({
        sid, name: entry.name,
        badges: [{ type: "evil", text: entry.label }],
      });
    }).join("");
  } else {
    kPanel.classList.add("hidden");
  }

  const total    = state.num_players;
  const readyCnt = state.ready_count || 0;
  document.getElementById("ready-status").textContent =
    `${readyCnt} / ${total} players ready`;

  document.getElementById("btn-ready").disabled = readyClicked;
}

document.getElementById("btn-ready").addEventListener("click", () => {
  readyClicked = true;
  document.getElementById("btn-ready").disabled = true;
  socket.emit("player_ready");
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: TEAM_PROPOSAL
// ═══════════════════════════════════════════════════════════════════════════════

let selectedTeam = new Set();

function renderTeamProposal(state) {
  const isLeader = state.is_leader;
  const teamSize = state.mission_team_size;

  document.getElementById("proposal-mission-num").textContent      = state.current_mission_number;
  document.getElementById("proposal-team-size-label").textContent  = `Pick ${teamSize}`;
  document.getElementById("proposal-need").textContent             = teamSize;

  renderMissionTrack("proposal-mission-track", state);
  renderRejectionMeter("proposal-rejection-meter", state.consecutive_rejections);

  document.getElementById("proposal-leader-panel").classList.toggle("hidden", !isLeader);
  document.getElementById("proposal-waiting-panel").classList.toggle("hidden",  isLeader);

  if (isLeader) {
    renderProposalLeaderView(state, teamSize);
  } else {
    document.getElementById("proposal-leader-name").textContent = state.leader_name || "—";
    renderProposalWaitingView(state);
  }
}

function renderProposalLeaderView(state, teamSize) {
  const list = document.getElementById("proposal-player-list");
  list.innerHTML = "";

  state.players.forEach(p => {
    const isSel  = selectedTeam.has(p.sid);
    const chip   = document.createElement("div");
    chip.innerHTML = playerChip({
      sid: p.sid, name: p.name, connected: p.connected,
      selected: isSel, clickable: true,
      badges: [
        ...(isSel        ? [{ type: "selected", text: "On Team" }]  : []),
        ...(p.sid===mySid? [{ type: "me",        text: "YOU" }]      : []),
      ],
    });
    const inner = chip.firstElementChild;
    inner.addEventListener("click", () => toggleProposalSelection(p.sid, teamSize, state));
    list.appendChild(inner);
  });

  updateProposeButton(teamSize);
}

function renderProposalWaitingView(state) {
  document.getElementById("proposal-waiting-player-list").innerHTML =
    state.players.map(p => playerChip({
      sid: p.sid, name: p.name, connected: p.connected,
      badges: [
        ...(p.is_leader  ? [{ type: "leader", text: "LEADER" }] : []),
        ...(p.sid===mySid? [{ type: "me",     text: "YOU" }]    : []),
      ],
    })).join("");
}

function toggleProposalSelection(sid, teamSize, state) {
  if (selectedTeam.has(sid)) {
    selectedTeam.delete(sid);
  } else if (selectedTeam.size < teamSize) {
    selectedTeam.add(sid);
  } else {
    showToast(`You can only select ${teamSize} player(s).`, "warning");
    return;
  }
  renderProposalLeaderView(state, teamSize);
}

function updateProposeButton(teamSize) {
  const btn = document.getElementById("btn-propose");
  btn.textContent = `Propose Team (${selectedTeam.size} / ${teamSize})`;
  btn.disabled    = (selectedTeam.size !== teamSize);
}

document.getElementById("btn-propose").addEventListener("click", () => {
  if (!lastState) return;
  socket.emit("propose_team", { team: Array.from(selectedTeam) });
  selectedTeam.clear();
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: TEAM_VOTE
// ═══════════════════════════════════════════════════════════════════════════════

function renderTeamVote(state) {
  document.getElementById("vote-mission-num").textContent = state.current_mission_number;
  document.getElementById("vote-progress").textContent   =
    `${state.votes_in} / ${state.num_players} voted`;

  renderMissionTrack("vote-mission-track", state);

  // Proposed team panel
  const proposedDiv = document.getElementById("vote-proposed-team");
  proposedDiv.innerHTML = (state.proposed_team || []).map(sid => {
    const p = state.players.find(x => x.sid === sid);
    return p ? playerChip({ sid, name: p.name }) : "";
  }).join("");

  // All players with vote status
  document.getElementById("vote-player-list").innerHTML =
    state.players.map(p => playerChip({
      sid: p.sid, name: p.name, connected: p.connected,
      badges: [
        ...(p.has_team_voted ? [{ type: "voted", text: "Voted" }] : []),
        ...(p.sid === mySid  ? [{ type: "me",    text: "YOU"  }] : []),
      ],
    })).join("");

  const hasVoted = state.has_team_voted;
  document.getElementById("vote-buttons").classList.toggle("hidden",  hasVoted);
  document.getElementById("vote-waiting").classList.toggle("hidden", !hasVoted);
}

document.getElementById("btn-approve").addEventListener("click", () => {
  socket.emit("vote_team", { approve: true });
});
document.getElementById("btn-reject").addEventListener("click", () => {
  socket.emit("vote_team", { approve: false });
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: TEAM_VOTE_RESULT
// ═══════════════════════════════════════════════════════════════════════════════

function renderTeamVoteResult(state) {
  const result = state.last_vote_result;
  if (!result) return;

  const banner = document.getElementById("vote-result-banner");
  if (result.approved) {
    banner.className = "result-banner success";
    document.getElementById("vote-result-icon").textContent  = "✓";
    document.getElementById("vote-result-title").textContent = "Team Approved!";
  } else {
    banner.className = "result-banner fail";
    document.getElementById("vote-result-icon").textContent  = "✗";
    document.getElementById("vote-result-title").textContent = "Team Rejected";
  }
  document.getElementById("vote-result-tally").textContent =
    `${result.approvals} approved · ${result.rejections} rejected`;

  // Per-player vote breakdown
  const list = document.getElementById("vote-result-list");
  list.innerHTML = "";
  if (result.votes) {
    Object.entries(result.votes)
      .sort((a, b) => b[1] - a[1])   // approvals first
      .forEach(([name, approved]) => {
        const p   = state.players.find(x => x.name === name);
        const sid = p?.sid || name;
        const chip = document.createElement("div");
        chip.innerHTML = playerChip({
          sid, name,
          badges: [{
            type: approved ? "good" : "evil",
            text: approved ? "✓ Approve" : "✗ Reject",
          }],
        });
        list.appendChild(chip.firstElementChild);
      });
  }

  // Rejection warning
  const rejWarn = document.getElementById("vote-result-rejection-warning");
  if (!result.approved && result.consecutive_rejections < 5) {
    const left = 5 - result.consecutive_rejections;
    rejWarn.classList.remove("hidden");
    document.getElementById("vote-result-rejections-left").textContent = left;
  } else {
    rejWarn.classList.add("hidden");
  }

  const isHost = state.is_host;
  document.getElementById("btn-advance-vote-result").classList.toggle("hidden",  !isHost);
  document.getElementById("vote-result-host-note").classList.toggle("hidden",   isHost);
}

document.getElementById("btn-advance-vote-result").addEventListener("click", () => {
  socket.emit("advance_from_vote_result");
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: MISSION
// ═══════════════════════════════════════════════════════════════════════════════

function renderMission(state) {
  document.getElementById("mission-num").textContent =
    state.current_mission_number;
  document.getElementById("mission-votes-progress").textContent =
    `${state.mission_votes_in} / ${state.proposed_team?.length || 0}`;

  renderMissionTrack("mission-track", state);

  const isOnMission = state.is_on_mission;
  document.getElementById("mission-active-panel").classList.toggle("hidden", !isOnMission);
  document.getElementById("mission-waiting-panel").classList.toggle("hidden",  isOnMission);

  if (isOnMission) {
    const isEvil  = (state.my_team === "evil");
    const noteEl  = document.getElementById("mission-team-note");
    const failBtn = document.getElementById("btn-fail");

    if (isEvil) {
      noteEl.innerHTML = `
        <span class="text-red">
          You may play <strong>Fail</strong> to sabotage this mission,
          or <strong>Success</strong> to stay hidden.
        </span>`;
      failBtn.disabled = false;
      failBtn.classList.remove("hidden");
    } else {
      noteEl.innerHTML = `
        <span class="text-blue">
          As a Good player, you <strong>must</strong> play Success.
          The Fail card is not available to you.
        </span>`;
      failBtn.disabled = true;
      failBtn.classList.add("hidden");
    }

    const hasVoted = state.has_mission_voted;
    document.getElementById("mission-vote-buttons").classList.toggle("hidden",  hasVoted);
    document.getElementById("mission-submitted").classList.toggle("hidden",    !hasVoted);
  } else {
    // Show the mission team for spectating players
    document.getElementById("mission-team-list").innerHTML =
      (state.proposed_team || []).map(sid => {
        const p = state.players.find(x => x.sid === sid);
        return p ? playerChip({
          sid, name: p.name,
          badges: [{ type: "selected", text: "On Mission" }],
        }) : "";
      }).join("");
  }
}

document.getElementById("btn-success").addEventListener("click", () => {
  socket.emit("vote_mission", { success: true });
});
document.getElementById("btn-fail").addEventListener("click", () => {
  if (confirm("Play FAIL? This will sabotage the mission — Evil eyes only.")) {
    socket.emit("vote_mission", { success: false });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: MISSION_RESULT
// ═══════════════════════════════════════════════════════════════════════════════

function renderMissionResult(state) {
  const result = state.last_mission_result;
  if (!result) return;

  const banner = document.getElementById("mission-result-banner");
  if (result.succeeded) {
    banner.className = "result-banner success";
    document.getElementById("mission-result-icon").textContent  = "✓";
    document.getElementById("mission-result-title").textContent =
      `Mission ${result.mission_number} Succeeded!`;
    document.getElementById("mission-result-detail").textContent =
      result.fail_count === 0
        ? "All cards were Success."
        : `${result.fail_count} Fail card(s) were played, but ${result.fails_required} were needed.`;
  } else {
    banner.className = "result-banner fail";
    document.getElementById("mission-result-icon").textContent  = "✗";
    document.getElementById("mission-result-title").textContent =
      `Mission ${result.mission_number} Failed!`;
    document.getElementById("mission-result-detail").textContent =
      `${result.fail_count} Fail card(s) sabotaged the mission.`;
  }

  renderMissionTrack("mission-result-track", state);

  document.getElementById("mission-result-score").textContent =
    `Good: ${result.good_wins} wins · Evil: ${result.evil_wins} wins`;

  const isHost = state.is_host;
  document.getElementById("btn-advance-mission-result").classList.toggle("hidden",  !isHost);
  document.getElementById("mission-result-host-note").classList.toggle("hidden",   isHost);
}

document.getElementById("btn-advance-mission-result").addEventListener("click", () => {
  socket.emit("advance_from_mission_result");
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: ASSASSINATION
// ═══════════════════════════════════════════════════════════════════════════════

let assassinTarget = null;

function renderAssassination(state) {
  const isAssassin = state.is_assassin;
  document.getElementById("assassination-assassin-panel").classList.toggle("hidden", !isAssassin);
  document.getElementById("assassination-waiting-panel").classList.toggle("hidden",  isAssassin);

  if (isAssassin) {
    assassinTarget = null;
    document.getElementById("btn-assassinate").disabled = true;

    const list = document.getElementById("assassination-player-list");
    list.innerHTML = "";

    state.players.forEach(p => {
      if (p.sid === mySid) return;   // can't target yourself
      const chip = document.createElement("div");
      chip.innerHTML = playerChip({
        sid: p.sid, name: p.name, connected: p.connected,
        clickable: true,
        selected: (assassinTarget === p.sid),
      });
      const inner = chip.firstElementChild;
      inner.addEventListener("click", () => {
        assassinTarget = p.sid;
        document.getElementById("btn-assassinate").disabled = false;
        // Highlight selection
        list.querySelectorAll(".player-chip").forEach(c => {
          c.classList.toggle("is-selected", c.dataset.sid === assassinTarget);
        });
      });
      list.appendChild(inner);
    });
  } else {
    document.getElementById("assassination-waiting-list").innerHTML =
      state.players.map(p => playerChip({
        sid: p.sid, name: p.name, connected: p.connected,
        badges: p.sid === mySid ? [{ type: "me", text: "YOU" }] : [],
      })).join("");
  }
}

document.getElementById("btn-assassinate").addEventListener("click", () => {
  if (!assassinTarget || !lastState) return;
  const target = lastState.players.find(p => p.sid === assassinTarget);
  if (!target) return;
  if (!confirm(`Assassinate ${target.name}? This cannot be undone.`)) return;
  socket.emit("assassinate", { target_sid: assassinTarget });
});

// ═══════════════════════════════════════════════════════════════════════════════
//  PHASE: GAME_OVER
// ═══════════════════════════════════════════════════════════════════════════════

function renderGameOver(state) {
  const isGoodWin = (state.winner === "good");
  const banner    = document.getElementById("game-over-banner");
  banner.className = `game-over-banner ${isGoodWin ? "good-wins" : "evil-wins"}`;

  document.getElementById("game-over-icon").textContent   = isGoodWin ? "⚔" : "💀";
  document.getElementById("game-over-title").textContent  = isGoodWin ? "Good Wins!" : "Evil Wins!";
  document.getElementById("game-over-reason").textContent = state.win_reason || "";

  // Full role reveal
  document.getElementById("game-over-roles-list").innerHTML =
    (state.all_roles || []).map(r => playerChip({
      sid: r.name, name: r.name,
      badges: [{ type: r.team, text: `${ROLE_ICONS[r.role] || ""} ${r.role}` }],
    })).join("");

  renderMissionTrack("game-over-mission-track", state);
}

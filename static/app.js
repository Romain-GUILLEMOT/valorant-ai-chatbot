const empty = value => value || "<span class=\"muted\">?</span>";
const agentSrc = row => row?.agent_img ? `/assets/agents/${row.agent_img}` : "";
const rankSrc = row => row?.rank_img ? `/assets/ranks/${row.rank_img}` : "/assets/ranks/unknown.png";

let lastData = null;
let lastUpdatedAt = null;

const SHORTCUTS = [
  ["T+N", "Reset game + full scan"],
  ["T+UP", "Ally score +1"],
  ["T+DOWN", "Ally score -1"],
  ["T+RIGHT", "Enemy score +1"],
  ["T+LEFT", "Enemy score -1"],
  ["T+G", "Gamma disclaimer"]
];

const pct = value => {
  if (!value) return "<span class=\"muted\">?</span>";
  const s = String(value).trim();
  return s.endsWith("%") ? s : `${s}%`;
};

const kdParts = value => {
  const text = String(value || "");
  const parts = text.split("-");
  const kills = parseInt(parts[0], 10) || 0;
  const deaths = parseInt(parts[1], 10) || 0;
  return { kills, deaths, diff: kills - deaths };
};

const tone = value => value > 0 ? "good" : value < 0 ? "bad" : "neutral";
const numberTone = (value, good, bad) => {
  const n = parseFloat(value);
  if (Number.isNaN(n)) return "neutral";
  return n >= good ? "good" : n < bad ? "bad" : "neutral";
};

function secondsAgo(isoDate) {
  if (!isoDate) return "--";
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return "--";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  return `${seconds}s ago`;
}

function renderMatchMeta() {
  const latest = lastData?.latest || {};
  document.querySelector("#match-meta").textContent =
    `total ${latest.scan_ms || 0}ms - ${latest.full_scan ? "FULL" : "FAST"} - refresh ${secondsAgo(lastUpdatedAt)}`;
}

function playerRow(row) {
  const kd = kdParts(row.kd);
  const avatar = agentSrc(row);
  return `<tr class="${row.team === "enemies" ? "enemy-row" : ""}">
    <td class="player-col">
      <div class="identity">
        <div class="agent-icon">${avatar ? `<img src="${avatar}" alt="">` : ""}${row.level ? `<i>${row.level}</i>` : ""}</div>
        <div>
          <strong title="${row.name || ""}">${empty(row.name)}</strong>
          <span>${empty(row.agent)} - ${empty(row.team)} #${row.slot || "?"}</span>
        </div>
      </div>
    </td>
    <td class="rank-col"><img src="${rankSrc(row)}" title="${row.rank || "unknown"}" alt=""></td>
    <td class="num main">${kd.kills}-${kd.deaths} <em class="${tone(kd.diff)}">${kd.diff > 0 ? "+" : ""}${kd.diff}</em></td>
    <td class="num">${empty(row.assists)}</td>
    <td class="num ${numberTone(row.kd_ratio, 1.2, 0.85)}">${empty(row.kd_ratio)}</td>
    <td class="num">${empty(row.kpr)}</td>
    <td class="num">${empty(row.fkfd)}</td>
    <td class="num">${pct(row.kast)}</td>
    <td class="num">${empty(row.srv)}</td>
    <td class="num ${numberTone(row.hs, 24, 14)}">${pct(row.hs)}</td>
    <td class="num">${empty(row.one_v_x)}</td>
  </tr>`;
}

function duel(row) {
  const kills = parseInt(row.kills, 10) || 0;
  const deaths = parseInt(row.deaths, 10) || 0;
  const diff = kills - deaths;
  const avatar = agentSrc(row);
  return `<article class="duel">
    <div class="agent-icon small">${avatar ? `<img src="${avatar}" alt="">` : ""}</div>
    <strong>${empty(row.agent)}</strong>
    <b>${kills}-${deaths}</b>
    <em class="${tone(diff)}">${diff > 0 ? "+" : ""}${diff}</em>
  </article>`;
}

function renderPlayers(rows) {
  const allies = rows.filter(row => row.team === "allies");
  const enemies = rows.filter(row => row.team === "enemies");
  document.querySelector("#players").innerHTML = `<table>
    <thead>
      <tr>
        <th class="player-col">Player</th>
        <th class="rank-col">Rank</th>
        <th>K-D</th>
        <th>A</th>
        <th>KD</th>
        <th>KPR</th>
        <th>FK/FD</th>
        <th>KAST</th>
        <th>SRV</th>
        <th>HS</th>
        <th>1vX</th>
      </tr>
    </thead>
    <tbody>
      ${allies.map(playerRow).join("")}
      <tr class="split"><td colspan="11">ENEMIES</td></tr>
      ${enemies.map(playerRow).join("")}
    </tbody>
  </table>`;
}

function renderShortcutList() {
  document.querySelector("#shortcut-list").innerHTML = SHORTCUTS.map(([hotkey, label]) => `
    <div class="shortcut-row">
      <kbd>${hotkey}</kbd>
      <span>${label}</span>
    </div>
  `).join("");
}

function renderPrompts(ai) {
  const prompts = ai?.prompts || [];
  document.querySelector("#prompt-list").innerHTML = prompts.map(prompt => `
    <button class="prompt-btn" data-prompt="${prompt.id}">
      <kbd>${prompt.hotkey}</kbd>
      <span>${prompt.label}</span>
      <em>${prompt.audience}</em>
    </button>
  `).join("");

  document.querySelectorAll(".prompt-btn").forEach(button => {
    button.addEventListener("click", () => postPrompt(button.dataset.prompt));
  });
}

function renderDeaths(deaths) {
  document.querySelector("#death-log").innerHTML = (deaths || []).slice(-3).reverse().map(death => `
    <div class="death-item">
      <b>${empty(death.killed_by_agent)}</b>
      <span>${String(death.at || "").split("T").at(-1) || "?"}</span>
    </div>
  `).join("") || `<div class="death-item"><b class="muted">none</b><span>--</span></div>`;
}

async function postScore(team, direction) {
  await fetch(`/api/score/${team}/${direction}`, { method: "POST" });
  await load();
}

async function postPrompt(promptId) {
  const status = document.querySelector("#ai-status");
  status.textContent = "generating...";
  const res = await fetch(`/api/ai/${promptId}`, { method: "POST" });
  const data = await res.json();
  console.log("[valorant-ai] prompt sent", data.sent_prompt || data.error || "no prompt");
  status.textContent = data.ok ? `copied: ${data.message}` : `error: ${data.error}`;
  await load();
}

async function load() {
  const data = await fetch("/api/state", { cache: "no-store" }).then(r => r.json());
  const latest = data.latest || {};
  const score = latest.score || data.score || {};
  lastData = data;
  lastUpdatedAt = latest.updated_at || null;

  document.querySelector("#status").textContent = String(data.status || "unknown").toUpperCase();
  document.querySelector("#game").textContent = `MATCH ${data.current_game_id || 1}`;
  renderMatchMeta();
  document.querySelector("#score-allies").textContent = score.allies ?? 0;
  document.querySelector("#score-enemies").textContent = score.enemies ?? 0;

  document.querySelector("#duels").innerHTML = (latest.live_duels || []).map(duel).join("");
  renderPlayers(latest.scoreboard || []);
  renderShortcutList();
  renderPrompts(data.ai || {});
  renderDeaths(data.death_log || []);

  const ai = data.ai || {};
  if (ai.last_message || ai.last_error) {
    document.querySelector("#ai-status").textContent = ai.last_message ? `copied: ${ai.last_message}` : `error: ${ai.last_error}`;
  }
}

document.querySelector("#new-game-btn").addEventListener("click", async () => {
  await fetch("/api/new-game", { method: "POST" });
  await load();
});

document.querySelectorAll(".score-btn").forEach(button => {
  button.addEventListener("click", () => postScore(button.dataset.team, button.dataset.direction));
});

load();
setInterval(load, 3000);
setInterval(renderMatchMeta, 1000);

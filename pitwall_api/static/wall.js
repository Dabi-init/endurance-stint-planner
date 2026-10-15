import { clampLap, esc } from "./escape.js";

const FIXTURE = "2024-r01-bahrain-verstappen";
const RECORDED = [
  { compound: "SOFT", laps: 17 },
  { compound: "HARD", laps: 20 },
  { compound: "SOFT", laps: 20 },
];

const state = {
  mode: "plan",
  lap: 1,
  replay: null,
  compare: null,
  event: null,
};

const $ = (id) => document.getElementById(id);

function safeUrl(url) {
  return typeof url === "string" && url.startsWith("https://") ? url : "";
}

function colour(value) {
  if (typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)) return value;
  if (typeof value === "string" && /^[0-9a-fA-F]{6}$/.test(value)) return `#${value}`;
  return "#d0d7e2";
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function overrides() {
  return {
    pit_lane_loss_sec: Number($("pit-loss").value),
    base_lap_time_sec: Number($("base-lap").value),
    dry_race: $("dry-race").checked,
  };
}

function clock(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds * 1000);
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const secs = Math.floor((total % 60000) / 1000);
  const ms = total % 1000;
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${hours}:${pad(minutes)}:${pad(secs)}.${pad(ms, 3)}`;
}

function currentEvent() {
  const events = state.replay?.events || [];
  if (state.mode !== "replay") return events[0];
  let chosen = events[0];
  for (const event of events) {
    if (event.lap <= state.lap) chosen = event;
  }
  return chosen;
}

function lapState() {
  return (state.replay?.laps || []).find((row) => row.lap === state.lap);
}

function renderTower() {
  const lap = lapState();
  $("tower").innerHTML = (state.replay?.tower || []).map((driver) => {
    const photo = safeUrl(driver.headshot_url);
    const pip = driver.focus && lap
      ? `<span class="compound-pip" style="background:${colour(lap.colour)}">${esc(lap.compound)}</span>`
      : "";
    const face = photo
      ? `<img class="face" alt="" src="${esc(photo)}" />`
      : `<span class="initials">${esc(driver.code || "?")}</span>`;
    return `<li class="driver${driver.focus ? " focus" : ""}">
      <span class="stripe" style="background:${colour(driver.team_colour_css)}"></span>
      <div class="who">${face}<div><strong>${esc(driver.code)}</strong><span>${esc(driver.team_name)}</span></div></div>
      <span class="meta">${esc(driver.grid ?? "—")}</span>
      <span class="meta">${pip || esc(driver.finish_position ?? "—")}</span>
    </li>`;
  }).join("");
  for (const image of $("tower").querySelectorAll("img")) {
    image.addEventListener("error", () => {
      const initials = document.createElement("span");
      initials.className = "initials";
      initials.textContent = image.closest(".driver")?.querySelector("strong")?.textContent || "?";
      image.replaceWith(initials);
    });
  }
}

function segments(stints, total) {
  return stints.map((stint) => {
    const width = (stint.laps / total) * 100;
    return `<div class="seg" style="width:${width}%;background:${colour(stint.colour)}">${esc(stint.label)} ${stint.laps}</div>`;
  }).join("");
}

function renderTimeline() {
  const event = currentEvent();
  const recorded = state.replay?.recorded_stints || [];
  const raceLaps = state.replay?.race_laps || 57;
  const planLaps = (event?.stints || []).reduce((sum, stint) => sum + stint.laps, 0) || raceLaps;
  const window = event?.pit_window;
  const band = window
    ? `<div class="window" style="left:${((window[0] - 1) / planLaps) * 100}%;width:${((window[1] - window[0] + 1) / planLaps) * 100}%"></div>`
    : "";
  const label = state.mode === "replay" && event?.lap ? `From lap ${event.lap}` : "Suggested";
  $("timeline").innerHTML = `
    <div class="lane"><p>${label}</p><div class="track">${segments(event?.stints || [], planLaps)}${band}</div></div>
    <div class="lane"><p>Recorded</p><div class="track">${segments(recorded, raceLaps)}</div></div>
    <div class="ticks"><span>1</span><span>${Math.round(raceLaps / 2)}</span><span>${raceLaps}</span></div>`;
  $("timeline-note").textContent = window
    ? `Amber band: a legal stop for this tyre order, laps ${window[0]}–${window[1]}.`
    : "No one-stop window for the plan on screen.";
  const onPit = state.mode === "replay" && lapState()?.pit;
  $("pit-flag").hidden = !onPit;
  $("lap-readout").textContent = state.mode === "replay" ? `Lap ${state.lap} / ${raceLaps}` : `Lap 1–${raceLaps}`;
  $("scrub").hidden = state.mode !== "replay";
}

function renderExplain() {
  const event = currentEvent();
  $("explain").textContent = event?.explanation || "No plan yet.";
  $("uncertainty").textContent = event?.uncertainty || "";
}

function card(name, seconds, summary, reason, preferred, rank) {
  return `<article class="card${preferred ? " preferred" : ""}">
      <header><h3><span class="rank">${esc(rank ?? "")}</span>${esc(name)}</h3></header>
      <p class="time">${clock(seconds)}</p>
      <p>${esc(summary)}</p>
      <p>${esc(reason || "")}</p>
    </article>`;
}

function renderCards() {
  if (state.mode === "replay") {
    const event = currentEvent();
    const name = event?.lap ? `From lap ${event.lap}` : "Before the start";
    $("cards").innerHTML = card(name, event?.race_time_sec, event?.summary, event?.why, event?.feasible, "•");
    return;
  }
  const rows = state.compare?.scenarios || [];
  $("cards").innerHTML = rows.map((row) => card(
    row.strategy_name,
    row.race_time_sec,
    row.summary,
    row.ranking_reason || row.why,
    row.preferred,
    row.rank,
  )).join("") || `<p class="fine">No scenarios yet.</p>`;
}

function render() {
  if (!state.replay) return;
  $("event-name").textContent = `${state.replay.season} ${state.replay.event_name}`;
  $("evidence-pill").textContent = state.replay.anchor_pace ? "Evidence C · same-race pace" : "Evidence C";
  renderTower();
  renderTimeline();
  renderExplain();
  renderCards();
}

function setMode(mode) {
  state.mode = mode;
  for (const button of document.querySelectorAll(".mode")) {
    button.classList.toggle("on", button.dataset.mode === mode);
  }
  render();
}

async function refresh(withOverrides) {
  const replayBody = {
    overrides: withOverrides ? overrides() : {},
    anchor_pace: $("anchor-pace").checked,
  };
  state.replay = await postJson(`/v1/replays/${FIXTURE}`, replayBody);
  const compareOverrides = { ...replayBody.overrides };
  if (replayBody.anchor_pace && state.replay.pace_anchor_sec != null) {
    compareOverrides.base_lap_time_sec = state.replay.pace_anchor_sec;
  }
  state.compare = await postJson("/v1/scenarios/compare", {
    series: "f1",
    season: 2024,
    round: 1,
    overrides: compareOverrides,
    scenarios: [{ name: "Recorded", stints: RECORDED }],
  });
  $("lap-slider").max = String(state.replay.race_laps || 57);
  render();
}

async function boot() {
  try {
    state.event = await getJson("/v1/f1/events/2024/1");
    $("pit-loss").value = state.event.pit_lane_loss_sec;
    $("base-lap").value = state.event.base_lap_time_sec;
    $("dry-race").checked = Boolean(state.event.dry_race);
    state.replay = await postJson(`/v1/replays/${FIXTURE}`, {
      overrides: {},
      anchor_pace: false,
    });
    state.compare = await postJson("/v1/scenarios/compare", {
      series: "f1",
      season: 2024,
      round: 1,
      scenarios: [{ name: "Recorded", stints: RECORDED }],
    });
    const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
    if (hash.get("mode") === "replay") {
      state.mode = "replay";
      state.lap = clampLap(hash.get("lap"), state.replay.race_laps || 57);
      $("lap-slider").value = String(state.lap);
      $("mode-replay").classList.add("on");
      $("mode-plan").classList.remove("on");
    }
    render();
  } catch (error) {
    $("explain").textContent = error.message;
  }
}

$("mode-plan").addEventListener("click", () => setMode("plan"));
$("mode-replay").addEventListener("click", () => setMode("replay"));
$("lap-slider").addEventListener("input", (event) => {
  state.lap = Number(event.target.value);
  render();
});
$("builder").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("apply-note").textContent = "Updating the plan from your overrides.";
  try {
    await refresh(true);
    $("apply-note").textContent = "Plan updated. Your numbers replaced the file for this view. The bundled file was not rewritten.";
  } catch (error) {
    $("apply-note").textContent = error.message;
  }
});

document.addEventListener("keydown", (event) => {
  if (state.mode !== "replay" || event.target.matches("input")) return;
  if (event.key === "ArrowRight") state.lap = Math.min(state.replay.race_laps, state.lap + 1);
  if (event.key === "ArrowLeft") state.lap = Math.max(1, state.lap - 1);
  $("lap-slider").value = String(state.lap);
  render();
});

boot();

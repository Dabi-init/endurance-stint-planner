const FIXTURE = "2024-r01-bahrain-verstappen";
const RECORDED = [
  { compound: "SOFT", laps: 17 },
  { compound: "HARD", laps: 20 },
  { compound: "SOFT", laps: 20 },
];

const CATEGORY_COLOUR = { Pro: "#3ee0c5", Silver: "#d5dde6", Bronze: "#e0a15a" };
const SAMPLE_CSV = [
  "lap,driver,lap_time_sec,fuel_remaining_liters",
  ...Array.from({ length: 12 }, (_, index) => {
    const lap = index + 1;
    return `${lap},Alex Pro,${(120 + lap * 0.2).toFixed(1)},${(100 - index * 3).toFixed(1)}`;
  }),
].join("\n");

const state = {
  series: "f1",
  mode: "plan",
  lap: 1,
  replay: null,
  compare: null,
  event: null,
  endurance: null,
  pacePatch: null,
  spoken: "",
  playing: false,
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

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
  if (!events.length || state.mode === "plan") return events[0];
  // A safety-car sentence is about the full-race plan, not a later slice.
  if (state.mode === "live" && liveFrame()?.alert) return events[0];
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
      <span class="meta">${driver.grid ?? "—"}</span>
      <span class="meta">${pip || (driver.finish_position ?? "—")}</span>
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
  const frame = state.mode === "live" ? liveFrame() : null;
  const label = frame?.alert
    ? "Safety-car what-if"
    : state.mode !== "plan" && event?.lap
      ? `From lap ${event.lap}`
      : "Suggested";
  const clips = state.mode === "plan" ? [] : (state.replay?.radio || []);
  const marks = clips.map((clip) => {
    const left = ((Number(clip.lap) - 1) / raceLaps) * 100;
    const on = Number(clip.lap) === state.lap ? " on" : "";
    return `<button type="button" class="radio-mark${on}" style="left:${left}%" data-lap="${Number(clip.lap)}" title="Team radio, lap ${Number(clip.lap)}"></button>`;
  }).join("");
  const radioLane = marks
    ? `<div class="lane"><p>Radio</p><div class="radio-lane">${marks}</div></div>`
    : "";
  $("timeline").innerHTML = `
    <div class="lane"><p>${label}</p><div class="track">${segments(event?.stints || [], planLaps)}${band}</div></div>
    <div class="lane"><p>Recorded</p><div class="track">${segments(recorded, raceLaps)}</div></div>
    ${radioLane}
    <div class="ticks"><span>1</span><span>${Math.round(raceLaps / 2)}</span><span>${raceLaps}</span></div>`;
  for (const mark of $("timeline").querySelectorAll(".radio-mark")) {
    mark.addEventListener("click", () => {
      state.lap = Number(mark.dataset.lap);
      $("lap-slider").value = String(state.lap);
      render();
    });
  }
  $("timeline-note").textContent = window
    ? `Amber band: a legal stop for this tyre order, laps ${window[0]}–${window[1]}.`
    : "No one-stop window for the plan on screen.";
  const onPit = (state.mode === "replay" && lapState()?.pit) || frame?.kind === "pit";
  $("pit-flag").hidden = !onPit;
  $("lap-readout").textContent = state.mode === "plan" ? `Lap 1–${raceLaps}` : `Lap ${state.lap} / ${raceLaps}`;
  $("scrub").hidden = state.mode === "plan";
  const banner = $("live-banner");
  if (frame && (frame.kind === "safety-car" || frame.kind === "vsc" || frame.kind === "pit")) {
    banner.hidden = false;
    banner.textContent = frame.message;
  } else {
    banner.hidden = true;
  }
}

function renderExplain() {
  const event = currentEvent();
  const frame = state.mode === "live" ? liveFrame() : null;
  const lead = frame?.alert ? `${frame.alert} ` : "";
  setExplain(`${lead}${event?.explanation || "No plan yet."}`, event?.uncertainty || "");
}

function setExplain(text, uncertainty) {
  $("explain").textContent = text;
  if (uncertainty != null) $("uncertainty").textContent = uncertainty;
  speakIfNeeded(text);
}

function speakIfNeeded(text) {
  if (!$("speak-call")?.checked || !text) return;
  if (state.spoken === text) return;
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance !== "function") {
    $("speak-note").textContent = "This browser has no speech synthesis.";
    return;
  }
  synth.cancel();
  synth.speak(new SpeechSynthesisUtterance(text));
  state.spoken = text;
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
  if (state.mode === "replay" || state.mode === "live") {
    const event = currentEvent();
    const frame = state.mode === "live" ? liveFrame() : null;
    const name = frame?.alert
      ? "Safety-car what-if"
      : event?.lap
        ? `From lap ${event.lap}`
        : "Before the start";
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
  if (state.series === "endurance") {
    renderEndurance();
    return;
  }
  if (!state.replay) return;
  $("event-name").textContent = `${state.replay.season} ${state.replay.event_name}`;
  $("evidence-pill").textContent = state.replay.anchor_pace ? "Evidence C · same-race pace" : "Evidence C";
  renderTower();
  renderTimeline();
  renderExplain();
  renderCards();
  renderRadio();
}

function setMode(mode) {
  state.mode = mode;
  pauseRecording();
  for (const button of document.querySelectorAll(".mode[data-mode]")) {
    button.classList.toggle("on", button.dataset.mode === mode);
  }
  $("live-tools").hidden = state.series === "endurance" || mode !== "live";
  if (mode !== "live") $("live-banner").hidden = true;
  $("series-kicker").textContent = state.series === "endurance"
    ? "Endurance · synthetic preset"
    : mode === "live"
      ? "Formula 1 · replay feed, not live timing"
      : "Formula 1 · file assumptions";
  render();
}

function liveFrame() {
  return (state.liveFrames || []).find((frame) => frame.lap === state.lap);
}

async function startLive(jumpLap) {
  const params = new URLSearchParams();
  if ($("sc-on").checked) {
    params.set("sc_start", "34");
    params.set("sc_end", "36");
    params.set("sc_pit", "10");
  }
  state.liveFrames = await getJson(`/v1/live/replay/frames?${params.toString()}`);
  const sources = await getJson("/v1/live/sources");
  $("live-source").textContent = sources.map((row) => `${row.id}: ${row.detail}`).join(" ");
  setMode("live");
  state.lap = jumpLap || 1;
  $("lap-slider").max = String(state.liveFrames.length);
  $("lap-slider").value = String(state.lap);
  $("scrub").hidden = false;
  render();
}

function raceLength() {
  return state.replay?.race_laps || (state.liveFrames || []).length || 1;
}

function tickMs() {
  const value = Number($("play-speed").value);
  return value >= 100 && value <= 5000 ? value : 1000;
}

function pauseRecording() {
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = null;
  state.playing = false;
  $("play-recording")?.classList.remove("on");
}

function playRecording() {
  if (state.mode !== "live" && state.mode !== "replay") return;
  const resumeLap = state.lap;
  pauseRecording();
  state.lap = resumeLap >= raceLength() ? 1 : resumeLap;
  $("lap-slider").value = String(state.lap);
  state.playing = true;
  $("play-recording").classList.add("on");
  state.playTimer = setInterval(() => {
    if (state.mode !== "live" && state.mode !== "replay") {
      pauseRecording();
      return;
    }
    if (state.lap >= raceLength()) {
      pauseRecording();
      return;
    }
    state.lap += 1;
    $("lap-slider").value = String(state.lap);
    render();
  }, tickMs());
}

function renderRadio() {
  const box = $("radio-box");
  const show = state.series !== "endurance" && state.mode !== "plan";
  box.hidden = !show;
  if (!show) return;
  const clip = (state.replay?.radio || []).find((row) => row.lap === state.lap);
  const audio = $("team-radio");
  const next = clip ? safeUrl(clip.recording_url) : "";
  if (audio.dataset.src !== next) {
    audio.dataset.src = next;
    if (next) audio.src = next;
    else audio.removeAttribute("src");
    if (next && $("radio-auto").checked) audio.play().catch(() => {});
  }
  $("radio-note").textContent = clip
    ? `Lap ${clip.lap}. OpenF1 link. The browser plays it. Pitwall does not store the audio.`
    : "No team-radio clip on this lap. Clips are OpenF1 links, not stored audio.";
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

function initials(name) {
  return String(name || "?").split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
}

function towerLabels(series) {
  const endurance = series === "endurance";
  $("tower-title").textContent = endurance ? "Crew" : "Timing tower";
  $("tower-blurb").textContent = endurance
    ? "Pro, Silver, and Bronze from the preset. Drive time is the central plan."
    : "Grid and recorded finish. The lap feed is car 1 only.";
  $("tower-col-a").textContent = endurance ? "Drive" : "Grid";
  $("tower-col-b").textContent = endurance ? "min" : "Finish";
  $("mode-replay").hidden = endurance;
  $("mode-live").hidden = endurance;
  $("endurance-tools").hidden = !endurance;
  $("builder").closest("section").hidden = endurance;
  $("live-tools").hidden = endurance || state.mode !== "live";
  $("cards-blurb").textContent = endurance
    ? "P10, median, and P90 laps for each strategy. A second class is a separate plan."
    : "Suggested plan beside the recorded stints.";
  $("series-f1").classList.toggle("on", !endurance);
  $("series-endurance").classList.toggle("on", endurance);
}

function lapCard(name, laps, summary, detail, preferred) {
  return `<article class="card${preferred ? " preferred" : ""}">
      <header><h3>${esc(name)}</h3></header>
      <p class="time">${esc(laps)} laps</p>
      <p>${esc(summary)}</p>
      <p>${esc(detail || "")}</p>
    </article>`;
}

function driveMinutes(plan) {
  const minutes = new Map();
  for (const stint of plan.stints || []) {
    minutes.set(stint.driver, (minutes.get(stint.driver) || 0) + stint.duration_min);
  }
  return minutes;
}

function renderEnduranceTower(plan) {
  const minutes = driveMinutes(plan);
  $("tower").innerHTML = (plan.drivers || []).map((driver) => {
    const driven = minutes.get(driver.full_name) || 0;
    return `<li class="driver">
      <span class="stripe" style="background:${CATEGORY_COLOUR[driver.team_name] || "#d0d7e2"}"></span>
      <div class="who"><span class="initials">${esc(initials(driver.full_name))}</span>
        <div><strong>${esc(driver.full_name)}</strong><span>${esc(driver.team_name)}</span></div>
      </div>
      <span class="meta">${driven ? driven.toFixed(0) : "—"}</span>
      <span class="meta">${esc(driver.team_name)}</span>
    </li>`;
  }).join("");
}

function renderEnduranceTimeline(plan) {
  const stints = plan.stints || [];
  const total = stints.reduce((sum, stint) => sum + stint.duration_min, 0) || 1;
  const drivers = new Map((plan.drivers || []).map((driver) => [driver.full_name, driver.team_name]));
  const bars = stints.map((stint) => {
    const category = drivers.get(stint.driver) || "";
    const width = (stint.duration_min / total) * 100;
    return `<div class="seg" style="width:${width}%;background:${CATEGORY_COLOUR[category] || "#d0d7e2"}">${esc(category)} ${stint.laps}</div>`;
  }).join("");
  $("timeline").innerHTML = `
    <div class="lane"><p>Stints</p><div class="track">${bars}</div></div>
    <div class="ticks"><span>0h</span><span>mid</span><span>finish</span></div>`;
  $("timeline-note").textContent = "Bar length is time in the car. Colour is Pro, Silver, or Bronze from the file.";
  $("pit-flag").hidden = true;
  $("lap-readout").textContent = plan.feasible ? `${plan.predicted_laps} laps` : "No legal plan";
  $("scrub").hidden = true;
}

function renderEndurance() {
  const pack = state.endurance;
  if (!pack?.plan) return;
  const plan = pack.plan;
  $("event-name").textContent = pack.preset.race.race_name;
  $("series-kicker").textContent = "Endurance · synthetic preset";
  $("evidence-pill").textContent = "Evidence C";
  renderEnduranceTower(plan);
  renderEnduranceTimeline(plan);
  const minutes = driveMinutes(plan);
  const crew = (plan.drivers || []).map((driver) => {
    const driven = minutes.get(driver.full_name) || 0;
    return driven
      ? `${driver.full_name} (${driver.team_name}) drives ${driven.toFixed(0)} min`
      : `${driver.full_name} (${driver.team_name}) is not scheduled in this central plan`;
  }).join(". ");
  const safety = pack.safety ? ` ${pack.safety.summary}` : "";
  $("radio-box").hidden = true;
  setExplain(`${plan.summary} ${crew}.${safety}`, plan.uncertainty || pack.preset.note || "");
  if (pack.classes && pack.classes.length > 1) {
    $("cards").innerHTML = pack.classes.map((row) => lapCard(
      row.name,
      row.plan.predicted_laps,
      `${row.plan.pit_stops} stops`,
      row.plan.summary,
      row.name === pack.selected,
    )).join("");
    $("class-note").textContent = pack.classNote || "";
  } else {
    const rows = pack.compare?.scenarios || [];
    $("cards").innerHTML = rows.map((row) => {
      const sim = row.simulation;
      const range = sim ? `P10 ${sim.laps_p10} · median ${sim.laps_median} · P90 ${sim.laps_p90}` : "";
      return lapCard(row.strategy_name, row.predicted_laps, range, row.summary, row.preferred);
    }).join("") || `<p class="fine">No scenarios yet.</p>`;
  }
  const banner = $("live-banner");
  if (pack.safety?.summary) {
    banner.hidden = false;
    banner.textContent = pack.safety.summary;
  } else {
    banner.hidden = true;
  }
}

async function loadEndurance(name) {
  const preset = await getJson(`/v1/endurance/preset?name=${encodeURIComponent(name)}`);
  const race = { ...preset.race, ...(state.pacePatch || {}) };
  const plan = await postJson("/v1/plans", { series: "endurance", race });
  const compare = await postJson("/v1/scenarios/compare", { series: "endurance", race });
  state.endurance = { preset: { ...preset, race }, plan, compare, classes: null, safety: null, selected: $("class-name").value };
  render();
}

async function setSeries(series) {
  state.series = series;
  towerLabels(series);
  if (series !== "endurance") {
    $("series-kicker").textContent = state.mode === "live"
      ? "Formula 1 · replay feed, not live timing"
      : "Formula 1 · file assumptions";
    render();
    return;
  }
  pauseRecording();
  const listed = await getJson("/v1/endurance/presets");
  $("preset-name").innerHTML = listed.presets.map((name) => `<option>${esc(name)}</option>`).join("");
  $("preset-name").value = "6h Endurance";
  await loadEndurance("6h Endurance");
}

async function boot() {
  try {
    state.event = await getJson("/v1/f1/events/2024/1");
    $("pit-loss").value = state.event.pit_lane_loss_sec;
    $("base-lap").value = state.event.base_lap_time_sec;
    $("dry-race").checked = Boolean(state.event.dry_race);
    state.replay = await getJson(`/v1/replays/${FIXTURE}`);
    state.compare = await postJson("/v1/scenarios/compare", {
      series: "f1",
      season: 2024,
      round: 1,
      scenarios: [{ name: "Recorded", stints: RECORDED }],
    });
    const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
    if (hash.get("mode") === "replay") {
      state.mode = "replay";
      state.lap = Number(hash.get("lap") || 1);
      $("lap-slider").value = String(state.lap);
      $("mode-replay").classList.add("on");
      $("mode-plan").classList.remove("on");
    }
    if (hash.get("sc") === "1") $("sc-on").checked = true;
    if (hash.get("speak") === "1") $("speak-call").checked = true;
    render();
    if (hash.get("series") === "endurance") {
      await setSeries("endurance");
    } else if (hash.get("mode") === "live") {
      await startLive(Number(hash.get("lap") || 35));
    }
  } catch (error) {
    $("explain").textContent = error.message;
  }
}

$("series-f1").addEventListener("click", () => setSeries("f1"));
$("series-endurance").addEventListener("click", () => setSeries("endurance"));
$("preset-name").addEventListener("change", () => {
  state.pacePatch = null;
  $("use-pace").hidden = true;
  loadEndurance($("preset-name").value).catch((error) => {
    $("explain").textContent = error.message;
  });
});
$("add-class").addEventListener("click", async () => {
  try {
    const sprint = await getJson(`/v1/endurance/preset?name=${encodeURIComponent("4h Sprint Endurance")}`);
    const result = await postJson("/v1/endurance/classes", {
      classes: [
        { name: $("class-name").value || "GT3", race: state.endurance.preset.race },
        { name: "4h sprint", race: sprint.race },
      ],
    });
    state.endurance.classes = result.classes;
    state.endurance.classNote = result.note;
    state.endurance.selected = $("class-name").value || "GT3";
    state.endurance.plan = result.classes[0].plan;
    render();
  } catch (error) {
    $("class-note").textContent = error.message;
  }
});
$("sc-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("sc-note").textContent = "Re-planning the declared window.";
  try {
    const safety = await postJson("/v1/safety-car", {
      series: "endurance",
      race: state.endurance.preset.race,
      safety_car: {
        deploy_min: Number($("sc-minute").value),
        duration_min: Number($("sc-duration").value),
      },
    });
    state.endurance.safety = safety;
    state.endurance.plan = safety.replanned;
    state.endurance.classes = null;
    $("sc-note").textContent = "What-if applied for this view. The bundled preset was not rewritten.";
    render();
  } catch (error) {
    $("sc-note").textContent = error.message;
  }
});
$("fill-sample").addEventListener("click", () => {
  $("telemetry-csv").value = SAMPLE_CSV;
});
$("telemetry-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const preview = await postJson("/v1/endurance/telemetry", {
      csv: $("telemetry-csv").value,
      synthetic: true,
    });
    state.pacePatch = preview.usable_for_strategy ? preview.config_patch : null;
    $("use-pace").hidden = !preview.usable_for_strategy;
    const median = preview.calibration?.median_lap_time_sec;
    $("telemetry-note").textContent = preview.usable_for_strategy
      ? `Synthetic sample median ${Number(median).toFixed(3)} s. The preset file was not rewritten.`
      : (preview.findings?.[0]?.message || "Those rows are not enough to calibrate pace.");
  } catch (error) {
    state.pacePatch = null;
    $("use-pace").hidden = true;
    $("telemetry-note").textContent = error.message;
  }
});
$("use-pace").addEventListener("click", () => {
  loadEndurance($("preset-name").value).catch((error) => {
    $("telemetry-note").textContent = error.message;
  });
});
$("rain-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const life = $("wet-life").value;
  const body = {
    season: 2024,
    round: 1,
    declared: $("declared-wet").checked ? "wet" : "dry",
  };
  if (life) body.wet_life_laps = Number(life);
  try {
    const result = await postJson("/v1/f1/weather", body);
    const time = result.plan.race_time_sec == null ? "no race time" : `${result.plan.race_time_sec} s`;
    $("rain-note").textContent = `${result.note} ${result.plan.summary} ${time}.`;
    $("explain").textContent = $("rain-note").textContent;
  } catch (error) {
    $("rain-note").textContent = error.message;
  }
});
$("sheet-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const documentBody = {
    series: state.series,
    event: $("event-name").textContent,
    explanation: $("explain").textContent,
  };
  try {
    const saved = await postJson("/v1/sheets", {
      name: $("sheet-name").value,
      document: documentBody,
    });
    const blob = new Blob([JSON.stringify(saved.document, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = saved.name;
    link.click();
    URL.revokeObjectURL(link.href);
    $("sheet-note").textContent = `${saved.note} Saved as ${saved.name}.`;
  } catch (error) {
    $("sheet-note").textContent = error.message;
  }
});
$("accuracy-button").addEventListener("click", async () => {
  $("accuracy-note").textContent = "Reading the bundled Bahrain comparison.";
  try {
    const report = await postJson("/v1/backtests/2024-r01-bahrain-verstappen", {});
    const delta = report.race_time_delta_sec;
    $("accuracy-note").textContent = `Not validated yet. Predicted ${report.predicted_stint_laps.join("/")} laps versus recorded ${report.actual_stint_laps.join("/")}. Race-time gap ${delta} s under file assumptions. ${report.notes[0] || ""}`;
  } catch (error) {
    $("accuracy-note").textContent = error.message;
  }
});
$("terms-button").addEventListener("click", async () => {
  try {
    const terms = await getJson("/v1/terms");
    $("terms-note").textContent = `${terms.openf1} ${terms.jolpica} ${terms.wec || ""} ${terms.commercial}`;
  } catch (error) {
    $("terms-note").textContent = error.message;
  }
});

$("mode-plan").addEventListener("click", () => setMode("plan"));
$("mode-replay").addEventListener("click", () => setMode("replay"));
$("mode-live").addEventListener("click", () => startLive());
$("lap-slider").addEventListener("input", (event) => {
  state.lap = Number(event.target.value);
  render();
});
$("play-live").addEventListener("click", () => playRecording());
$("play-recording").addEventListener("click", () => playRecording());
$("pause-recording").addEventListener("click", () => pauseRecording());
$("play-speed").addEventListener("change", () => {
  if (state.playing) playRecording();
});
$("speak-call").addEventListener("change", () => {
  state.spoken = "";
  if (!$("speak-call").checked && window.speechSynthesis) {
    window.speechSynthesis.cancel();
    return;
  }
  speakIfNeeded($("explain").textContent);
});
$("wec-enable").addEventListener("change", () => {
  $("wec-refresh").disabled = !$("wec-enable").checked;
  if (!$("wec-enable").checked) {
    $("wec-rows").innerHTML = "";
    $("wec-note").textContent = "Off. Nothing is fetched. The feed is not stored or redistributed.";
  }
});
$("wec-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("wec-enable").checked) {
    $("wec-note").textContent = "Turn on personal-use timing before refreshing. Nothing was fetched.";
    return;
  }
  $("wec-note").textContent = "Reading the public timing page for this screen only.";
  try {
    const timing = await getJson("/v1/live/wec?enable=true");
    $("wec-rows").innerHTML = (timing.rows || []).map((row) =>
      `<li><span>${esc(row.position ?? "—")}</span><span>${esc(row.car)}</span><span>${esc(row.team || row.class_name)}</span><span>${row.lap ?? "—"}</span><span>${esc(row.gap)}</span></li>`
    ).join("");
    const session = timing.session ? `${timing.session.event} ${timing.session.name}. ` : "";
    $("wec-note").textContent = `${session}${timing.notice}`;
  } catch (error) {
    $("wec-note").textContent = error.message;
  }
});
$("sc-on").addEventListener("change", () => {
  if (state.mode === "live") startLive(state.lap);
});
$("undercut-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await postJson("/v1/f1/undercut", {
      gap_behind_sec: Number($("gap").value),
      laps_ahead: Number($("laps-ahead").value),
      tyre_gain_sec_per_lap: Number($("tyre-gain").value),
      our_pit_loss_sec: 22,
      their_pit_loss_sec: 22,
    });
    $("undercut-note").textContent = result.explanation;
  } catch (error) {
    $("undercut-note").textContent = error.message;
  }
});
$("odds-button").addEventListener("click", async () => {
  $("odds-note").textContent = "Sampling the file's degradation and pit loss.";
  try {
    const odds = await postJson("/v1/f1/odds", { season: 2024, round: 1, iterations: 64 });
    $("odds-note").textContent = `P10 ${odds.p10_sec} s, median ${odds.p50_sec} s, P90 ${odds.p90_sec} s. ${odds.honesty}`;
  } catch (error) {
    $("odds-note").textContent = error.message;
  }
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

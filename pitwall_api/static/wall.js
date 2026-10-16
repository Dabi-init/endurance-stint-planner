import { renderAccuracy } from "./accuracy-view.js";
import { renderEndurance, towerLabels } from "./endurance-view.js";
import {
  renderCards,
  renderExplain,
  renderRadio,
  renderTimeline,
  renderTower,
  speakIfNeeded,
} from "./f1-view.js";
import { clampLap, esc, getJson, postJson } from "./format.js";
import { $, FIXTURE, RECORDED, SAMPLE_CSV, state } from "./state.js";

function overrides() {
  return {
    pit_lane_loss_sec: Number($("pit-loss").value),
    base_lap_time_sec: Number($("base-lap").value),
    dry_race: $("dry-race").checked,
  };
}

function render() {
  if (state.series === "endurance") {
    renderEndurance();
    renderRadio();
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

state.paint = render;

function setMode(mode) {
  state.mode = mode;
  pauseRecording();
  for (const button of document.querySelectorAll(".mode[data-mode]")) {
    button.classList.toggle("on", button.dataset.mode === mode);
  }
  $("live-tools").hidden = state.series === "endurance" || mode !== "live";
  if (mode !== "live") $("live-banner").hidden = true;
  const accuracy = mode === "accuracy";
  $("accuracy-page").hidden = !accuracy;
  $("wall").hidden = accuracy;
  if (accuracy) renderAccuracy();
  $("series-kicker").textContent = accuracy
    ? "Formula 1 · post-session accuracy log"
    : state.series === "endurance"
    ? "Endurance · synthetic preset"
    : mode === "live"
      ? "Formula 1 · replay feed, not live timing"
      : "Formula 1 · file assumptions";
  render();
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
  state.lap = clampLap(jumpLap, state.liveFrames.length || state.replay?.race_laps || 57);
  $("lap-slider").max = String(state.liveFrames.length);
  $("lap-slider").value = String(state.lap);
  $("scrub").hidden = false;
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

async function loadEndurance(name) {
  const preset = await getJson(`/v1/endurance/preset?name=${encodeURIComponent(name)}`);
  const race = { ...preset.race, ...(state.pacePatch || {}) };
  const plan = await postJson("/v1/plans", { series: "endurance", race });
  const compare = await postJson("/v1/scenarios/compare", { series: "endurance", race });
  state.endurance = {
    preset: { ...preset, race },
    plan,
    compare,
    classes: null,
    safety: null,
    selected: $("class-name").value,
  };
  render();
}

async function setSeries(series) {
  state.series = series;
  if (series === "endurance") pauseRecording();
  towerLabels(series);
  if (series !== "endurance") {
    $("series-kicker").textContent = state.mode === "live"
      ? "Formula 1 · replay feed, not live timing"
      : "Formula 1 · file assumptions";
    render();
    return;
  }
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
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
    if (hash.get("sc") === "1") $("sc-on").checked = true;
    if (hash.get("speak") === "1") $("speak-call").checked = true;
    render();
    if (hash.get("series") === "endurance") {
      await setSeries("endurance");
    } else if (hash.get("mode") === "live") {
      await startLive(hash.get("lap") || 35);
    } else if (hash.get("mode") === "accuracy") {
      setMode("accuracy");
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
    const predictedStops = (report.predicted_stop_laps || []).join(", ") || "none";
    const recordedStops = (report.actual_stop_laps || []).join(", ") || "none";
    $("accuracy-note").textContent = `Not validated yet. Predicted stop laps ${predictedStops} versus recorded stop laps ${recordedStops}. Predicted ${report.predicted_stint_laps.join("/")} laps versus recorded ${report.actual_stint_laps.join("/")}. Race-time gap ${delta} s under file assumptions. ${report.notes[0] || ""}`;
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
function raceLength() {
  return state.replay?.race_laps || (state.liveFrames || []).length || 1;
}

function tickMs() {
  const value = Number($("play-speed")?.value);
  return value >= 100 && value <= 5000 ? value : 1000;
}

function pauseRecording() {
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = null;
  state.playing = false;
  $("play-recording")?.classList.remove("on");
}

function playRecording() {
  if (state.series === "endurance") return;
  if (state.mode !== "live" && state.mode !== "replay") return;
  const resumeLap = state.lap;
  pauseRecording();
  state.lap = resumeLap >= raceLength() ? 1 : resumeLap;
  $("lap-slider").value = String(state.lap);
  state.playing = true;
  $("play-recording")?.classList.add("on");
  state.playTimer = setInterval(() => {
    if (state.series === "endurance" || (state.mode !== "live" && state.mode !== "replay")) {
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

$("play-live")?.addEventListener("click", () => playRecording());
$("play-recording")?.addEventListener("click", () => playRecording());
$("pause-recording")?.addEventListener("click", () => pauseRecording());
$("play-speed")?.addEventListener("change", () => {
  if (state.playing) playRecording();
});
$("speak-call")?.addEventListener("change", () => {
  state.spoken = "";
  if (!$("speak-call").checked && window.speechSynthesis) {
    window.speechSynthesis.cancel();
    return;
  }
  speakIfNeeded($("explain").textContent);
});
$("wec-enable")?.addEventListener("change", () => {
  $("wec-refresh").disabled = !$("wec-enable").checked;
  if (!$("wec-enable").checked) {
    $("wec-rows").innerHTML = "";
    $("wec-note").textContent = "Off. Nothing is fetched. The feed is not stored or redistributed.";
  }
});
$("wec-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("wec-enable").checked) {
    $("wec-note").textContent = "Turn on personal-use timing before refreshing. Nothing was fetched.";
    return;
  }
  $("wec-note").textContent = "Reading the public timing page for this screen only.";
  try {
    const timing = await getJson("/v1/live/wec?enable=true");
    $("wec-rows").innerHTML = (timing.rows || []).map((row) =>
      `<li><span>${esc(row.position ?? "—")}</span><span>${esc(row.car)}</span><span>${esc(row.team || row.class_name)}</span><span>${esc(row.lap ?? "—")}</span><span>${esc(row.gap)}</span></li>`
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
      out_lap_warmup_sec: Number($("out-lap").value),
      in_lap_delta_sec: Number($("in-lap").value),
      traffic_avoided_sec: Number($("traffic").value),
    });
    $("undercut-note").textContent = result.explanation;
  } catch (error) {
    $("undercut-note").textContent = error.message;
  }
});
$("odds-button").addEventListener("click", async () => {
  $("odds-note").textContent = "Sampling the file's degradation and pit loss as a race-time spread.";
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
  if (state.series === "endurance" || state.mode !== "replay" || event.target.matches("input, textarea, select")) return;
  if (event.key === "ArrowRight") state.lap = Math.min(state.replay.race_laps, state.lap + 1);
  if (event.key === "ArrowLeft") state.lap = Math.max(1, state.lap - 1);
  $("lap-slider").value = String(state.lap);
  render();
});

boot();

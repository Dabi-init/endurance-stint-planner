import { clock, colour, esc, safeUrl } from "./format.js";
import { $, state } from "./state.js";

export function liveFrame() {
  return (state.liveFrames || []).find((frame) => frame.lap === state.lap);
}

export function currentEvent() {
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

export function renderTower() {
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

export function renderTimeline() {
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
      state.paint?.();
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

export function speakIfNeeded(text) {
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

export function setExplain(text, uncertainty) {
  $("explain").textContent = text;
  if (uncertainty != null) $("uncertainty").textContent = uncertainty;
  speakIfNeeded(text);
}

export function renderExplain() {
  const event = currentEvent();
  const frame = state.mode === "live" ? liveFrame() : null;
  const lead = frame?.alert ? `${frame.alert} ` : "";
  setExplain(`${lead}${event?.explanation || "No plan yet."}`, event?.uncertainty || "");
}

function httpsUrls(clip) {
  const listed = Array.isArray(clip.recording_urls)
    ? clip.recording_urls
    : [clip.recording_url];
  return listed.filter((url) => typeof url === "string" && url.startsWith("https://"));
}

export function renderRadio() {
  const box = $("radio-box");
  if (!box) return;
  const show = state.series !== "endurance" && state.mode !== "plan";
  box.hidden = !show;
  if (!show) {
    const quiet = $("team-radio");
    if (quiet && quiet.dataset.src) {
      quiet.pause();
      quiet.removeAttribute("src");
      quiet.load();
      quiet.dataset.src = "";
    }
    return;
  }
  const clips = (state.replay?.radio || []).filter((row) => Number(row.lap) === state.lap);
  const urls = clips.flatMap(httpsUrls);
  const audio = $("team-radio");
  const next = urls[0] || "";
  if (audio.dataset.src !== next) {
    audio.pause();
    audio.dataset.src = next;
    if (next) {
      audio.src = next;
    } else {
      audio.removeAttribute("src");
      audio.load();
    }
    if (next && $("radio-auto")?.checked) audio.play().catch(() => {});
  }
  $("radio-note").textContent = urls.length
    ? `Lap ${state.lap}. ${urls.length} OpenF1 link${urls.length === 1 ? "" : "s"}. The browser plays the first. Pitwall does not store the audio.`
    : "No team-radio clip on this lap. Clips are OpenF1 links, not stored audio.";
}

function card(name, seconds, summary, reason, preferred, rank) {
  return `<article class="card${preferred ? " preferred" : ""}">
      <header><h3><span class="rank">${esc(rank ?? "")}</span>${esc(name)}</h3></header>
      <p class="time">${clock(seconds)}</p>
      <p>${esc(summary)}</p>
      <p>${esc(reason || "")}</p>
    </article>`;
}

export function renderCards() {
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

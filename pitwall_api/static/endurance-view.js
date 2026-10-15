import { esc } from "./format.js";
import { $, CATEGORY_COLOUR, state } from "./state.js";

export function towerLabels(series) {
  const endurance = series === "endurance";
  $("tower-title").textContent = endurance ? "Crew" : "Timing tower";
  $("tower-blurb").textContent = endurance
    ? "Pro, Silver, and Bronze from the preset. Drive time is the central plan. Classes do not interact."
    : "Grid and recorded finish. The lap feed is car 1 only.";
  $("tower-col-a").textContent = endurance ? "Drive" : "Grid";
  $("tower-col-b").textContent = endurance ? "min" : "Finish";
  $("mode-replay").hidden = endurance;
  $("mode-live").hidden = endurance;
  $("endurance-tools").hidden = !endurance;
  $("builder").closest("section").hidden = endurance;
  $("live-tools").hidden = endurance || state.mode !== "live";
  $("cards-blurb").textContent = endurance
    ? "P10, median, and P90 laps for each strategy. Classes do not interact."
    : "Suggested plan beside the recorded stints.";
  $("series-f1").classList.toggle("on", !endurance);
  $("series-endurance").classList.toggle("on", endurance);
}

function initials(name) {
  return String(name || "?").split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
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
  $("radio-box") && ($("radio-box").hidden = true);
}

export function renderEndurance() {
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
  $("explain").textContent = `${plan.summary} ${crew}.${safety}`;
  $("uncertainty").textContent = plan.uncertainty || pack.preset.note || "";
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

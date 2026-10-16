import { esc, getJson } from "./format.js";

const SEASON = 2026;

export async function renderAccuracy() {
  const notice = document.querySelector("#accuracy-notice");
  const honesty = document.querySelector("#accuracy-honesty");
  const rates = document.querySelector("#accuracy-rates");
  const assumption = document.querySelector("#accuracy-assumption");
  const log = document.querySelector("#accuracy-log");
  notice.textContent = "Unofficial, not affiliated with Formula 1.";
  try {
    const payload = await getJson(`/v1/accuracy/${SEASON}`);
    notice.textContent = payload.notice;
    honesty.textContent = `Not validated yet. Through ${payload.as_of}. ${payload.honesty}`;
    assumption.textContent = payload.assumption;
    rates.innerHTML = rateCards(payload.rates);
    const races = payload.races || [];
    log.innerHTML = races.map((race, index) => raceBlock(race, index === 0)).join("");
    if (!races.length) {
      log.textContent = "No completed race is in this log yet.";
    }
  } catch (error) {
    honesty.textContent = error.message;
  }
}

function rateCards(rates) {
  return [
    ["Pit-lap error", laps(rates.pit_lap_mae)],
    ["Stint-length error", laps(rates.stint_length_mae)],
    ["Stop-count error", laps(rates.stop_count_mae)],
    ["Undercut error", percent(rates.undercut_error_rate)],
    ["Finish-order error", laps(rates.finish_order_mae)],
  ]
    .map(
      ([label, value]) =>
        `<p class="rate"><span>${esc(label)}</span><strong>${esc(value)}</strong></p>`,
    )
    .join("");
}

function raceBlock(race, open) {
  const rates = race.rates || {};
  let note = "";
  if (race.wet_tyres_seen) {
    note = " Wet tyres were in the stints, so this race stays out of the strategy rates.";
  }
  if (!race.plan_feasible) note += " The planner had no legal plan.";
  return `<details class="accuracy-race"${open ? " open" : ""}>
<summary>Round ${esc(race.round)} · ${esc(race.event_name)} · ${esc(race.race_date)} · pit ${esc(laps(rates.pit_lap_mae))} · stints ${esc(laps(rates.stint_length_mae))} · undercut ${esc(percent(rates.undercut_error_rate))} · finish ${esc(laps(rates.finish_order_mae))}</summary>
<p class="fine">Predicted stops ${esc(join(race.predicted_stop_laps))} · predicted stints ${esc(join(race.predicted_stint_laps))}.${esc(note)} ${esc(race.plan_message || "")}</p>
<table>
<thead><tr><th>Driver</th><th>Qualifying</th><th>Finish</th><th>Actual stops</th><th>Actual stints</th><th>Pit error</th><th>Stint error</th></tr></thead>
<tbody>
${(race.drivers || []).map(driverRow).join("")}
</tbody>
</table>
</details>`;
}

function driverRow(driver) {
  let finish = driver.actual_finish_rank == null ? "—" : String(driver.actual_finish_rank);
  if (driver.status && driver.status !== "classified") finish = driver.status;
  return `<tr><td>${esc(driver.code)}</td><td>${esc(driver.qualifying_position ?? "—")}</td><td>${esc(finish)}</td><td>${esc(join(driver.actual_stop_laps))}</td><td>${esc(join(driver.actual_stint_laps))}</td><td>${esc(laps(driver.pit_lap_mae))}</td><td>${esc(laps(driver.stint_length_mae))}</td></tr>`;
}

function laps(value) {
  return value == null ? "—" : Number(value).toFixed(3);
}

function percent(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

function join(values) {
  return Array.isArray(values) && values.length ? values.join(", ") : "—";
}

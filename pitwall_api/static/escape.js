export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

export function clampLap(value, raceLaps) {
  const laps = Number(raceLaps);
  const limit = Number.isInteger(laps) && laps >= 1 ? laps : 1;
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) return 1;
  return Math.min(limit, Math.max(1, parsed));
}

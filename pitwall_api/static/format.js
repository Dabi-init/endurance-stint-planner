export { clampLap, esc } from "./escape.js";

export function safeUrl(url) {
  return typeof url === "string" && url.startsWith("https://") ? url : "";
}

export function colour(value) {
  if (typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)) return value;
  if (typeof value === "string" && /^[0-9a-fA-F]{6}$/.test(value)) return `#${value}`;
  return "#d0d7e2";
}

export function clock(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds * 1000);
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const secs = Math.floor((total % 60000) / 1000);
  const ms = total % 1000;
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${hours}:${pad(minutes)}:${pad(secs)}.${pad(ms, 3)}`;
}

export async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

export async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

export const FIXTURE = "2024-r01-bahrain-verstappen";
export const RECORDED = [
  { compound: "SOFT", laps: 17 },
  { compound: "HARD", laps: 20 },
  { compound: "SOFT", laps: 20 },
];

export const CATEGORY_COLOUR = { Pro: "#3ee0c5", Silver: "#d5dde6", Bronze: "#e0a15a" };
export const SAMPLE_CSV = [
  "lap,driver,lap_time_sec,fuel_remaining_liters",
  ...Array.from({ length: 12 }, (_, index) => {
    const lap = index + 1;
    return `${lap},Alex Pro,${(120 + lap * 0.2).toFixed(1)},${(100 - index * 3).toFixed(1)}`;
  }),
].join("\n");

export const state = {
  series: "f1",
  mode: "plan",
  lap: 1,
  replay: null,
  compare: null,
  event: null,
  endurance: null,
  pacePatch: null,
};

export const $ = (id) => document.getElementById(id);

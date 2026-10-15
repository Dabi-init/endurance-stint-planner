import assert from "node:assert/strict";
import test from "node:test";

import { clampLap, esc } from "../../pitwall_api/static/escape.js";

test("esc encodes markup that would otherwise run in the tower", () => {
  assert.equal(
    esc(`<img src=x onerror="alert(1)">`),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
  );
  assert.equal(esc("a&b"), "a&amp;b");
  assert.equal(esc(null), "");
});

test("clampLap keeps a replay deep link inside the race", () => {
  assert.equal(clampLap(0, 57), 1);
  assert.equal(clampLap("999", 57), 57);
  assert.equal(clampLap("abc", 57), 1);
  assert.equal(clampLap("4", 57), 4);
  assert.equal(clampLap(1.5, 57), 1);
});

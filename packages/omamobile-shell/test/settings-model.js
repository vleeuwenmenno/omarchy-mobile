// SPDX-License-Identifier: MIT
// The shared geometry model the launcher and Settings read, and that it agrees
// with the helper's limits.
const test = require("node:test")
const assert = require("node:assert")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const { execFileSync } = require("node:child_process")

const root = path.join(__dirname, "..")
const source = fs.readFileSync(path.join(root, "plugins/omamobile.launcher/SettingsGeometry.js"), "utf8")
const M = vm.runInNewContext(source + "\n({GAP_MIN, GAP_MAX, GAP_DEFAULT, SCALE_MIN, SCALE_MAX, parse, bottomGap, stepGap, stepScale, formatScale, clampGap})")

test("a missing or damaged file is the default gap", () => {
  for (const text of ["", "{", "[]", "null", "{\"keyboard\":5}", "{\"keyboard\":{}}", "{\"keyboard\":{\"bottom_gap\":\"x\"}}", "{\"keyboard\":{\"bottom_gap\":true}}"])
    assert.strictEqual(M.bottomGap(M.parse(text)), 24, text)
  assert.strictEqual(M.bottomGap(null), 24)
})

test("the gap is read inside its limits", () => {
  const gap = (v) => M.bottomGap(M.parse(JSON.stringify({ keyboard: { bottom_gap: v } })))
  assert.strictEqual(gap(40), 40)
  assert.strictEqual(gap(10), 24)
  assert.strictEqual(gap(500), 64)
  assert.strictEqual(gap(33.6), 34)
})

test("steps stay inside the limits", () => {
  assert.strictEqual(M.stepGap(24, -1), 24)
  assert.strictEqual(M.stepGap(64, 1), 64)
  assert.strictEqual(M.stepGap(24, 1), 28)
  assert.strictEqual(M.stepScale(0.5, -1), 0.5)
  assert.strictEqual(M.stepScale(2, 1), 2)
  assert.strictEqual(M.stepScale(1.8, 1), 1.9)
  assert.strictEqual(M.stepScale(1.35, 1), 1.45)
  assert.strictEqual(M.formatScale(1.8), "1.8×")
  assert.strictEqual(M.formatScale(1), "1×")
})

test("the limits equal the helper's", () => {
  const status = JSON.parse(execFileSync("python3", ["-B", path.join(root, "bin/omamobile-settings"), "status"],
    { env: { ...process.env, OMAMOBILE_GSETTINGS: "/nonexistent", OMAMOBILE_SETTINGS_FILE: "/nonexistent/settings.json" } }))
  assert.deepStrictEqual(status.limits, { scale: [M.SCALE_MIN, M.SCALE_MAX], gap: [M.GAP_MIN, M.GAP_MAX], gap_default: M.GAP_DEFAULT })
})

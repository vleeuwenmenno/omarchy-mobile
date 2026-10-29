// SPDX-License-Identifier: MIT
// Node tests for plugins/omamobile.quicksettings/LocationModel.js. Run by test/all.
"use strict"
const assert = require("assert")
const fs = require("fs")
const path = require("path")
const file = path.join(__dirname, "../plugins/omamobile.quicksettings/LocationModel.js")
const M = new Function("exports", fs.readFileSync(file, "utf8") +
  ";exports.parse=parse;exports.tileStatus=tileStatus;exports.when=when;exports.duration=duration;" +
  "exports.title=title;exports.processLine=processLine;exports.timing=timing;exports.coverage=coverage;exports.finished=finished")
const m = {}
M(m)

const tests = []
const test = (name, fn) => tests.push([name, fn])
const base = { available: true, enabled: true, running: false, busy: false, failed: false, usage: null }
const full = { active: [], manager_in_use: false, unknown_active: 0, coverage: "full" }
const status = (over) => m.tileStatus(Object.assign({}, base, over))

test("permission Off stays Off even when the observer reports use", () => {
  assert.strictEqual(status({ enabled: false, running: true, usage: Object.assign({}, full, { manager_in_use: true }) }), "Off")
})
test("On is permission alone; In use needs a known client or GeoClue's InUse", () => {
  assert.strictEqual(status({ usage: full }), "On")
  assert.strictEqual(status({ usage: Object.assign({}, full, { active: [{}] }) }), "In use")
  assert.strictEqual(status({ usage: Object.assign({}, full, { manager_in_use: true }) }), "In use")
  assert.strictEqual(status({ usage: Object.assign({}, full, { unknown_active: 1 }) }), "On")
})
test("a running receiver nobody vouches for is Receiver on, never In use", () => {
  assert.strictEqual(status({ running: true, usage: null }), "Receiver on")
  assert.strictEqual(status({ running: true, usage: Object.assign({}, full, { coverage: "partial" }) }), "Receiver on")
  assert.strictEqual(status({ running: true, usage: full }), "On")
  assert.strictEqual(status({ running: false, usage: null }), "On")
})
test("busy and failed toggles say so; no backend says No GNSS", () => {
  assert.strictEqual(status({ busy: true }), "Turning off…")
  assert.strictEqual(status({ busy: true, enabled: false }), "Turning on…")
  assert.strictEqual(status({ failed: true }), "Failed")
  assert.strictEqual(status({ available: false }), "No GNSS")
})
test("parse accepts only an available JSON object", () => {
  assert.strictEqual(m.parse("{not"), null)
  assert.strictEqual(m.parse('{"available": false, "error": "x"}'), null)
  assert.strictEqual(m.parse(""), null)
  assert.deepStrictEqual(m.parse('{"available": true, "a": 1}\n'), { available: true, a: 1 })
})
test("entries read as app, process and time without claiming identity", () => {
  const now = new Date(2026, 9, 29, 15, 0)
  const start = new Date(2026, 9, 29, 14, 2).getTime() / 1000
  const done = { app: "org.example.Maps", process: "maps", pid: 42, started: start, ended: start + 185, end_reason: "stopped", active: false }
  assert.strictEqual(m.title(done), "org.example.Maps")
  assert.strictEqual(m.processLine(done), "maps (PID 42)")
  assert.strictEqual(m.timing(done, false, now), "14:02 · 3 min · Stopped")
  assert.strictEqual(m.timing(Object.assign({}, done, { active: true, ended: null, end_reason: null }), true, now), "In use since 2:02 PM")
  assert.strictEqual(m.title({ process: "x" }), "x")
  assert.strictEqual(m.title({}), "Unknown app")
  assert.strictEqual(m.processLine({ app: "a" }), "Process not identified")
  const unknownEnd = { started: start, ended: null, end_reason: "monitor-restarted", active: false }
  assert.strictEqual(m.timing(unknownEnd, false, now), "14:02 · End time unknown")
  assert.match(m.timing(Object.assign({}, unknownEnd, {end_reason: "events-lost"}), false, now), /Monitoring interrupted.*end time unknown/)
  assert.match(m.timing(Object.assign({}, unknownEnd, {end_reason: "uncertain"}), false, now), /End time unknown/)
  assert.strictEqual(m.when(new Date(2026, 9, 28, 9, 5).getTime() / 1000, false, now), "28 Oct 09:05")
})
test("durations", () => {
  assert.deepStrictEqual([5, 60, 3599, 3600, 3720].map(m.duration), ["5 s", "1 min", "59 min", "1 h", "1 h 2 min"])
})
test("coverage text is honest about partial and unavailable monitoring", () => {
  const now = new Date(2026, 9, 29, 15, 0)
  const since = new Date(2026, 9, 29, 8, 0).getTime() / 1000
  assert.match(m.coverage(null, false, now), /unavailable/)
  assert.strictEqual(m.coverage({ coverage: "full", coverage_since: since }, false, now), "Monitoring since 08:00.")
  assert.match(m.coverage({ coverage: "partial", coverage_note: "Earlier uses may be missing.", coverage_since: since }, false, now), /Earlier uses may be missing/)
  assert.strictEqual(m.finished([{ active: true }, { active: false }, { active: false }]), 2)
})

test("the hidden panel does not poll and the tile never flips before the real state", () => {
  const dir = path.join(__dirname, "../plugins/omamobile.quicksettings")
  const panel = fs.readFileSync(path.join(dir, "LocationPanel.qml"), "utf8")
  assert.match(panel, /Timer \{[^}]*running: root\.opened/)
  assert.doesNotMatch(panel, /running: true/)
  const qml = fs.readFileSync(path.join(dir, "QuickSettings.qml"), "utf8")
  const tile = qml.slice(qml.indexOf("id: location\n"), qml.indexOf("id: locationRead"))
  assert.ok(tile.includes("toggle()"))
  assert.doesNotMatch(tile, /enabled = !enabled/)
})

let failed = 0
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name) } catch (error) { failed++; console.log("not ok - " + name + "\n" + error.message) }
}
process.exit(failed ? 1 : 0)

// SPDX-License-Identifier: MIT
// The bottom-edge swipe up: quick goes home, a pause arms recents, a short
// drag springs back, and jitter in position or speed changes none of that.
const test = require("node:test")
const assert = require("node:assert")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

const root = path.join(__dirname, "..")
const source = fs.readFileSync(path.join(root, "plugins/omamobile.gestures/NavGesture.js"), "utf8")
const G = vm.runInNewContext(source + "\n({HOLD_MS, track, shouldArm, release})")

const limits = { armLift: 64, homeLift: 56, flingLift: 24, flingSpeed: 0.6, holdMs: G.HOLD_MS }
const radius = 12

// Replays finger samples [t, x, y] the way the switcher sees them: each move
// tracks the anchor, and a timer due HOLD_MS after the latest fresh anchor
// may arm. Returns the decision at release with the last sample's velocity.
function replay(samples, vyAtRelease, apps) {
  let anchor = null
  let armed = false
  let due = Infinity
  for (const [t, x, y] of samples) {
    if (due <= t && !armed) armed = G.shouldArm(anchor, due, Math.max(0, -anchor.y), limits, apps)
    const next = G.track(anchor, x, y, t, radius)
    if (next !== anchor) { anchor = next; due = t + limits.holdMs }
  }
  const [lastT, , lastY] = samples[samples.length - 1]
  if (!armed && due <= lastT) armed = G.shouldArm(anchor, lastT, Math.max(0, -lastY), limits, apps)
  return { armed, action: G.release(armed, Math.max(0, -lastY), vyAtRelease, limits) }
}

test("a quick swipe up goes home", () => {
  const swipe = [[0, 0, 0], [16, 0, -60], [32, 2, -160], [48, 3, -280]]
  assert.deepStrictEqual(replay(swipe, -4, 3), { armed: false, action: "home" })
})

test("a slow swipe up without a pause still goes home", () => {
  const slow = []
  for (let t = 0; t <= 900; t += 30) slow.push([t, 0, -t * 0.25])
  assert.deepStrictEqual(replay(slow, -0.25, 3), { armed: false, action: "home" })
})

test("swipe up and pause arms recents, and release keeps them", () => {
  const pause = [[0, 0, 0], [16, 0, -80], [32, 0, -150], [100, 0, -152], [200, 0, -150], [260, 0, -151]]
  assert.deepStrictEqual(replay(pause, 0, 3), { armed: true, action: "recents" })
})

test("a wobble inside the circle is still a pause", () => {
  const wobble = [[0, 0, 0], [20, 0, -120], [60, 8, -128], [120, -6, -114], [180, 5, -126], [240, -4, -118]]
  assert.strictEqual(replay(wobble, 0.9, 3).action, "recents")
})

test("a fast reading at release does not undo an armed pause", () => {
  const pause = [[0, 0, 0], [20, 0, -120], [240, 0, -121]]
  assert.strictEqual(replay(pause, -3, 3).action, "recents")
  assert.strictEqual(replay(pause, 3, 3).action, "recents")
})

test("a pause too low, too short, or with nothing open does not arm", () => {
  assert.strictEqual(replay([[0, 0, 0], [20, 0, -40], [300, 0, -40]], 0, 3).armed, false)
  assert.strictEqual(replay([[0, 0, 0], [20, 0, -150], [150, 0, -150]], 0, 3).armed, false)
  const empty = replay([[0, 0, 0], [20, 0, -150], [400, 0, -150]], 0, 0)
  assert.deepStrictEqual(empty, { armed: false, action: "home" })
})

test("dragging back down after arming cancels", () => {
  assert.strictEqual(replay([[0, 0, 0], [20, 0, -150], [260, 0, -150], [320, 0, -10]], 0.5, 3).action, "cancel")
})

test("a small drag springs back; a short fast flick goes home", () => {
  assert.strictEqual(G.release(false, 10, -3, limits), "cancel")
  assert.strictEqual(G.release(false, 40, -0.2, limits), "cancel")
  assert.strictEqual(G.release(false, 40, -0.8, limits), "home")
  assert.strictEqual(G.release(true, 10, 0, limits), "cancel")
})

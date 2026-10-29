// SPDX-License-Identifier: MIT
// What a swipe up from the bottom edge means, after iOS: a quick swipe goes
// home; swipe up and pause, and recent apps arm (a preview and one tick of
// feedback), and letting go then keeps recents on screen. A short drag that
// does neither springs back.
//
// The pause is told by where the finger is, never by its speed: the finger
// has to stay within a small circle for HOLD_MS. A wobble inside the circle
// keeps the pause going; leaving it starts a new one. Release speed is only
// used to let a short, fast flick count as a swipe home, and only when recents
// are not armed, so a jittery reading at lift-off cannot turn a pause into
// home or a swipe into recents.
//
// Pure functions, shared by omamobile.switcher and test/nav-gesture.js.
// Distances are in the caller's logical pixels; times in milliseconds;
// velocity in pixels per millisecond, negative upward.

var HOLD_MS = 150

// The point the pause is measured from: kept while the finger stays within
// `radius` of it, else a fresh one where the finger is now.
function track(anchor, x, y, now, radius) {
  if (anchor && Math.abs(x - anchor.x) <= radius && Math.abs(y - anchor.y) <= radius) return anchor
  return { x: x, y: y, t: now }
}

// Arm recents: paused long enough, high enough, and there is something to
// show (with no apps open, recents would be empty, so the swipe stays home).
function shouldArm(anchor, now, lift, limits, appCount) {
  if (!anchor || appCount <= 0) return false
  if (lift < limits.armLift) return false
  return now - anchor.t >= (limits.holdMs || HOLD_MS)
}

// On release: "recents", "home" or "cancel".
function release(armed, lift, vy, limits) {
  if (lift < limits.flingLift) return "cancel"
  if (armed) return "recents"
  if (lift >= limits.homeLift) return "home"
  if (vy <= -limits.flingSpeed) return "home"
  return "cancel"
}

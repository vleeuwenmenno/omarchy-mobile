// SPDX-License-Identifier: MIT
// The Settings app's shared, read-only geometry model: what the launcher's
// dock and the Settings > Keyboard page both read from
// ~/.config/omamobile/settings.json. Only bin/omamobile-settings writes that
// file (validated, atomically); here it is parsed, never changed. The limits
// match the helper's and test/settings-model.js checks they stay equal.
//
//   { "version": 1, "keyboard": { "bottom_gap": 24 } }
//
// bottom_gap is the height of the navigation strip under the app drawer and
// the on-screen keyboard, in the shell's logical pixels (scaled with the
// theme's spacing scale, like the rest of the shell). The keyboard sits above
// the dock's exclusive zone, so this is the clearance for the bottom gestures.

var GAP_MIN = 24
var GAP_MAX = 64
var GAP_DEFAULT = 24
var GAP_STEP = 4
var SCALE_MIN = 0.5
var SCALE_MAX = 2.0
var SCALE_STEP = 0.1

function clampGap(value) {
  var n = Number(value)
  if (value === null || value === undefined || value === "" || typeof value === "boolean" || !isFinite(n)) return GAP_DEFAULT
  return Math.max(GAP_MIN, Math.min(GAP_MAX, Math.round(n)))
}

// The file's text as settings: anything missing or unreadable is the default.
function parse(text) {
  var data = null
  try { data = JSON.parse(String(text || "")) } catch (error) { data = null }
  var keyboard = data && typeof data === "object" && data.keyboard && typeof data.keyboard === "object" ? data.keyboard : {}
  return { keyboard: { bottomGap: clampGap(keyboard.bottom_gap) } }
}

function bottomGap(settings) {
  return settings && settings.keyboard ? clampGap(settings.keyboard.bottomGap) : GAP_DEFAULT
}

function stepGap(value, direction) {
  return clampGap(clampGap(value) + direction * GAP_STEP)
}

function clampScale(value) {
  var n = Number(value)
  if (!isFinite(n)) return 1.0
  return Math.round(Math.max(SCALE_MIN, Math.min(SCALE_MAX, n)) * 100) / 100
}

function stepScale(value, direction) {
  return clampScale(Math.round((clampScale(value) + direction * SCALE_STEP) * 100) / 100)
}

function formatScale(value) {
  return String(Number(clampScale(value).toFixed(2))) + "×"
}

// SPDX-License-Identifier: MIT
pragma Singleton
import QtQuick
// The system bottom-edge gesture, shared like PullState: the dock
// (omamobile.launcher) owns the touch strip and publishes the finger here;
// the switcher (omamobile.switcher) animates it and decides what it does.
// `attached` says a switcher is listening (a count, as a reloading plugin
// may attach anew before its old instance detaches); without one the dock
// falls back to summoning recents on an upward swipe.
QtObject {
  property int listeners: 0
  readonly property bool attached: listeners > 0
  property bool pressed: false
  property bool active: false
  property real dx: 0
  property real dy: 0
  // Pixels per millisecond, as the dock's other drags measure it.
  property real vx: 0
  property real vy: 0
  signal primed()
  signal started()
  signal ended(bool canceled)
  signal held()
  function press() { pressed = true; primed() }
  function release() { pressed = false }
  function begin() { dx = 0; dy = 0; vx = 0; vy = 0; active = true; started() }
  function update(x, y, velocityX, velocityY) { dx = x; dy = y; vx = velocityX; vy = velocityY }
  function finish(canceled) {
    if (!active) return
    active = false
    ended(canceled === true)
  }
  function hold() { held() }
}

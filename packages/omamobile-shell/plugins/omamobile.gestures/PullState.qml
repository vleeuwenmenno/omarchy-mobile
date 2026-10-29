// SPDX-License-Identifier: MIT
pragma Singleton
import QtQuick
QtObject {
  property bool active: false
  property real distance: 0
  function begin(distance) { this.distance = distance; active = true }
  function update(distance) { this.distance = Math.max(0, distance) }
  function finish() { active = false }
}

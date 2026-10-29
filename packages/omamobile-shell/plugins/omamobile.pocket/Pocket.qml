// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import ".." as Phone

Item {
  id: root
  property var shell: null
  property var manifest: null
  property double now: Date.now()
  Phone.PocketStatus { id: guard }
  function open(payloadJson) {}
  function close() {}
  function state() {
    return JSON.stringify({ active: guard.active, token: guard.value.token || "",
      screens: guard.active ? Quickshell.screens.map(s => s.name) : [] })
  }
  Timer { interval: 100; repeat: true; running: guard.active; onTriggered: root.now = Date.now() }
  Process { id: dismissProcess }
  Variants {
    model: Quickshell.screens
    delegate: PanelWindow {
      id: window
      required property var modelData
      screen: modelData
      visible: guard.active
      anchors { top: true; bottom: true; left: true; right: true }
      exclusionMode: ExclusionMode.Ignore
      WlrLayershell.namespace: "omamobile-pocket"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
      color: Commons.Color.background
      // The full surface consumes all touches outside the deliberate swipe.
      MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
      Column {
        width: Math.min(parent.width - 72, 380)
        anchors.centerIn: parent
        spacing: 24
        Text { width: parent.width; text: "Pocket protection"; color: Commons.Color.foreground; font.family: Style.font.family; font.pixelSize: 26; font.bold: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap }
        Text {
          width: parent.width
          text: guard.value.near === true ? "Pocket protection blocked this wake."
            : "Proximity unavailable. Wake protected."
          color: Commons.Color.foreground; opacity: 0.75; font.family: Style.font.family; font.pixelSize: 18; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
        }
        Text { width: parent.width; text: "If this was a mistake, swipe below."; color: Commons.Color.foreground; opacity: 0.75; font.family: Style.font.family; font.pixelSize: 16; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap }
        Rectangle {
          id: track
          width: parent.width; height: 72; radius: 0; color: "transparent"
          border.width: 2; border.color: Commons.Color.muted
          Text { anchors.centerIn: parent; text: "Swipe to continue   ›"; color: Commons.Color.foreground; font.family: Style.font.family; font.pixelSize: 16 }
          Rectangle { x: 8 + swipe.progress * (track.width - 72); y: 8; width: 56; height: 56; radius: 0; color: Commons.Color.accent; Text { anchors.centerIn: parent; text: "›"; color: Commons.Color.background; font.family: Style.font.family; font.pixelSize: 32 } }
          MouseArea {
            id: swipe
            anchors.fill: parent
            property real startX: 0
            property real startY: 0
            property double startTime: 0
            property bool eligible: false
            property real progress: 0
            onPressed: function(mouse) {
              startX = mouse.x; startY = mouse.y; startTime = Date.now()
              eligible = mouse.x < 80 && guard.value.phase === "blocked"
              progress = 0
            }
            onPositionChanged: function(mouse) {
              if (Math.abs(mouse.y - startY) > 45) eligible = false
              progress = eligible ? Math.max(0, Math.min(1, (mouse.x - startX) / (width - 80))) : 0
            }
            onReleased: function(mouse) {
              if (eligible && progress >= .85 && Date.now() - startTime >= 250 && !dismissProcess.running) {
                dismissProcess.command = ["omamobile-pocket", "dismiss", guard.value.token]
                dismissProcess.running = true
              }
              eligible = false; progress = 0
            }
            onCanceled: { eligible = false; progress = 0 }
          }
        }
        Text { width: parent.width; color: Commons.Color.muted; font.family: Style.font.family; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter
          text: guard.value.phase === "blocked" ? "Screen off in " + Math.max(0, Math.ceil((guard.value.deadline_wall * 1000 - root.now) / 1000)) + "s" : "Checking wake…" }
      }
    }
  }
}

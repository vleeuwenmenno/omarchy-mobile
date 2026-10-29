// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
QtObject {
  id: root
  property var value: ({ active: false })
  readonly property bool active: value.active === true
  property FileView source: FileView {
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/omamobile-pocket.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try { root.value = JSON.parse(text()) } catch (error) {}
    }
  }
}

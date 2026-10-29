// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import ".." as Phone
import "../omamobile.quicksettings" as QuickSettings
import "../omamobile.quicksettings/TilesModel.js" as TilesModel
import "../omamobile.rotation" as RotationUi
import "../omamobile.launcher/SettingsGeometry.js" as Geometry

// The phone's Settings app: a list of sections, each a page with a back
// button, drawn like the other sheets (a card over a scrim, Omarchy's square
// controls). Three sections: General, Keyboard and Quick Settings.
//
// Nothing here keeps its own copy of a setting. Values come from
// `omamobile-settings status` (GSettings for the keyboard, settings.json for
// the bottom gap) and are saved one key at a time with `omamobile-settings
// set`. The Quick Settings page reads the sheet's own layout file and hands
// editing back to the sheet.
//
// It never takes keyboard focus and is not drawn over the lock: it opens only
// on an unlocked screen and not from a pocket.
//
// `shell summon omamobile.settings '{"page":"keyboard"}'` opens a page
// ("general", "keyboard" or "quicksettings"); no page opens the list.
Item {
  id: root

  // Injected by the host.
  property var shell: null
  property var manifest: null

  property bool opened: false
  property string page: "root"
  property string pendingPage: "root"
  property var values: ({ keyboard: {}, available: {}, limits: {} })
  property var general: ({})
  property var layout: TilesModel.defaults()
  property string error: ""
  property bool confirmReset: false
  property var pendingWrite: null

  readonly property string pluginId: (manifest && manifest.id) || "omamobile.settings"
  readonly property color foreground: Commons.Color.popups.text
  readonly property var keyboard: values.keyboard || ({})
  readonly property var available: values.available || ({})
  readonly property var titles: ({ root: "Settings", general: "General", keyboard: "Keyboard", quicksettings: "Quick Settings" })
  readonly property var glyphs: ({
    back: String.fromCodePoint(0xF004D), close: String.fromCodePoint(0xF0156),
    general: String.fromCodePoint(0xF0493), keyboard: String.fromCodePoint(0xF030C),
    tiles: String.fromCodePoint(0xF056E), theme: String.fromCodePoint(0xF03D8),
    rotation: String.fromCodePoint(0xF0467), edit: String.fromCodePoint(0xF03EB),
    reset: String.fromCodePoint(0xF0450), auto: String.fromCodePoint(0xF030C)
  })

  Phone.PocketStatus { id: pocket }

  // ---------------------------------------------------------------- lifecycle

  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") || ({}) } catch (e) { payload = ({}) }
    pendingPage = ["general", "keyboard", "quicksettings"].indexOf(payload.page) >= 0 ? payload.page : "root"
    if (pocket.active) { hostHide(); return }
    if (!lockCheck.running) lockCheck.running = true
  }

  function close() { opened = false; confirmReset = false }

  function hostHide() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  function dismiss() { hostHide() }

  function back() {
    confirmReset = false
    if (page !== "root") page = "root"
    else dismiss()
  }

  function state() {
    return JSON.stringify({ opened: opened, page: page, keyboard: keyboard, available: available, tiles: layout.length })
  }

  // Never over a secure lock: ask the lock, and stay closed if it is up.
  Process {
    id: lockCheck
    command: ["sh", "-c", "omarchy-shell lock status 2>/dev/null | grep -q '\"secure\":true'"]
    onExited: function(code) {
      if (code === 0) { root.hostHide(); return }
      root.page = root.pendingPage
      root.error = ""
      root.opened = true
      root.refresh()
    }
  }

  // ---------------------------------------------------------------- values

  function refresh() {
    if (!statusRead.running) statusRead.running = true
    if (!generalRead.running) generalRead.running = true
  }

  Process {
    id: statusRead
    command: ["omamobile-settings", "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var value = JSON.parse(text)
          if (value && value.keyboard && !root.pendingWrite && !write.running) root.values = value
        } catch (e) { root.error = "Settings helper unavailable" }
      }
    }
  }

  Process {
    id: generalRead
    command: ["omamobile-settings", "general"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: { try { root.general = JSON.parse(text) } catch (e) { root.general = ({}) } }
    }
  }

  // One write at a time; a tap while one runs replaces any waiting one. The
  // value shows at once and the helper's answer settles it.
  function setValue(key, value) {
    var next = JSON.parse(JSON.stringify(values))
    next.keyboard = next.keyboard || ({})
    next.keyboard[key.split(".")[1]] = value
    values = next
    if (write.running) { pendingWrite = { key: key, value: value }; return }
    startWrite(key, value)
  }

  function startWrite(key, value) {
    error = ""
    write.command = ["omamobile-settings", "set", key, String(value)]
    write.running = true
  }

  Process {
    id: write
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var out = JSON.parse(text)
          if (out.error) root.error = out.error
          else if (out.keyboard && !root.pendingWrite) root.values = out
        } catch (e) { root.error = "Could not save the setting" }
      }
    }
    onExited: function(code) {
      if (code !== 0 && root.error === "") root.error = "Could not save the setting"
      if (root.pendingWrite) {
        var next = root.pendingWrite
        root.pendingWrite = null
        root.startWrite(next.key, next.value)
      } else if (code !== 0) {
        root.refresh()
      }
    }
  }

  // The Quick Settings sheet's own layout file: read only.
  FileView {
    path: Quickshell.env("HOME") + "/.config/omamobile/quicksettings.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.layout = TilesModel.parseConfig(text())
    onLoadFailed: root.layout = TilesModel.defaults()
  }

  // ---------------------------------------------------------------- actions

  // Through the CLI, like the sheet's other tiles: a plugin may only summon
  // panels it owns. This sheet closes first so the next one is not under it.
  function summon(plugin, payload) {
    dismiss()
    Quickshell.execDetached(["omarchy-shell", "shell", "summon", plugin, payload || "{}"])
  }

  function openThemePicker() {
    dismiss()
    Quickshell.execDetached(["omarchy-menu", "summon", "style.theme"])
  }

  function resetTiles() {
    if (!confirmReset) { confirmReset = true; confirmTimer.restart(); return }
    confirmReset = false
    Quickshell.execDetached(["omarchy-shell", "shell", "call", "omamobile.quicksettings", "resetTiles", ""])
  }
  Timer { id: confirmTimer; interval: 4000; onTriggered: root.confirmReset = false }

  // ---------------------------------------------------------------- window

  property real reveal: opened ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

  PanelWindow {
    id: panel
    visible: root.opened || root.reveal > 0
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Normal
    WlrLayershell.namespace: "omamobile-settings"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: "transparent"

    Rectangle {
      anchors.fill: parent
      color: Commons.Color.menu.scrim
      opacity: root.reveal
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      // Full width on a phone, a column in the middle of a wider screen.
      width: Math.min(parent.width - Style.gapsOut * 2, Style.space(560))
      height: Math.min(parent.height - Style.gapsOut * 2, Style.space(820))
      x: Math.round((parent.width - width) / 2)
      y: Math.round((parent.height - height) / 2) + Math.round((1 - root.reveal) * Style.space(60))
      opacity: root.reveal
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      padding: Style.spacing.panelPadding

      // Swallow taps so they don't reach the scrim.
      MouseArea { anchors.fill: parent }

      Item {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset

        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(44, Style.space(48))

          QuickSettings.GlyphButton {
            id: backButton
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            glyph: root.page === "root" ? root.glyphs.close : root.glyphs.back
            foreground: root.foreground
            onTapped: root.back()
          }

          Text {
            anchors.left: backButton.right
            anchors.leftMargin: Style.spacing.lg
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.titles[root.page] || "Settings"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }
        }

        Flickable {
          id: flick
          anchors.top: header.bottom
          anchors.topMargin: Style.spacing.lg
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          clip: true
          contentHeight: pages.item ? pages.item.implicitHeight : 0
          boundsBehavior: Flickable.StopAtBounds

          Loader {
            id: pages
            width: flick.width
            sourceComponent: root.page === "general" ? generalPage
              : root.page === "keyboard" ? keyboardPage
              : root.page === "quicksettings" ? quickSettingsPage : rootPage
            onLoaded: flick.contentY = 0
          }
        }
      }
    }
  }

  // ---------------------------------------------------------------- pages

  Component {
    id: rootPage
    Column {
      width: pages.width
      spacing: Style.spacing.md

      NavRow {
        foreground: root.foreground
        label: "General"
        detail: "Appearance, rotation, about"
        glyph: root.glyphs.general
        onTapped: root.page = "general"
      }
      NavRow {
        foreground: root.foreground
        label: "Keyboard"
        detail: root.available.size === true || root.available.auto_show === true
          ? (root.keyboard.auto_show === false ? "Opens from its tile" : "Opens when you type") : "Size and gesture gap"
        glyph: root.glyphs.keyboard
        onTapped: root.page = "keyboard"
      }
      NavRow {
        foreground: root.foreground
        label: "Quick Settings"
        detail: TilesModel.sanitize(root.layout).length + " tiles shown"
        glyph: root.glyphs.tiles
        onTapped: root.page = "quicksettings"
      }
    }
  }

  Component {
    id: generalPage
    Column {
      width: pages.width
      spacing: Style.spacing.md

      PanelSectionHeader { width: parent.width; text: "Appearance"; foreground: root.foreground }
      NavRow {
        foreground: root.foreground
        label: "Theme"
        detail: root.general.theme || ""
        glyph: root.glyphs.theme
        onTapped: root.openThemePicker()
      }

      PanelSectionHeader { width: parent.width; topPadding: Style.spacing.lg; text: "Display"; foreground: root.foreground }
      NavRow {
        foreground: root.foreground
        label: "Rotation"
        detail: "Auto-rotate and allowed orientations"
        glyph: root.glyphs.rotation
        onTapped: root.summon("omamobile.rotation", "{}")
      }

      PanelSectionHeader { width: parent.width; topPadding: Style.spacing.lg; text: "About"; foreground: root.foreground }
      InfoRow { foreground: root.foreground; label: "Omarchy"; value: root.general.omarchy || "" }
      InfoRow { foreground: root.foreground; label: "Phone shell"; value: root.general.shell || "" }
      InfoRow { foreground: root.foreground; label: "Kernel"; value: root.general.kernel || "" }
    }
  }

  Component {
    id: keyboardPage
    Column {
      width: pages.width
      spacing: Style.spacing.md

      PanelSectionHeader { width: parent.width; text: "Opening"; foreground: root.foreground }
      RotationUi.SwitchRow {
        foreground: root.foreground
        busy: false
        enabled: root.available.auto_show === true
        label: "Automatically show when typing"
        detail: "Off: open it from the Keyboard tile"
        glyph: root.glyphs.auto
        checked: root.keyboard.auto_show === true
        onTapped: root.setValue("keyboard.auto_show", !(root.keyboard.auto_show === true))
      }

      PanelSectionHeader { width: parent.width; topPadding: Style.spacing.lg; text: "Size"; foreground: root.foreground }
      StepperRow {
        foreground: root.foreground
        enabled: root.available.size === true
        label: "Portrait"
        detail: "Height when held upright"
        value: Geometry.formatScale(root.keyboard.portrait_scale)
        canDecrement: root.keyboard.portrait_scale > Geometry.SCALE_MIN
        canIncrement: root.keyboard.portrait_scale < Geometry.SCALE_MAX
        onDecrement: root.setValue("keyboard.portrait_scale", Geometry.stepScale(root.keyboard.portrait_scale, -1))
        onIncrement: root.setValue("keyboard.portrait_scale", Geometry.stepScale(root.keyboard.portrait_scale, 1))
      }
      StepperRow {
        foreground: root.foreground
        enabled: root.available.size === true
        label: "Landscape"
        detail: "Height when held sideways"
        value: Geometry.formatScale(root.keyboard.landscape_scale)
        canDecrement: root.keyboard.landscape_scale > Geometry.SCALE_MIN
        canIncrement: root.keyboard.landscape_scale < Geometry.SCALE_MAX
        onDecrement: root.setValue("keyboard.landscape_scale", Geometry.stepScale(root.keyboard.landscape_scale, -1))
        onIncrement: root.setValue("keyboard.landscape_scale", Geometry.stepScale(root.keyboard.landscape_scale, 1))
      }
      RotationUi.SwitchRow {
        foreground: root.foreground
        busy: false
        enabled: root.available.stretch === true
        label: "Stretch keys to fit"
        detail: "Fill the width of the screen"
        glyph: root.glyphs.keyboard
        checked: root.keyboard.stretch === true
        onTapped: root.setValue("keyboard.stretch", !(root.keyboard.stretch === true))
      }
      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: root.available.size === true
          ? "Size and stretch apply the next time the keyboard opens."
          : "The on-screen keyboard's settings are not installed on this system."
        color: Qt.darker(root.foreground, 1.4)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      PanelSectionHeader { width: parent.width; topPadding: Style.spacing.lg; text: "Gestures"; foreground: root.foreground }
      StepperRow {
        foreground: root.foreground
        label: "Bottom gap"
        detail: "Clearance under the keyboard for swipes"
        value: String(root.keyboard.bottom_gap === undefined ? Geometry.GAP_DEFAULT : root.keyboard.bottom_gap)
        canDecrement: root.keyboard.bottom_gap > Geometry.GAP_MIN
        canIncrement: root.keyboard.bottom_gap < Geometry.GAP_MAX
        onDecrement: root.setValue("keyboard.bottom_gap", Geometry.stepGap(root.keyboard.bottom_gap, -1))
        onIncrement: root.setValue("keyboard.bottom_gap", Geometry.stepGap(root.keyboard.bottom_gap, 1))
      }

      Text {
        width: parent.width
        visible: text.length > 0
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: root.error
        color: Commons.Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }
  }

  Component {
    id: quickSettingsPage
    Column {
      width: pages.width
      spacing: Style.spacing.md

      InfoRow {
        foreground: root.foreground
        label: "Tiles shown"
        value: TilesModel.sanitize(root.layout).length + " of " + TilesModel.CATALOG.length
      }
      NavRow {
        foreground: root.foreground
        label: "Edit tiles"
        detail: "Add, remove and move tiles"
        glyph: root.glyphs.edit
        onTapped: root.summon("omamobile.quicksettings", "{\"page\":\"edit\"}")
      }
      NavRow {
        foreground: root.foreground
        enabled: !TilesModel.isDefault(root.layout)
        label: root.confirmReset ? "Tap again to reset" : "Reset to default layout"
        detail: TilesModel.isDefault(root.layout) ? "Already the default" : "Replaces your tile arrangement"
        glyph: root.glyphs.reset
        chevron: false
        onTapped: root.resetTiles()
      }
    }
  }
}

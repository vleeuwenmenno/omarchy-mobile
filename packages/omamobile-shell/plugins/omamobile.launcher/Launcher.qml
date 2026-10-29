// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import qs.services as OmarchyServices
import ".." as Phone
import "../omamobile.gestures" as Gestures
import "DeviceProfile.js" as DeviceProfile
import "LauncherModel.js" as LauncherModel
import "SettingsGeometry.js" as SettingsGeometry

// The phone's home surface, after Omalauncher: one bar at the bottom of the
// screen that is app search, app grid and coding-agent prompt at once.
//
// Collapsed, it is a dock holding a single search pill. Tapping it raises the
// app drawer with the input focused. Typing filters the grid; text that reads
// like a sentence (or matches no app) offers "Ask <agent>" (the user's
// Omarchy default agent) instead, and Enter
// takes whichever is on top: the first app, or a terminal running the agent
// with the text as its first prompt.
//
// Apps come from Omarchy's application library (services/AppLibrary.qml: the
// same entries, hidden-entry filters, icons and launch path as the Omarchy
// menu). The host shares its instance with `menu` plugins; see the Loader
// below for why this one is a `panel` that runs its own for now.
Item {
  id: root

  // Injected by the host.
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property string deviceDescriptor: ""
  readonly property var deviceProfile: DeviceProfile.profile(deviceDescriptor)
  readonly property int sideInset: Style.space(deviceProfile.sideInset)

  FileView {
    path: DeviceProfile.DESCRIPTOR_PATH
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.deviceDescriptor = text()
    onLoadFailed: root.deviceDescriptor = ""
  }

  // Pocket protection: the bottom-edge gestures stand down while it is up.
  Phone.PocketStatus { id: pocketGuard }

  readonly property string pluginId: (manifest && manifest.id) || "omamobile.launcher"
  readonly property var appLibrary: shell && shell.appLibrary ? shell.appLibrary : localLibrary.item

  // The host hands its application library only to `menu` plugins, and in
  // this Omarchy build a third-party menu loses its whole shell facade on the
  // next config change (phone/plugins/README.md has the details). So the
  // launcher declares `panel` and runs Omarchy's own AppLibrary type here: the
  // same entries, hidden-entry filters, icon index and launch path, in a
  // second instance. If the host ever provides one, that wins.
  Loader {
    id: localLibrary
    active: !!root.shell && !root.shell.appLibrary
    sourceComponent: Component { OmarchyServices.AppLibrary { } }
  }

  // `opened` is the drawer; the dock is always on screen.
  property bool opened: false
  // Home is an empty workspace; an app keeps only the system gesture strip.
  readonly property bool homeVisible: !!Hyprland.focusedWorkspace
    && Hyprland.focusedWorkspace.toplevels.values.length === 0
  // The strip kept under the drawer and the on-screen keyboard for the bottom
  // gestures: Settings > Keyboard > Bottom gap (24 by default, which is what
  // it always was). Read-only here; bin/omamobile-settings writes the file.
  property var geometry: SettingsGeometry.parse("")
  readonly property int navigationHeight: Style.space(SettingsGeometry.bottomGap(geometry))
  FileView {
    path: Quickshell.env("HOME") + "/.config/omamobile/settings.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.geometry = SettingsGeometry.parse(text())
    onLoadFailed: root.geometry = SettingsGeometry.parse("")
  }
  property string query: ""
  property var apps: []
  property int appsRevision: 0

  // ---------------------------------------------------------------- settings

  property var shellConfig: ({})
  readonly property var settings: LauncherModel.mergedSettings(
    manifest && manifest.settings ? manifest.settings.defaults : ({}), shellConfig, pluginId)

  // The coding agent is the user's choice, made the Omarchy way:
  // omarchy-default-agent stores it in ~/.config/omarchy/defaults/agent and
  // leaves it unset until the user picks one. Read it live so a choice made
  // in Omarchy's menu shows up here at once.
  property string agentId: ""
  readonly property string agentName: LauncherModel.agentName(agentId)
  readonly property bool hasAgent: agentId.length > 0
  readonly property string agentIcon: hasAgent
    ? Util.fileUrl(omarchyPath + "/shell/plugins/agents/assets/" + agentId + ".svg") : ""

  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/defaults/agent"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.agentId = LauncherModel.agentId(text())
    onLoadFailed: root.agentId = ""
  }

  readonly property int columns: Math.max(3, Math.min(6, Number(settings.columns) || 4))
  readonly property int sentenceWords: Math.max(2, Number(settings.sentenceWords) || 3)

  // Plugin entries in shell.json carry their settings inline, but the host
  // only hands those to bar widgets, so read our own entry from the file.
  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.shellConfig = JSON.parse(text() || "{}") } catch (e) { root.shellConfig = ({}) }
    }
  }

  // ---------------------------------------------------------------- results

  readonly property bool promptMode: LauncherModel.looksLikePrompt(query, apps.length, sentenceWords)
  readonly property bool hasQuery: query.trim().length > 0

  function refreshApps() {
    // sortedEntries() yields ranked rows of { entry, score, ... }; the grid
    // wants the DesktopEntry objects themselves.
    var rows = appLibrary ? appLibrary.sortedEntries(query) : []
    var entries = []
    for (var i = 0; i < rows.length; i++)
      if (rows[i] && rows[i].entry) entries.push(rows[i].entry)
    apps = entries
  }

  onQueryChanged: refreshApps()
  onAppLibraryChanged: refreshApps()

  Connections {
    target: root.appLibrary
    ignoreUnknownSignals: true
    function onAppsChanged() { root.refreshApps() }
  }

  // ---------------------------------------------------------------- actions

  // Not AppLibrary.launch: omamobile-launch starts the app the same way
  // (uwsm-app -- gtk-launch) on a new empty workspace, or focuses it on its
  // own if it is already open. Omarchy's "Launching…" feedback stays.
  function launchApp(entry) {
    if (!entry || !entry.id) return
    if (appLibrary && typeof appLibrary.beginLaunchFeedback === "function")
      appLibrary.beginLaunchFeedback(appLibrary.entryName(entry))
    Quickshell.execDetached(LauncherModel.appArgv(entry.id))
    dismiss()
  }

  // Long-press in the drawer: put the app on the home screen
  // (omamobile.home), on the page it shows, and go there, as on Android.
  // Through IPC, like the switcher: a plugin only summons its own panels.
  function addToHome(entry) {
    if (!entry) return
    Quickshell.execDetached(["qs", "ipc", "-p", Quickshell.shellDir, "call", "shell", "call",
                             "omamobile.home", "addApp", String(entry.id)])
    dismiss()
  }

  function askAgent(prompt) {
    var text = String(prompt || "").trim()
    if (!text) return "empty"
    if (!hasAgent) {
      Util.execArgv(LauncherModel.PICK_AGENT_ARGV)
      dismiss()
      return "pick-agent"
    }
    Util.execArgv(LauncherModel.promptArgv(text))
    dismiss()
    return "ok"
  }

  // Enter: the agent when the text reads as a prompt, else the top app.
  function activate() {
    if (!hasQuery) return
    if (promptMode || apps.length === 0) askAgent(query)
    else launchApp(apps[0])
  }

  // ---------------------------------------------------------------- lifecycle

  // `shell summon omamobile.launcher '{"query":"..."}'` opens the
  // drawer, optionally pre-filled.
  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }
    query = typeof payload.query === "string" ? payload.query : ""
    if (appLibrary) appLibrary.refreshIcons()
    refreshApps()
    opened = true
  }

  // ---------------------------------------------------------------- focus

  // A drawer summoned over IPC (or by a swipe) is mapped without any touch
  // on it, and Hyprland gives such a layer no keyboard focus, so the input
  // never gets one and squeekboard stays hidden. Hand the focus over on
  // purpose: a HyprlandFocusGrab on the drawer for a moment, then drop the
  // grab (it would swallow the keyboard's touches, like Exclusive focus) and
  // show the keyboard. Only for a committed open, never for a drag preview.
  property bool keyboardShown: false

  function setKeyboard(show) {
    Quickshell.execDetached(["busctl", "--user", "call", "sm.puri.OSK0", "/sm/puri/OSK0",
                             "sm.puri.OSK0", "SetVisible", "b", show ? "true" : "false"])
    keyboardShown = show
  }

  function cancelFocus() {
    focusStart.stop()
    focusEnd.stop()
    focusGrab.active = false
    if (keyboardShown) setKeyboard(false)
  }

  onOpenedChanged: {
    if (opened) focusStart.restart()
    else cancelFocus()
  }

  Timer {
    id: focusStart
    interval: 120
    onTriggered: {
      if (!root.opened) return
      focusGrab.active = true
      input.forceActiveFocus()
      focusEnd.restart()
    }
  }

  Timer {
    id: focusEnd
    interval: 450
    onTriggered: {
      focusGrab.active = false
      if (!root.opened) return
      input.forceActiveFocus()
      root.setKeyboard(true)
    }
  }

  HyprlandFocusGrab {
    id: focusGrab
    windows: [drawer]
  }

  // Host-initiated close (`shell hide`).
  function close() {
    opened = false
    query = ""
  }

  function dismiss() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  function expand() {
    if (shell && typeof shell.summon === "function") shell.summon(pluginId, "{}")
    else open("{}")
  }

  // `shell call omamobile.launcher <method> <arg>` entry points.
  function search(text) {
    if (!opened) expand()
    query = String(text || "")
    return JSON.stringify({ mode: promptMode ? "agent" : "apps", apps: apps.slice(0, 8).map(function(e) { return e.id }) })
  }

  function ask(prompt) { return askAgent(prompt) }

  function state() {
    return JSON.stringify({
      opened: opened,
      query: query,
      mode: hasQuery ? (promptMode ? "agent" : "apps") : "idle",
      apps: apps.length,
      library: shell && shell.appLibrary ? "host" : (appLibrary ? "local" : "none"),
      agent: agentId,
      command: hasAgent ? LauncherModel.promptArgv("<prompt>") : LauncherModel.PICK_AGENT_ARGV
    })
  }

  // Anything that opens a window (an app, the screensaver) closes the drawer,
  // as on Android: left open, it stays on top and keeps the keyboard focus.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (root.opened && event && event.name === "openwindow") root.dismiss()
    }
  }

  // ---------------------------------------------------------------- geometry

  readonly property color foreground: Commons.Color.menu.text
  readonly property int touch: Math.max(44, Style.space(44))
  readonly property int inputHeight: Math.max(48, Style.space(48))
  readonly property int dockHeight: inputHeight + Style.spacing.xxl * 2
  // Same side padding as the status bar, so the search bar lines up with the
  // rounded corners.
  readonly property int searchInset: Style.spacing.huge + sideInset
  // The strip above the dock's search pill that holds the drag handle.
  readonly property int handleHeight: Math.max(22, Style.space(22))
  readonly property int dockBottomInset: Style.space(8)

  // Dragging the dock handle up: the drawer follows the finger before it is
  // opened. `previewing` keeps it mapped and fully shown meanwhile.
  property bool previewing: false
  property real handleVelocity: 0
  readonly property real screenHeight: drawer.screen ? drawer.screen.height : Math.max(drawerSheetHeight, 1)

  function previewMove(up, velocity) {
    if (opened) return
    if (!previewing) {
      previewing = true
      pullSettle = false
      previewEnd.stop()
    }
    handleVelocity = velocity
    var h = Math.max(drawerSheetHeight, screenHeight)
    dragY = Math.max(0, h - Math.max(0, up))
  }

  function previewRelease() {
    if (!previewing) return
    var h = Math.max(drawerSheetHeight, screenHeight)
    var up = h - dragY
    pullSettle = true
    if (up > h * 0.25 || (handleVelocity < -1.0 && up > Style.space(24))) {
      dragY = 0
      expand()
    } else {
      dragY = h
    }
    previewEnd.restart()
  }

  // Settles the preview once the open has landed or the cancel slide is done.
  Timer {
    id: previewEnd
    interval: 260
    onTriggered: {
      root.previewing = false
      if (!root.opened) {
        root.pullSettle = false
        root.dragY = 0
        root.pullSettle = true
      }
    }
  }

  property real reveal: (opened || previewing) ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

  // Pull the open drawer down to close it, as QuickSettings is pushed up: the
  // sheet follows the finger and, on release, settles back or slides off.
  // `dragY` is how far down the finger has pulled it.
  property real dragY: 0
  property bool pullSettle: true
  property bool pullMoved: false
  Behavior on dragY { enabled: root.pullSettle; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
  // A pull that ends over an app cell must not also count as a tap on it.
  Timer { id: pullGuard; interval: 150; onTriggered: root.pullMoved = false }

  function pullRelease(velocity) {
    var past = dragY > Style.space(120) || (velocity > 1.0 && dragY > Style.space(24))
    pullSettle = true
    pullGuard.restart()
    if (past) {
      dragY = drawerSheetHeight
      dismiss()
    } else {
      dragY = 0
    }
  }
  property real drawerSheetHeight: 0

  // ---------------------------------------------------------------- dock

  Variants {
    model: Quickshell.screens

    PanelWindow {
      required property var modelData
      screen: modelData

      // Keep the navigation strip reserved while typing so the keyboard
      // sits above it; only Home shows the search pill and drawer handle.
      visible: true
      anchors { bottom: true; left: true; right: true }
      implicitHeight: (root.homeVisible && !root.opened) ? root.dockHeight + root.handleHeight + root.dockBottomInset : root.navigationHeight
      exclusionMode: ExclusionMode.Auto
      color: Commons.Color.bar.background
      WlrLayershell.namespace: "omamobile-dock"
      // Bottom, not Top: its exclusive zone still keeps windows off it, and
      // fullscreen windows (the screensaver, video) cover it. On Top it was
      // drawn over a fullscreen window when it re-mapped after the drawer.
      WlrLayershell.layer: WlrLayer.Bottom

      // System gestures along the bottom edge (omamobile.switcher), as on
      // Android: up for recent apps, sideways to switch apps, hold for home.
      // A tap on the pill still opens the drawer. The strip covers only the
      // margin under the pill, so the drawer handle above has its own drag.
      Item {
        anchors.fill: parent

        // The handle: drag up and the drawer follows the finger; on release it
        // settles open (keyboard follows) or back.
        Item {
          id: handleZone
          visible: root.homeVisible && !root.opened
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.handleHeight + Style.spacing.xxl

          Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: Style.spacing.md
            width: Math.max(36, Style.space(40))
            height: Math.max(4, Style.space(4))
            radius: height / 2
            color: Qt.darker(root.foreground, 1.6)
          }

          DragHandler {
            target: null
            xAxis.enabled: false
            property real lastY: 0
            property real lastT: 0
            property real velocity: 0
            onActiveChanged: {
              if (active) { lastY = 0; lastT = Date.now(); velocity = 0 }
              else root.previewRelease()
            }
            onActiveTranslationChanged: {
              if (!active) return
              var y = activeTranslation.y
              var now = Date.now()
              if (now > lastT) velocity = 0.6 * velocity + 0.4 * ((y - lastY) / (now - lastT))
              lastY = y; lastT = now
              root.previewMove(-y, velocity)
            }
          }
        }

        // The system navigation strip along the bottom edge. The finger goes
        // to Gestures.NavState, where the switcher follows it: sideways
        // switches apps, up opens recents, a hold goes home. A small handle
        // shows while it is touched and fades a moment later; the strip
        // itself always takes gestures.
        Item {
          id: recentsStrip
          anchors.bottom: parent.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.navigationHeight
          enabled: !pocketGuard.active

          property bool handleShown: false
          readonly property bool touched: navDrag.active || navTap.pressed

          onTouchedChanged: {
            if (touched) {
              handleHide.stop()
              handleShown = true
            } else {
              handleHide.restart()
            }
          }

          Timer {
            id: handleHide
            interval: 1600
            onTriggered: recentsStrip.handleShown = false
          }

          Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            // Leans after the finger, like the handle on Android and iOS.
            anchors.horizontalCenterOffset: navDrag.active
              ? Math.max(-Style.space(40), Math.min(Style.space(40), Gestures.NavState.dx * 0.2)) : 0
            anchors.verticalCenterOffset: navDrag.active
              ? Math.max(-Style.space(10), Math.min(0, Gestures.NavState.dy * 0.08)) : 0
            width: Math.max(72, Style.space(96))
            height: Math.max(4, Style.space(5))
            radius: height / 2
            color: root.foreground
            opacity: recentsStrip.handleShown ? 0.75 : 0
            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            Behavior on anchors.horizontalCenterOffset { enabled: !navDrag.active; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Behavior on anchors.verticalCenterOffset { enabled: !navDrag.active; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
          }

          TapHandler {
            id: navTap
            gesturePolicy: TapHandler.DragThreshold
            longPressThreshold: 0.45
            onPressedChanged: {
              if (pressed) Gestures.NavState.press()
              else Gestures.NavState.release()
            }
            onLongPressed: {
              if (Gestures.NavState.attached) Gestures.NavState.hold()
            }
          }

          DragHandler {
            id: navDrag
            target: null
            property bool canceled: false
            onActiveChanged: {
              if (active) {
                canceled = false
                Gestures.NavState.begin()
                return
              }
              // Later, so a cancel (lost grab) has been seen whichever order
              // Qt reports it in.
              Qt.callLater(function() {
                var dy = Gestures.NavState.dy
                var lost = navDrag.canceled || pocketGuard.active
                Gestures.NavState.finish(lost)
                // No switcher listening: the plain swipe up for recents.
                // Through the CLI, like Omarchy's background does: a plugin
                // may only summon panels it owns, and the switcher is its own.
                if (!Gestures.NavState.attached && !lost && dy < -24)
                  Quickshell.execDetached(["omarchy-shell", "shell", "summon", "omamobile.switcher", "{}"])
              })
            }
            onCanceled: canceled = true
            onActiveTranslationChanged: {
              if (!active) return
              var velocity = centroid.velocity
              Gestures.NavState.update(activeTranslation.x, activeTranslation.y,
                                       velocity.x / 1000, velocity.y / 1000)
            }
          }
        }

        SearchPill {
          visible: root.homeVisible && !root.opened
          anchors.fill: parent
          anchors.topMargin: root.handleHeight + Style.spacing.xxl
          anchors.bottomMargin: Style.spacing.xxl + root.dockBottomInset
          anchors.leftMargin: root.searchInset
          anchors.rightMargin: root.searchInset
          placeholder: (root.hasAgent ? "Search apps or ask " + root.agentName + "…" : "Search apps…")
          onTapped: root.expand()
        }
      }
    }
  }

  // ---------------------------------------------------------------- drawer

  PanelWindow {
    id: drawer

    visible: root.opened || root.reveal > 0 || root.previewing
    anchors { top: true; bottom: true; left: true; right: true }
    // Normal: fit between the bar and the on-screen keyboard, like Android's
    // adjustResize.
    exclusionMode: ExclusionMode.Normal
    color: "transparent"
    WlrLayershell.namespace: "omamobile-launcher"
    WlrLayershell.layer: WlrLayer.Top
    // OnDemand, not Exclusive: Hyprland sends no touch to other layers while
    // one holds exclusive focus, and that includes the on-screen keyboard.
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    onVisibleChanged: {
      if (visible) {
        if (root.opened) Qt.callLater(function() { input.forceActiveFocus() })
      } else {
        root.pullSettle = false
        root.dragY = 0
        root.pullSettle = true
      }
    }

    Rectangle {
      id: sheet
      width: parent.width
      height: parent.height
      y: Math.round((1 - root.reveal) * Style.space(80)) + root.dragY
      opacity: root.reveal * (1 - Math.min(1, root.dragY / Math.max(1, height)) * 0.6)
      color: Commons.Color.menu.background
      onHeightChanged: root.drawerSheetHeight = height

      // Pull down from the header, or from the grid while it is scrolled to
      // its top, to close. A passive PointHandler: it takes no grab, so the
      // grid still scrolls and the cells still get their taps; at the top a
      // downward drag cannot scroll the grid anyway, so it is free to move
      // the sheet instead.
      PointHandler {
        id: pull
        property real minY: 0
        property real lastY: 0
        property real lastT: 0
        property real velocity: 0
        property bool pulling: false
        readonly property bool inGrid: point.position.y >= grid.y && point.position.y <= grid.y + grid.height
        readonly property bool inDragZone: point.position.y <= grid.y + grid.height
        readonly property bool atTop: !inGrid || (root.hasQuery ? grid.atYEnd : grid.atYBeginning)

        onActiveChanged: {
          if (active) {
            minY = point.scenePosition.y
            lastY = minY; lastT = Date.now(); velocity = 0
            pulling = false
          } else if (pulling) {
            pulling = false
            root.pullRelease(velocity)
          }
        }
        onPointChanged: {
          if (!active) return
          var y = point.scenePosition.y
          var x = point.scenePosition.x - point.scenePressPosition.x
          var now = Date.now()
          if (now > lastT) velocity = 0.6 * velocity + 0.4 * ((y - lastY) / (now - lastT))
          lastY = y; lastT = now
          if (!inDragZone && !pulling) return
          // Moving up, or off the top of the grid, restarts the pull.
          if (!atTop && !pulling) { minY = y; return }
          if (y < minY) minY = y
          var dy = y - minY
          if (!pulling) {
            if (dy < Style.space(10) || dy < Math.abs(x) * 1.5) return
            pulling = true
            root.pullMoved = true
            pullGuard.stop()
            root.pullSettle = false
          }
          root.dragY = Math.max(0, dy - Style.space(10))
        }
      }

      // ---------- Header: count and a collapse control
      Item {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Style.spacing.panelPadding
        anchors.rightMargin: Style.spacing.sm
        height: root.touch + Style.spacing.sm

        Text {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: root.hasQuery ? (root.apps.length === 1 ? "1 app" : root.apps.length + " apps") : "Apps"
          color: Qt.darker(root.foreground, 1.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }

        Button {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: root.touch
          height: root.touch
          iconText: "󰅀"
          iconSize: Style.font.iconLarge
          foreground: root.foreground
          onClicked: root.dismiss()
        }
      }

      // ---------- App grid
      GridView {
        id: grid
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: askRow.visible ? askRow.top : inputRow.top
        anchors.leftMargin: Style.spacing.lg
        anchors.rightMargin: Style.spacing.lg
        anchors.bottomMargin: Style.spacing.lg
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        // While searching, results stack up from the input so the best match
        // sits nearest the thumb; the full list reads top-down.
        verticalLayoutDirection: root.hasQuery ? GridView.BottomToTop : GridView.TopToBottom
        cellWidth: Math.floor(width / root.columns)
        cellHeight: Math.max(96, Style.space(100))
        model: root.apps
        opacity: root.promptMode ? 0.5 : 1

        delegate: AppCell {
          required property var modelData
          required property int index
          width: grid.cellWidth
          height: grid.cellHeight
          entry: modelData
          highlighted: index === 0 && root.hasQuery && !root.promptMode
          onTapped: if (!root.pullMoved) root.launchApp(modelData)
          onHeld: if (!root.pullMoved) root.addToHome(modelData)
        }
      }

      Text {
        anchors.centerIn: grid
        visible: root.hasQuery && root.apps.length === 0
        textFormat: Text.PlainText
        text: "No apps match"
        color: Qt.darker(root.foreground, 1.6)
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      // ---------- Ask the agent
      BorderSurface {
        id: askRow
        visible: root.hasQuery
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: inputRow.top
        anchors.leftMargin: root.searchInset
        anchors.rightMargin: root.searchInset
        anchors.bottomMargin: Style.spacing.lg
        height: Math.max(root.touch, Style.space(52))
        radius: Style.cornerRadius
        color: askTouch.pressed ? Style.pressedFillFor(root.foreground, Commons.Color.accent)
          : root.promptMode ? Commons.Color.menu.selectedBackground : "transparent"
        borderSpec: root.promptMode
          ? Border.flat(Commons.Color.accent, Math.max(1, Style.normalBorderWidth))
          : Border.controlSpec("normal", root.foreground, Commons.Color.accent)

        Item {
          id: askIcon
          anchors.left: parent.left
          anchors.leftMargin: Style.spacing.xl
          anchors.verticalCenter: parent.verticalCenter
          width: Style.font.display
          height: Style.font.display

          Image {
            id: askImage
            anchors.fill: parent
            source: root.agentIcon
            visible: status === Image.Ready
            fillMode: Image.PreserveAspectFit
            sourceSize.width: width * Screen.devicePixelRatio
            sourceSize.height: height * Screen.devicePixelRatio
          }

          Text {
            anchors.centerIn: parent
            visible: askImage.status !== Image.Ready
            textFormat: Text.PlainText
            text: "󰚩"
            color: Commons.Color.accent
            font.family: Style.font.family
            font.pixelSize: Style.font.display
          }
        }

        Column {
          anchors.left: askIcon.right
          anchors.leftMargin: Style.spacing.xl
          anchors.right: askEnter.left
          anchors.rightMargin: Style.spacing.lg
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.spacing.xxs

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.hasAgent ? "Ask " + root.agentName : "Choose your agent"
            color: root.promptMode ? Commons.Color.menu.selectedText : root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.query.trim()
            color: Qt.darker(root.foreground, 1.4)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }

        Text {
          id: askEnter
          anchors.right: parent.right
          anchors.rightMargin: Style.spacing.xl
          anchors.verticalCenter: parent.verticalCenter
          visible: root.promptMode
          textFormat: Text.PlainText
          text: "󰌑"
          color: Commons.Color.menu.selectedText
          font.family: Style.font.family
          font.pixelSize: Style.font.iconLarge
        }

        MouseArea {
          id: askTouch
          anchors.fill: parent
          onClicked: root.askAgent(root.query)
        }
      }

      // ---------- The one input
      Item {
        id: inputRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.dockHeight

        TextField {
          id: input
          anchors.fill: parent
          anchors.topMargin: Style.spacing.xxl
          anchors.bottomMargin: Style.spacing.xxl + root.dockBottomInset
          anchors.leftMargin: root.searchInset
          anchors.rightMargin: root.searchInset
          verticalAlignment: TextInput.AlignVCenter
          font.pixelSize: Style.font.title
          leftPadding: Style.spacing.controlPaddingX + Style.font.iconLarge + Style.spacing.xl
          placeholderText: (root.hasAgent ? "Search apps or ask " + root.agentName + "…" : "Search apps…")
          foreground: root.foreground
          text: root.query
          onTextEdited: root.query = text
          Keys.onReturnPressed: root.activate()
          Keys.onEnterPressed: root.activate()
          Keys.onEscapePressed: {
            if (root.query) root.query = ""
            else root.dismiss()
          }

          Text {
            anchors.left: parent.left
            anchors.leftMargin: Style.spacing.controlPaddingX + Border.left(input._borderSpec)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.promptMode ? "󰚩" : "󰍉"
            color: root.promptMode ? Commons.Color.accent : Qt.darker(root.foreground, 1.3)
            font.family: Style.font.family
            font.pixelSize: Style.font.iconLarge
          }
        }
      }
    }
  }

  // ---------------------------------------------------------------- parts

  // The collapsed bar: looks like the input it turns into.
  component SearchPill: BorderSurface {
    id: pill

    property string placeholder: ""
    signal tapped()

    radius: Style.cornerRadius
    color: pillTouch.pressed ? Style.pressedFillFor(root.foreground, Commons.Color.accent) : Style.normalFill
    borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)

    Text {
      id: pillIcon
      anchors.left: parent.left
      anchors.leftMargin: Style.spacing.controlPaddingX + pill.borderLeft
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: "󰍉"
      color: Qt.darker(root.foreground, 1.3)
      font.family: Style.font.family
      font.pixelSize: Style.font.iconLarge
    }

    Text {
      anchors.left: pillIcon.right
      anchors.leftMargin: Style.spacing.xl
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.controlPaddingX
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: pill.placeholder
      color: Qt.darker(root.foreground, 1.6)
      font.family: Style.font.family
      font.pixelSize: Style.font.title
      elide: Text.ElideRight
    }

    // A TapHandler, not a MouseArea: it lets go once the touch turns into a
    // drag, so the dock's swipe-up (recent apps) still sees it.
    TapHandler {
      id: pillTouch
      onTapped: pill.tapped()
    }
  }

  // One app in the grid: icon over a two-line name.
  component AppCell: Item {
    id: cell

    property var entry: null
    property bool highlighted: false
    signal tapped()
    signal held()

    BorderSurface {
      anchors.fill: parent
      anchors.margins: Style.spacing.xs
      radius: Style.cornerRadius
      color: cellTouch.pressed ? Style.pressedFillFor(root.foreground, Commons.Color.accent)
        : cell.highlighted ? Commons.Color.menu.selectedBackground : "transparent"
      borderSpec: cell.highlighted ? Border.flat(Commons.Color.accent, Math.max(1, Style.normalBorderWidth)) : Border.none()
    }

    Image {
      id: icon
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: parent.top
      anchors.topMargin: Style.spacing.xl
      width: Math.max(40, Style.space(44))
      height: width
      fillMode: Image.PreserveAspectFit
      asynchronous: true
      // Decode at physical pixels so PNG icons stay sharp at scale 3.
      sourceSize.width: width * Screen.devicePixelRatio
      sourceSize.height: height * Screen.devicePixelRatio
      source: root.appLibrary && cell.entry ? root.appLibrary.iconSource(cell.entry.icon) : ""
    }

    Text {
      anchors.top: icon.bottom
      anchors.topMargin: Style.spacing.md
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.leftMargin: Style.spacing.sm
      anchors.rightMargin: Style.spacing.sm
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: root.appLibrary && cell.entry ? root.appLibrary.entryName(cell.entry) : ""
      color: cell.highlighted ? Commons.Color.menu.selectedText : root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.Wrap
      maximumLineCount: 2
      elide: Text.ElideRight
    }

    MouseArea {
      id: cellTouch
      anchors.fill: parent
      onClicked: cell.tapped()
      onPressAndHold: cell.held()
    }
  }
}

// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import ".." as Phone
import "../omamobile.gestures" as Gestures
import "../omamobile.gestures/NavGesture.js" as NavGesture
import "../omamobile.launcher/SettingsGeometry.js" as SettingsGeometry

// Recent apps, after Android: every open window as a card with a live
// preview. Swipe sideways through them, tap one to switch to it, flick it up
// to close it. Home shows the home screen (an empty workspace) and leaves the
// apps open. Recents are never an empty dead end: with no app open (summoned
// over IPC, or after the last one closed) they go home instead.
//
// The dock's bottom-edge strip drives the system gestures through
// Gestures.NavState, drawn here on a click-through layer, after iOS: swipe
// sideways and the app on screen slides away as the next one follows the
// finger; swipe up and it shrinks with the finger, and letting go goes home;
// swipe up and pause and recents arm (the cards spread out, one tick of
// feedback), and letting go keeps them (NavGesture.js decides); hold still
// and the home screen comes up. While recents cover the dock, their own
// bottom strip takes the swipe home.
//
// Every app has a screen (workspace) of its own (omamobile-launch). Hold a
// card for the two ways to change that: "Show with…" puts the app on another
// app's screen, where the two tile as Omarchy tiles them, and "Move to its
// own screen" gives it one back.
//
// Windows come from the Wayland foreign-toplevel list, which gives each one
// activate() and close(). Home and the hold actions need Hyprland: the
// actions find a window's Hyprland address and workspace through
// Quickshell.Hyprland and run omamobile-launch with them.
Item {
  id: root

  // Injected by the host.
  property var shell: null
  property var manifest: null

  readonly property string pluginId: (manifest && manifest.id) || "omamobile.switcher"

  property bool opened: false

  // Newest first, like Android's recents.
  readonly property var windows: {
    var list = ToplevelManager.toplevels.values.slice()
    list.reverse()
    return list
  }

  // Host lifecycle (`shell summon` / `shell hide`).
  function open(payloadJson) {
    opened = true
    navLastOpen = { at: Date.now(), windows: windows.length, emptyGoesHome: windows.length === 0 }
    if (windows.length === 0) Qt.callLater(goHome)
  }
  function close() {
    opened = false
    closeActions()
  }

  function dismiss() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  function switchTo(toplevel) {
    if (toplevel) toplevel.activate()
    dismiss()
  }

  // Home with nothing over it: an empty workspace (never an app's), unless
  // one is already in front; the home screens (omamobile.home) back on their
  // home page; the app drawer and the on-screen keyboard closed through their
  // own routes, as swiping home from an open drawer must.
  function goHome() {
    navLastHome = { at: Date.now(), opened: opened, windows: windows.length, gesture: navTrace.seq || 0 }
    var ws = Hyprland.focusedWorkspace
    if (!ws || ws.toplevels.values.length > 0)
      Quickshell.execDetached(["hyprctl", "dispatch", "hl.dsp.focus({ workspace = \"empty\" })"])
    Quickshell.execDetached(["qs", "ipc", "-p", Quickshell.shellDir, "call", "shell", "call", "omamobile.home", "goHome", ""])
    Quickshell.execDetached(["omarchy-shell", "shell", "hide", "omamobile.launcher"])
    Quickshell.execDetached(["busctl", "--user", "call", "sm.puri.OSK0", "/sm/puri/OSK0",
                             "sm.puri.OSK0", "SetVisible", "b", "false"])
    dismiss()
  }

  // The last app closed (a flick, Clear all, or on its own) while recents
  // were up: nothing is left to pick, so home.
  onWindowsChanged: if (opened && windows.length === 0) Qt.callLater(goHome)

  function closeAll() {
    var list = ToplevelManager.toplevels.values.slice()
    for (var i = 0; i < list.length; i++) list[i].close()
  }

  // ---------------------------------------------------------------- hold actions

  // The window whose actions are open, and which page: "menu" or "pick"
  // (the apps it can share a screen with).
  property var actionTarget: null
  property string actionPage: "menu"
  readonly property bool actionsOpen: actionTarget !== null && windows.indexOf(actionTarget) >= 0

  // Hyprland's view of a Wayland toplevel: its address and workspace. By the
  // toplevel mapping when Hyprland offers it, else by class and title.
  function hyprlandFor(toplevel) {
    if (!toplevel) return null
    var list = Hyprland.toplevels.values
    var fallback = null
    for (var i = 0; i < list.length; i++) {
      const candidate = list[i]
      if (candidate.wayland === toplevel) return candidate
      const ipc = candidate.lastIpcObject || ({})
      if (!fallback && candidate.title === toplevel.title && ipc["class"] === toplevel.appId) fallback = candidate
    }
    return fallback
  }

  function addressOf(toplevel) {
    var hypr = hyprlandFor(toplevel)
    return hypr && hypr.address ? String(hypr.address) : ""
  }

  function workspaceOf(toplevel) {
    var hypr = hyprlandFor(toplevel)
    return hypr && hypr.workspace ? hypr.workspace.id : null
  }

  // Other open windows on the same screen.
  function screenMates(toplevel) {
    var ws = workspaceOf(toplevel)
    if (ws === null || ws === undefined) return []
    return windows.filter(function(other) { return other !== toplevel && workspaceOf(other) === ws })
  }

  // Windows on other screens, which this one can join.
  function partners(toplevel) {
    var ws = workspaceOf(toplevel)
    return windows.filter(function(other) {
      return other !== toplevel && (ws === null || ws === undefined || workspaceOf(other) !== ws)
    })
  }

  function openActions(toplevel) {
    if (!toplevel) return
    Hyprland.refreshToplevels()
    actionPage = "menu"
    actionTarget = toplevel
  }

  function closeActions() {
    actionTarget = null
    actionPage = "menu"
  }

  // This window onto other's screen: omamobile-launch moves it there by
  // address and tiles the two.
  function showWith(toplevel, other) {
    var a = addressOf(toplevel)
    var b = addressOf(other)
    if (a && b) Quickshell.execDetached(["omamobile-launch", "show-with", a, b])
    closeActions()
    dismiss()
  }

  function moveToOwnScreen(toplevel) {
    var a = addressOf(toplevel)
    if (a) Quickshell.execDetached(["omamobile-launch", "own-screen", a])
    closeActions()
    dismiss()
  }

  function windowLabel(toplevel) {
    if (!toplevel) return ""
    return (toplevel.appId || "App") + (toplevel.title ? "  " + toplevel.title : "")
  }

  readonly property color foreground: Commons.Color.menu.text
  readonly property int touch: Math.max(44, Style.space(44))

  // The dock's navigation strip height (Settings > Keyboard > Bottom gap):
  // recents cover the dock, so they keep a strip of their own that size.
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

  // ---------------------------------------------------------------- bottom-edge gestures

  Phone.PocketStatus { id: pocketGuard }

  Component.onCompleted: Gestures.NavState.listeners++
  Component.onDestruction: Gestures.NavState.listeners = Math.max(0, Gestures.NavState.listeners - 1)

  // "" until the finger picks a direction, then "switch" (sideways) or
  // "recents" (up: home on release, unless a pause armed recents).
  property string navMode: ""
  // A pause on the way up armed recents; where that pause is measured from.
  property bool navArmed: false
  property var navAnchor: null
  // Letting go went home: the picture shrinks away over the home screen.
  property bool navHomeOut: false
  // The nav layer is mapped: from the first touch, so the previews are
  // captured by the time the finger has picked a direction.
  property bool navShown: false
  // The app on screen (null at home) and its neighbours in recents order:
  // newer on the left, older on the right, as the recents cards lie.
  property var navCurrent: null
  property var navNewer: null
  property var navOlder: null
  property var navTarget: null
  // The finger: the cards' sideways offset, and how far up for recents.
  property real navOffset: 0
  property real navLift: 0
  // Animate to a resting place instead of following the finger.
  property bool navSettle: false
  property bool navLanded: false
  property bool navUnlocked: false
  // This gesture began while the last one was still settling: let it pass.
  property bool navIgnored: false
  // Waiting for the lock check before acting.
  property var navAction: null
  readonly property bool navBusy: navSettle || navAction !== null
  readonly property real navGap: Style.space(16)

  // The app in front, if one is: the active toplevel of the newest-first list.
  function navApp() {
    var active = ToplevelManager.activeToplevel
    return active && active.activated && windows.indexOf(active) >= 0 ? active : null
  }

  // The next app from list index `from` (-1 is home, before the newest),
  // skipping apps that share its screen: switching to them changes nothing.
  function navNeighbour(from, step) {
    var ws = from >= 0 ? workspaceOf(windows[from]) : null
    for (var i = from + step; i >= 0 && i < windows.length; i += step) {
      if (ws !== null && ws !== undefined && workspaceOf(windows[i]) === ws) continue
      return windows[i]
    }
    return null
  }

  function navPrime() {
    if (opened || navBusy || pocketGuard.active) {
      navNote("primeBlocked", { opened: opened, settle: navSettle, gatePending: navAction !== null, pocket: pocketGuard.active })
      return
    }
    Hyprland.refreshToplevels()
    navCurrent = navApp()
    var from = navCurrent ? windows.indexOf(navCurrent) : -1
    navNewer = navNeighbour(from, -1)
    navOlder = navNeighbour(from, 1)
    navTarget = null
    navMode = ""
    navOffset = 0
    navLift = 0
    navArmed = false
    navAnchor = null
    navHomeOut = false
    navShown = true
  }

  // A touch that never became a gesture (a tap, or a hold that went home).
  function navUnprime() {
    if (Gestures.NavState.pressed || Gestures.NavState.active || navBusy || navMode !== "") return
    navHide()
  }

  function navHide() {
    navLand.stop()
    navSpring.stop()
    navAfter.stop()
    navStill.stop()
    navShown = false
    navArmed = false
    navAnchor = null
    navHomeOut = false
    navSettle = false
    navLanded = false
    navUnlocked = false
    navMode = ""
    navOffset = 0
    navLift = 0
    navCurrent = null
    navNewer = null
    navOlder = null
    navTarget = null
  }

  function navStart() {
    // A drag the switcher saw no touch for (no NavState.primed): a record of its own.
    if (navTrace.started) {
      navSeq += 1
      navTrace = { seq: navSeq, at: Date.now(), noPrime: true }
    }
    navIgnored = opened || navBusy || pocketGuard.active
    navNote("started", { at: Date.now(), ignored: navIgnored, shown: navShown, opened: opened, settle: navSettle,
                         gatePending: navAction !== null, pocket: pocketGuard.active })
    if (!navIgnored && !navShown) navPrime()
  }

  function navMove() {
    if (navIgnored || !navShown || navBusy || !Gestures.NavState.active) return
    var dx = Gestures.NavState.dx
    var dy = Gestures.NavState.dy
    if (navMode === "") {
      var slop = Style.space(12)
      if (Math.abs(dx) < slop && Math.abs(dy) < slop) return
      if (-dy > Math.abs(dx)) navMode = "recents"
      else if (Math.abs(dx) > Math.abs(dy)) navMode = "switch"
      else return
    }
    if (navMode === "switch") {
      var target = dx < 0 ? navOlder : navNewer
      // Nothing that way: the card gives a little, then springs back.
      navOffset = target ? dx : dx * 0.25
    } else {
      navLift = Math.max(0, -dy)
      navTrack(dx, dy)
    }
    navTrace.mode = navMode
    navTrace.moves = (navTrace.moves || 0) + 1
    navTrace.maxLift = Math.max(navTrace.maxLift || 0, navLift)
  }

  // The swipe up's thresholds, in this shell's logical pixels.
  function navLimits() {
    return {
      armLift: Style.space(64),
      homeLift: Math.max(Style.space(56), stage.height * 0.06),
      flingLift: Style.space(24),
      flingSpeed: 0.6,
      holdMs: NavGesture.HOLD_MS
    }
  }

  // Each move: still within the pause's circle, or a fresh pause from here.
  function navTrack(dx, dy) {
    if (navArmed) return
    var next = NavGesture.track(navAnchor, dx, dy, Date.now(), Style.space(12))
    if (next === navAnchor) return
    navAnchor = next
    navStill.restart()
    navTrace.anchorResets = (navTrace.anchorResets || 0) + 1
  }

  // The pause lasted: arm recents once, with the preview and one tick.
  function navTryArm() {
    var now = Date.now()
    navTrace.timerFires = (navTrace.timerFires || 0) + 1
    navTrace.lastTimer = {
      at: now, armed: navArmed, ignored: navIgnored, settle: navSettle, gatePending: navAction !== null,
      mode: navMode, active: Gestures.NavState.active, lift: navLift, windows: windows.length,
      anchorAgeMs: navAnchor ? now - navAnchor.t : -1, limits: navLimits()
    }
    if (navArmed || navIgnored || navBusy || navMode !== "recents" || !Gestures.NavState.active) return
    if (!NavGesture.shouldArm(navAnchor, now, navLift, navLimits(), windows.length)) return
    navArmed = true
    navTrace.armedAt = { ms: navTrace.started ? now - navTrace.started.at : -1, lift: navLift }
    navPulse()
  }

  function navEnd(canceled) {
    navTrace.ended = {
      at: Date.now(), canceled: canceled, ignored: navIgnored, pocket: pocketGuard.active, mode: navMode,
      armed: navArmed, lift: navLift, vy: Gestures.NavState.vy, dx: Gestures.NavState.dx, dy: Gestures.NavState.dy,
      timerRunning: navStill.running, anchorAgeMs: navAnchor ? Date.now() - navAnchor.t : -1,
      sinceStartMs: navTrace.started ? Date.now() - navTrace.started.at : -1
    }
    if (navIgnored) { navIgnored = false; return }
    if (canceled || pocketGuard.active || navMode === "") { navCancel(); return }
    navSettle = true
    if (navMode === "switch") {
      var dx = Gestures.NavState.dx
      var vx = Gestures.NavState.vx
      var target = dx < 0 ? navOlder : navNewer
      var far = Math.abs(dx) > stage.width * 0.3
      var flung = Math.abs(vx) > 0.5 && (vx < 0) === (dx < 0) && Math.abs(dx) > Style.space(24)
      if (!target || !(far || flung)) { navCancel(); return }
      navTarget = target
      navOffset = dx < 0 ? -(stage.width + navGap) : stage.width + navGap
      navLand.restart()
      navGate(function() { root.navUnlocked = true; root.navCommitSwitch() })
    } else {
      navStill.stop()
      var action = NavGesture.release(navArmed, navLift, Gestures.NavState.vy, navLimits())
      navTrace.decision = action
      if (action === "cancel") { navCancel(); return }
      if (action === "home") { navGate(function() { root.navCommitHome() }); return }
      navGate(function() {
        if (root.shell && typeof root.shell.summon === "function")
          root.navTrace.summon = String(root.shell.summon(root.pluginId, "{}"))
        else { root.navTrace.summon = "local"; root.open("{}") }
        root.navTrace.openedAfterSummon = root.opened
        // Recents maps above this layer; drop it once it has.
        navAfter.restart()
      })
    }
  }

  // The picture shrinks and fades over the home screen as it comes up.
  function navCommitHome() {
    navHomeOut = true
    navPulse()
    goHome()
    navSpring.restart()
  }

  // Both the slide has landed and the lock said yes: switch, then let the
  // compositor show the real window before the picture goes.
  function navCommitSwitch() {
    if (!navLanded || !navUnlocked) return
    var target = navTarget
    if (!target || windows.indexOf(target) < 0) { navCancel(); return }
    target.activate()
    navPulse()
    navAfter.restart()
  }

  function navCancel() {
    navAction = null
    navTarget = null
    navSettle = true
    navStill.stop()
    navArmed = false
    navOffset = 0
    navLift = 0
    navSpring.restart()
  }

  function navHome() {
    navNote("held", { at: Date.now(), mode: navMode, opened: opened, settle: navSettle, gatePending: navAction !== null })
    if (opened || navBusy || navMode !== "" || pocketGuard.active) return
    navGate(function() {
      root.navPulse()
      root.goHome()
      root.navHide()
    })
  }

  Timer { id: navLand; interval: 200; onTriggered: { root.navLanded = true; root.navCommitSwitch() } }
  Timer { id: navSpring; interval: 200; onTriggered: root.navHide() }
  Timer { id: navAfter; interval: 120; onTriggered: root.navHide() }
  // A little past the hold time, as timers may fire early.
  Timer { id: navStill; interval: NavGesture.HOLD_MS + 20; onTriggered: root.navTryArm() }

  // Act only while unlocked: a gesture that ends after the lock came up
  // (power pressed mid-swipe) does nothing. The lock service is not one a
  // third-party plugin can bind to, so ask it, as omamobile.call does.
  function navGate(action) {
    navAction = action
    if (!lockCheck.running) lockCheck.running = true
  }

  function navGateDone(unlocked) {
    var action = navAction
    navAction = null
    navNote("gate", { at: Date.now(), unlocked: unlocked, hadAction: !!action, pocket: pocketGuard.active,
                      lockText: navLockText, lockExit: navLockExit })
    if (!action) return
    if (unlocked && !pocketGuard.active) action()
    else navCancel()
  }

  Process {
    id: lockCheck
    command: ["timeout", "2", "omarchy-shell", "lock", "isLocked"]
    onStarted: { root.navLockText = ""; root.navLockExit = -1 }
    stdout: StdioCollector {
      onStreamFinished: {
        root.navLockText = text.trim().split("\n").pop().trim()
        root.navGateDone(root.navLockText === "false")
      }
    }
    onExited: function(exitCode) {
      root.navLockExit = exitCode
      if (exitCode !== 0) root.navGateDone(false)
    }
  }

  // ---------------------------------------------------------------- diagnostics

  // The last bottom-edge gesture as the switcher saw it, read-only:
  //   omarchy-shell shell call omamobile.switcher state ''
  // A gesture's record starts at the touch (NavState.primed); a record that
  // never changes on a swipe means the switcher is not hearing the dock.
  property int navSeq: 0
  property var navTrace: ({})
  property var navLastOpen: null
  property var navLastHome: null
  property string navLockText: ""
  property int navLockExit: -1

  function navNote(key, value) { navTrace[key] = value }

  function state() {
    var hyprMapped = 0
    var hypr = Hyprland.toplevels.values
    for (var i = 0; i < hypr.length; i++) if (hypr[i].lastIpcObject && hypr[i].lastIpcObject.mapped !== false) hyprMapped++
    return JSON.stringify({
      opened: opened,
      windows: windows.map(function(w) { return w.appId || "" }),
      activeApp: navApp() ? navApp().appId : null,
      hyprlandToplevels: hypr.length,
      hyprlandMapped: hyprMapped,
      focusedWorkspaceToplevels: Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.toplevels.values.length : -1,
      hasShellSummon: !!(shell && typeof shell.summon === "function"),
      navState: {
        listeners: Gestures.NavState.listeners, attached: Gestures.NavState.attached,
        pressed: Gestures.NavState.pressed, active: Gestures.NavState.active
      },
      nav: {
        shown: navShown, mode: navMode, armed: navArmed, settle: navSettle, ignored: navIgnored,
        gatePending: navAction !== null, lockRunning: lockCheck.running,
        stillRunning: navStill.running, stillInterval: navStill.interval, holdMs: NavGesture.HOLD_MS,
        anchor: navAnchor, pocket: pocketGuard.active, navigationHeight: navigationHeight
      },
      last: navTrace,
      lastOpen: navLastOpen,
      lastHome: navLastHome
    })
  }

  // Touch feedback through the bounded helper: it honours the user's Touch
  // feedback setting, the lock, pocket protection and its own rate limit.
  Process { id: haptic; command: ["timeout", "2", "omamobile-haptics", "pulse"] }
  function navPulse() { if (!haptic.running) haptic.running = true }

  Connections {
    target: Gestures.NavState
    function onPrimed() {
      root.navSeq += 1
      root.navTrace = { seq: root.navSeq, at: Date.now() }
      root.navPrime()
    }
    function onPressedChanged() { if (!Gestures.NavState.pressed) Qt.callLater(root.navUnprime) }
    function onStarted() { root.navStart() }
    function onDxChanged() { root.navMove() }
    function onDyChanged() { root.navMove() }
    function onEnded(canceled) { root.navEnd(canceled) }
    function onHeld() { root.navHome() }
  }

  Connections {
    target: pocketGuard
    function onActiveChanged() { if (pocketGuard.active && root.navShown) root.navCancel() }
  }

  Behavior on navOffset { enabled: root.navSettle; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
  Behavior on navLift { enabled: root.navSettle; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

  // Where apps sit on screen (maximized between the bar and the dock), from
  // Hyprland, so the gesture starts from exactly the picture already shown.
  function navRect() {
    var list = [navCurrent, navOlder, navNewer]
    var origin = navLayer.screen ? Qt.point(navLayer.screen.x, navLayer.screen.y) : Qt.point(0, 0)
    for (var i = 0; i < list.length; i++) {
      var hypr = hyprlandFor(list[i])
      var ipc = hypr ? hypr.lastIpcObject || ({}) : ({})
      if (ipc.at && ipc.size && ipc.size[0] > 0 && ipc.size[1] > 0)
        return Qt.rect(ipc.at[0] - origin.x, ipc.at[1] - origin.y, ipc.size[0], ipc.size[1])
    }
    return Qt.rect(0, 0, navLayer.width, navLayer.height)
  }

  // The gesture's pictures: a click-through layer above the apps, so the
  // finger stays with the dock and the keyboard keeps its touches.
  PanelWindow {
    id: navLayer

    visible: root.navShown
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    mask: Region {}
    WlrLayershell.namespace: "omamobile-nav"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Item {
      id: stage

      readonly property rect area: root.navShown ? root.navRect() : Qt.rect(0, 0, 0, 0)
      // 0..1 on the way up to recents.
      readonly property real lift: root.navMode === "recents" ? Math.min(1, root.navLift / Math.max(1, height * 0.6)) : 0
      x: area.x
      y: area.y
      width: area.width
      height: area.height
      clip: true
      // Shown once the direction is known and the picture of the app in
      // front has arrived; until then the real app stays in view.
      opacity: root.navMode !== "" && (root.navCurrent === null || currentCard.ready) ? 1 : 0

      // Covers the real app under its moving picture; dims home once
      // recents are armed. Fades as the picture goes home.
      Rectangle {
        anchors.fill: parent
        visible: root.navCurrent !== null || root.navArmed
        color: root.navMode === "recents" ? Commons.Color.menu.background : Commons.Color.background
        opacity: root.navHomeOut ? 0 : (root.navCurrent !== null ? 1 : 0.94)
        Behavior on opacity { enabled: root.navHomeOut; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
      }

      // The row of pictures: it shrinks as the finger rises, settles to the
      // recents size with the neighbours beside it once armed (from home,
      // the newest app in the middle), and shrinks away going home.
      Item {
        id: deck
        width: stage.width
        height: stage.height
        x: root.navArmed && root.navCurrent === null ? -(stage.width + root.navGap) * scale : 0
        y: -root.navLift * 0.4
        scale: root.navHomeOut ? 0.3 : (root.navArmed ? 0.62 : 1 - 0.4 * stage.lift)
        opacity: root.navHomeOut ? 0 : 1
        Behavior on scale { enabled: root.navArmed || root.navHomeOut || root.navSettle; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on opacity { enabled: root.navHomeOut; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        NavCard {
          toplevel: root.navNewer
          visible: toplevel !== null && (root.navMode === "switch" || root.navArmed)
          x: root.navOffset - stage.width - root.navGap
        }

        NavCard {
          id: currentCard
          toplevel: root.navCurrent
          lift: root.navArmed ? 1 : stage.lift
          x: root.navOffset
        }

        NavCard {
          toplevel: root.navOlder
          visible: toplevel !== null && (root.navMode === "switch" || root.navArmed)
          x: root.navOffset + stage.width + root.navGap
        }
      }
    }
  }

  // One app's still picture in a gesture, the size of the app on screen.
  component NavCard: Rectangle {
    id: navCard

    property var toplevel: null
    property real lift: 0
    readonly property bool ready: shot.hasContent

    width: parent ? parent.width : 0
    height: parent ? parent.height : 0
    visible: toplevel !== null
    // Square at rest, like the window; rounded as it moves away.
    radius: Math.min(Style.cornerRadius, Math.abs(x) / 8 + lift * Style.cornerRadius * 4)
    clip: true
    color: Commons.Color.background

    ScreencopyView {
      id: shot
      anchors.fill: parent
      // Still, as in recents: a fresh snapshot each time the layer maps.
      captureSource: root.navShown && navCard.toplevel ? navCard.toplevel : null
      live: false
    }
  }

  PanelWindow {
    id: overlay

    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.namespace: "omamobile-switcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    onVisibleChanged: if (visible) cards.positionViewAtBeginning()

    Rectangle {
      anchors.fill: parent
      color: Commons.Color.menu.background
      opacity: 0.94
    }

    // Tapping empty space goes back to whatever was on screen. With no apps
    // open recents go home on their own (open, onWindowsChanged).
    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    Item {
      anchors.fill: parent
      focus: root.opened
      Keys.onEscapePressed: {
        if (root.actionsOpen) root.closeActions()
        else root.dismiss()
      }
    }

    ListView {
      id: cards

      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: -Style.space(24)
      height: Math.round(parent.height * 0.68)

      // Empty, it would still catch taps meant to close recents.
      visible: root.windows.length > 0
      interactive: visible
      orientation: ListView.Horizontal
      spacing: Style.space(18)
      snapMode: ListView.SnapToItem
      highlightRangeMode: ListView.StrictlyEnforceRange
      preferredHighlightBegin: (width - cardWidth) / 2
      preferredHighlightEnd: (width + cardWidth) / 2
      boundsBehavior: Flickable.StopAtBounds
      model: root.windows

      readonly property int cardWidth: Math.round(width * 0.72)

      delegate: Item {
        id: slot
        required property var modelData
        required property int index

        width: cards.cardWidth
        height: cards.height

        // Title row: app and window title.
        Text {
          id: title
          anchors.left: card.left
          anchors.right: card.right
          anchors.bottom: card.top
          anchors.bottomMargin: Style.space(8)
          opacity: card.opacity
          textFormat: Text.PlainText
          text: (slot.modelData.appId || "") + (slot.modelData.title ? "  " + slot.modelData.title : "")
          elide: Text.ElideRight
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Rectangle {
          id: card

          width: parent.width
          height: parent.height - title.height - Style.space(8)
          y: title.height + Style.space(8) + drag.lift
          radius: Style.cornerRadius
          clip: true
          color: Commons.Color.background
          border.width: 2
          border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.25)
          opacity: 1 - Math.min(0.8, Math.abs(drag.lift) / height)

          ScreencopyView {
            anchors.fill: parent
            anchors.margins: card.border.width
            captureSource: root.opened ? slot.modelData : null
            // A still preview is enough for recents. Continuously copying and
            // scaling every open surface makes the software Qt Quick fallback
            // unusably slow on devices whose shell cannot use a GPU scenegraph.
            // Rebinding captureSource on every open takes a fresh snapshot.
            live: false
          }

          // Tap to switch; hold for "Show with…" and "Move to its own screen".
          TapHandler {
            onTapped: root.switchTo(slot.modelData)
            onLongPressed: root.openActions(slot.modelData)
          }

          // Flick up to close; anything shorter springs back.
          DragHandler {
            id: drag
            target: null
            xAxis.enabled: false
            property real lift: 0
            onActiveTranslationChanged: lift = Math.min(0, activeTranslation.y)
            onActiveChanged: {
              if (active) return
              if (lift < -card.height * 0.25) {
                closeOut.start()
              } else {
                springBack.start()
              }
            }
          }

          NumberAnimation {
            id: springBack
            target: drag; property: "lift"; to: 0
            duration: 160; easing.type: Easing.OutCubic
          }

          SequentialAnimation {
            id: closeOut
            NumberAnimation { target: drag; property: "lift"; to: -card.height * 1.2; duration: 160; easing.type: Easing.InCubic }
            ScriptAction { script: { slot.modelData.close(); drag.lift = 0 } }
          }
        }
      }
    }

    // Bottom actions: clear everything, or go home. Clear all closes the
    // last app, so recents then go home too.
    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Math.max(Style.space(28), root.navigationHeight + Style.space(8))
      spacing: Style.space(16)

      Repeater {
        model: [
          { label: "Clear all", visible: root.windows.length > 0, action: "clear" },
          { label: "Home", visible: root.windows.length > 0, action: "home" }
        ]

        delegate: BorderSurface {
          id: bottomButton
          required property var modelData
          visible: modelData.visible
          width: Math.max(root.touch * 2.6, label.implicitWidth + Style.space(32))
          height: root.touch
          radius: Style.cornerRadius
          color: tap.pressed ? Commons.Color.menu.selected || Commons.Color.background : Commons.Color.background

          Text {
            id: label
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: bottomButton.modelData.label
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          TapHandler {
            id: tap
            onTapped: bottomButton.modelData.action === "home" ? root.goHome() : root.closeAll()
          }
        }
      }
    }

    // The system strip over the dock's, which recents cover: swipe up here to
    // go home, as from an app. Taps fall through to close recents. It takes
    // no keyboard focus, and nothing above the lock (no above_lock rule).
    Item {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: root.navigationHeight

      Rectangle {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: Math.max(-Style.space(10), homeSwipe.lift * 0.08)
        width: Math.max(72, Style.space(96))
        height: Math.max(4, Style.space(5))
        radius: height / 2
        color: root.foreground
        opacity: 0.75
      }

      DragHandler {
        id: homeSwipe
        target: null
        xAxis.enabled: false
        property real lift: 0
        onActiveTranslationChanged: lift = Math.min(0, activeTranslation.y)
        onActiveChanged: {
          if (active) return
          var swiped = lift < -Style.space(24)
          lift = 0
          if (swiped && !pocketGuard.active)
            root.navGate(function() { root.navPulse(); root.goHome() })
        }
      }
    }

    // Hold actions: a sheet over the cards. Tapping outside it closes it.
    Item {
      id: actionLayer
      anchors.fill: parent
      visible: root.actionsOpen

      Rectangle {
        anchors.fill: parent
        color: Commons.Color.menu.background
        opacity: 0.6
      }

      MouseArea {
        anchors.fill: parent
        onClicked: root.closeActions()
      }

      BorderSurface {
        id: actionCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Style.space(16)
        anchors.bottomMargin: Style.space(28)
        height: actionColumn.implicitHeight + Style.space(24)
        radius: Style.cornerRadius
        color: Commons.Color.background

        // Swallows taps between the rows, so they don't close the sheet.
        MouseArea { anchors.fill: parent }

        Column {
          id: actionColumn
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(12)
          spacing: Style.space(6)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.actionPage === "pick" ? "Show with…" : root.windowLabel(root.actionTarget)
            elide: Text.ElideRight
            color: Qt.darker(root.foreground, 1.3)
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            bottomPadding: Style.space(6)
          }

          // The menu.
          SheetRow {
            visible: root.actionPage === "menu"
            enabled: root.actionsOpen && root.partners(root.actionTarget).length > 0
            text: "Show with…"
            hint: enabled ? "Share the screen with another open app" : "No other app is open"
            onActivated: root.actionPage = "pick"
          }

          SheetRow {
            visible: root.actionPage === "menu" && root.actionsOpen && root.screenMates(root.actionTarget).length > 0
            text: "Move to its own screen"
            hint: "Stop sharing the screen"
            onActivated: root.moveToOwnScreen(root.actionTarget)
          }

          // The apps to share a screen with.
          Repeater {
            model: root.actionPage === "pick" && root.actionsOpen ? root.partners(root.actionTarget) : []

            delegate: SheetRow {
              required property var modelData
              text: modelData.appId || "App"
              hint: modelData.title || ""
              onActivated: root.showWith(root.actionTarget, modelData)
            }
          }

          SheetRow {
            text: root.actionPage === "pick" ? "Back" : "Cancel"
            onActivated: {
              if (root.actionPage === "pick") root.actionPage = "menu"
              else root.closeActions()
            }
          }
        }
      }
    }
  }

  // One row of the hold-actions sheet: a label over a hint.
  component SheetRow: Rectangle {
    id: sheetRow

    property string text: ""
    property string hint: ""
    signal activated()

    width: parent ? parent.width : 0
    height: Math.max(root.touch, rowText.implicitHeight + (rowHint.visible ? rowHint.implicitHeight : 0) + Style.space(16))
    radius: Style.cornerRadius
    color: rowTap.pressed ? (Commons.Color.menu.selected || Commons.Color.background) : "transparent"
    opacity: enabled ? 1 : 0.45

    Column {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(12)
      anchors.rightMargin: Style.space(12)

      Text {
        id: rowText
        width: parent.width
        textFormat: Text.PlainText
        text: sheetRow.text
        elide: Text.ElideRight
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
      }

      Text {
        id: rowHint
        width: parent.width
        visible: sheetRow.hint.length > 0
        textFormat: Text.PlainText
        text: sheetRow.hint
        elide: Text.ElideRight
        color: Qt.darker(root.foreground, 1.4)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
    }

    MouseArea {
      id: rowTap
      anchors.fill: parent
      enabled: sheetRow.enabled
      onClicked: sheetRow.activated()
    }
  }
}

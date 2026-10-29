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

Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool opened: false
  property var policy: ({locked:true, allowed:[], hints:true, hint_seconds:5})
  property var live: ({})
  property double now: Date.now()
  property string error: ""
  Phone.PocketStatus { id: pocket }
  // Keep the hint at the same physical panel corner as portrait bottom-right.
  // Use the inverse output transform to map the physical corner into
  // logical layer coordinates; rotate safe-area insets with that corner.
  readonly property int outputTransform: Number(live.current || 0)
  readonly property bool hintTop: outputTransform === 3 || outputTransform === 2
  readonly property bool hintLeft: outputTransform === 2 || outputTransform === 1
  readonly property bool hintLandscape: outputTransform === 1 || outputTransform === 3
  readonly property var hint: live.hint || null
  readonly property bool fresh: now - Number(live.at_wall || 0)*1000 < 3000
  readonly property bool hintVisible: !!hint && fresh && live.safe === true && live.locked === true
    && !pocket.active && !opened && Number(hint.expires_wall)*1000 > now
  readonly property var directions: [
    { id:"normal", label:"Portrait", detail:"Upright", glyph:"󰄜", turn:0 },
    { id:"left-up", label:"Landscape left", detail:"Top of the phone points left", glyph:"󰄜", turn:-90 },
    { id:"right-up", label:"Landscape right", detail:"Top of the phone points right", glyph:"󰄜", turn:90 },
    { id:"bottom-up", label:"Upside-down portrait", detail:"Top of the phone points down", glyph:"󰄜", turn:180 }
  ]
  function open(payloadJson) { opened=true; refresh() }
  function close() { opened=false }
  function dismiss() {
    opened=false
    if (shell && typeof shell.hide === "function") shell.hide("omamobile.rotation")
  }
  function refresh() { if (!read.running) read.running=true }
  function state() { return JSON.stringify({opened:opened, policy:policy, hintVisible:hintVisible, hint:hint, outputTransform:outputTransform, hintTop:hintTop, hintLeft:hintLeft}) }
  function change(command, value) {
    if (write.running || read.running) return
    error=""
    write.command=["omamobile-rotation",command,value || ""]
    write.running=true
  }
  function configure(value) { change("configure",JSON.stringify(value)) }
  function toggleDirection(id) {
    var allowed=policy.allowed.slice()
    var index=allowed.indexOf(id)
    if (index<0) allowed.push(id); else allowed.splice(index,1)
    configure({allowed:allowed})
  }
  FileView {
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/omamobile-rotation.json"
    watchChanges:true
    onFileChanged:reload()
    onLoaded: { try { root.live=JSON.parse(text()) } catch(e) { root.live=({}) } }
    onLoadFailed:root.live=({})
  }
  Timer { interval:100; running:!!root.hint; repeat:true; onTriggered:root.now=Date.now() }
  Timer { interval:1000; running:root.opened; repeat:true; onTriggered:root.refresh() }
  Process {
    id:read
    command:["omamobile-rotation","status"]
    stdout:StdioCollector { waitForEnd:true; onStreamFinished: { try { root.policy=JSON.parse(text); root.error="" } catch(e) { root.error="Rotation service unavailable" } } }
  }
  Process { id:write; onExited:function(code,status) { if(code!==0) root.error="Could not update rotation setting"; root.refresh() } }
  Process { id:accept }
  // ---------------------------------------------------------------- settings

  // Laid out like quick settings' Wi-Fi panel: a popup card over a scrim,
  // a back glyph, and full-width rows with a switch at the end.
  readonly property color foreground: Commons.Color.popups.text
  readonly property int touchSize: Math.max(44, Style.space(48))
  readonly property bool busy: write.running

  property real reveal: opened ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

  PanelWindow {
    id:panel
    visible:root.opened || root.reveal > 0
    anchors { top:true; bottom:true; left:true; right:true }
    exclusionMode:ExclusionMode.Normal
    WlrLayershell.namespace:"omamobile-rotation-settings"
    WlrLayershell.layer:WlrLayer.Overlay
    WlrLayershell.keyboardFocus:root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    color:"transparent"

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
      x: Style.gapsOut
      width: parent.width - Style.gapsOut * 2
      height: parent.height - Style.gapsOut * 2
      y: Style.gapsOut + Math.round((1 - root.reveal) * Style.space(60))
      opacity: root.reveal
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      padding: Style.spacing.panelPadding

      focus: root.opened
      Keys.onEscapePressed: root.dismiss()

      // Swallow taps so they don't reach the scrim.
      MouseArea { anchors.fill: parent }

      Item {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset

        // ---------- Header: back, title
        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.touchSize

          QuickSettings.GlyphButton {
            id: back
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            glyph: "󰁍"
            foreground: root.foreground
            onTapped: root.dismiss()
          }

          Text {
            anchors.left: back.right
            anchors.leftMargin: Style.spacing.lg
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "Rotation"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }
        }

        Flickable {
          anchors.top: header.bottom
          anchors.topMargin: Style.spacing.lg
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          clip: true
          contentHeight: content.height
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: content
            width: parent.width
            spacing: Style.spacing.md

            SwitchRow {
              foreground: root.foreground
              busy: root.busy
              label: "Auto-rotate"
              detail: root.policy.locked ? "Locked to current orientation" : "Follows how you hold the phone"
              glyph: "󰑵"
              checked: !root.policy.locked
              onTapped: root.change(root.policy.locked ? "unlock" : "lock", "")
            }

            PanelSectionHeader {
              width: parent.width
              topPadding: Style.spacing.lg
              text: "Allowed orientations"
              foreground: root.foreground
            }

            Repeater {
              model: root.directions
              delegate: SwitchRow {
                required property var modelData
                foreground: root.foreground
                busy: root.busy
                width: content.width
                label: modelData.label
                detail: modelData.detail
                glyph: modelData.glyph
                glyphRotation: modelData.turn
                checked: root.policy.allowed.indexOf(modelData.id) >= 0
                onTapped: root.toggleDirection(modelData.id)
              }
            }

            PanelSectionHeader {
              width: parent.width
              topPadding: Style.spacing.lg
              text: "Suggestions"
              foreground: root.foreground
            }

            SwitchRow {
              foreground: root.foreground
              busy: root.busy
              label: "Suggest rotation"
              detail: "Floating button while rotation is locked"
              glyph: "󰑓"
              checked: !!root.policy.hints
              onTapped: root.configure({hints: !root.policy.hints})
            }

            // Hint lifetime: 2–15 seconds.
            BorderSurface {
              width: parent.width
              height: Math.max(56, Style.space(60))
              radius: Style.cornerRadius
              enabled: !!root.policy.hints && !root.busy
              opacity: enabled ? 1 : 0.45
              color: Style.normalFillFor(root.foreground, Commons.Color.accent)
              borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.xxl
                anchors.right: minus.left
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "Show for"
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }

              QuickSettings.GlyphButton {
                id: minus
                anchors.right: seconds.left
                anchors.verticalCenter: parent.verticalCenter
                glyph: "󰍴"
                foreground: root.foreground
                enabled: parent.enabled && root.policy.hint_seconds > 2
                onTapped: root.configure({hint_seconds: Math.max(2, root.policy.hint_seconds - 1)})
              }

              Text {
                id: seconds
                anchors.right: plus.left
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(56)
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: root.policy.hint_seconds + " s"
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
              }

              QuickSettings.GlyphButton {
                id: plus
                anchors.right: parent.right
                anchors.rightMargin: Style.spacing.sm
                anchors.verticalCenter: parent.verticalCenter
                glyph: "󰐕"
                foreground: root.foreground
                enabled: parent.enabled && root.policy.hint_seconds < 15
                onTapped: root.configure({hint_seconds: Math.min(15, root.policy.hint_seconds + 1)})
              }
            }

            Text {
              width: parent.width
              topPadding: Style.spacing.sm
              wrapMode: Text.WordWrap
              textFormat: Text.PlainText
              text: "Tap the floating button to rotate once and keep the lock. Ignore it to keep the current orientation."
              color: Qt.darker(root.foreground, 1.4)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
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
      }
    }
  }
  PanelWindow {
    id:hintWindow
    visible:root.hintVisible
    anchors {
      top:root.hintTop; bottom:!root.hintTop
      left:root.hintLeft; right:!root.hintLeft
    }
    margins {
      top:root.hintTop ? (root.hintLandscape ? 28 : 96) : 0
      bottom:!root.hintTop ? (root.hintLandscape ? 28 : 96) : 0
      left:root.hintLeft ? (root.hintLandscape ? 96 : 28) : 0
      right:!root.hintLeft ? (root.hintLandscape ? 96 : 28) : 0
    }
    implicitWidth:64; implicitHeight:64
    exclusionMode:ExclusionMode.Ignore
    WlrLayershell.namespace:"omamobile-rotation-hint"
    WlrLayershell.layer:WlrLayer.Overlay
    WlrLayershell.keyboardFocus:WlrKeyboardFocus.None
    color:"transparent"
    Rectangle {
      anchors.fill:parent; color:Commons.Color.background; border.width:2; border.color:Commons.Color.accent
      opacity:root.hint ? Math.max(0,Math.min(1,(Number(root.hint.expires_wall)*1000-root.now)/600)) : 0
      Text { anchors.centerIn:parent; text:"󰑵"; color:Commons.Color.accent; font.family:Style.font.family; font.pixelSize:30 }
      MouseArea {
        anchors.fill:parent
        onClicked: {
          if (!root.hintVisible || accept.running) return
          accept.command=["omamobile-rotation","accept",root.hint.token]
          accept.running=true
        }
      }
    }
  }
}

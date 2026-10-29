// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "LocationModel.js" as LocationModel

// The page behind the Location tile, after the Wi-Fi and Bluetooth panels:
// what is using location now and which apps and processes used it recently.
//
// It reads `omamobile-location history` (the root observer's answer for this
// user only) and asks it nothing else but `clear`. It polls every two seconds
// while it is open and not at all when hidden. App names are what each app
// reports about itself and the process is what the bus saw; neither is proof
// of identity, and the panel says so. No coordinates exist in the history.
Item {
  id: root

  property bool opened: false
  property color foreground: Commons.Color.popups.text
  // The tile's status line ("Off", "On", "In use", "Receiver on").
  property string tileStatus: ""
  property bool twelveHour: false

  // The back glyph: the owner closes this and brings quick settings back.
  signal backRequested()
  signal refreshRequested()
  property bool clearFailed: false

  readonly property int touchSize: Math.max(44, Style.space(48))
  readonly property int pad: Style.spacing.panelPadding

  // The observer's last answer (null: not answering) and its entries.
  property var data: null
  property var entries: []
  readonly property var activeEntries: entries.filter(function(e) { return e.active })
  readonly property var recentEntries: entries.filter(function(e) { return !e.active })

  function open() {
    if (opened) return
    opened = true
    refresh()
  }

  function close() { opened = false }

  function refresh() {
    if (!opened) return
    refreshRequested()
    if (!historyRead.running) historyRead.running = true
  }

  // `shell call` helper: the panel's state as JSON.
  function snapshot() {
    return JSON.stringify({ opened: opened, status: tileStatus, observer: !!data,
                            active: activeEntries.length, recent: recentEntries.length })
  }

  Process {
    id: historyRead
    command: ["omamobile-location", "history"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = LocationModel.parse(text)
        root.data = parsed ? parsed.status : null
        root.entries = parsed && Array.isArray(parsed.entries) ? parsed.entries : []
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) { root.data = null; root.entries = [] }
    }
  }

  Process {
    id: clearWrite
    command: ["omamobile-location", "clear"]
    onExited: function(exitCode) {
      root.clearFailed = exitCode !== 0
      root.refresh()
    }
  }

  // Nothing runs while the panel is hidden.
  Timer {
    interval: 2000
    running: root.opened
    repeat: true
    onTriggered: root.refresh()
  }

  property real reveal: opened ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

  PanelWindow {
    id: window

    visible: root.opened || root.reveal > 0
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Normal
    color: "transparent"
    WlrLayershell.namespace: "omamobile-location"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    Rectangle {
      anchors.fill: parent
      color: Commons.Color.menu.scrim
      opacity: root.reveal
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.close()
    }

    BorderSurface {
      id: panel

      x: Style.gapsOut
      width: parent.width - Style.gapsOut * 2
      height: parent.height - Style.gapsOut * 2
      y: Style.gapsOut + Math.round((1 - root.reveal) * Style.space(60))
      opacity: root.reveal
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      padding: root.pad

      focus: root.opened
      Keys.onEscapePressed: root.close()

      // Swallow taps so they don't reach the scrim.
      MouseArea { anchors.fill: parent }

      Item {
        id: body
        anchors.fill: parent
        anchors.topMargin: panel.contentTopInset
        anchors.rightMargin: panel.contentRightInset
        anchors.bottomMargin: panel.contentBottomInset
        anchors.leftMargin: panel.contentLeftInset

        // ---------- Header: back and title
        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.touchSize

          GlyphButton {
            id: back
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            glyph: "󰁍"
            onTapped: root.backRequested()
          }

          Text {
            anchors.left: back.right
            anchors.leftMargin: Style.spacing.lg
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "Location"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }
        }

        // ---------- State and what the monitor can and cannot see
        Column {
          id: summary
          anchors.top: header.bottom
          anchors.topMargin: root.pad
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: Style.spacing.xs

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.tileStatus
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
          }
          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            text: LocationModel.coverage(root.data, root.twelveHour)
            color: root.foreground
            opacity: 0.7
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }
        }

        // ---------- The lists
        Flickable {
          id: scroller
          anchors.top: summary.bottom
          anchors.topMargin: Style.spacing.lg
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: footer.top
          anchors.bottomMargin: Style.spacing.md
          clip: true
          contentWidth: width
          contentHeight: lists.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: lists
            width: scroller.width
            spacing: Style.spacing.md

            Text {
              visible: root.activeEntries.length > 0
              width: parent.width
              textFormat: Text.PlainText
              text: "In use now"
              color: root.foreground
              opacity: 0.7
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.activeEntries
              delegate: Loader {
                required property var modelData
                width: lists.width
                sourceComponent: entryRow
                onLoaded: item.entry = modelData
              }
            }

            Text {
              visible: root.recentEntries.length > 0
              width: parent.width
              textFormat: Text.PlainText
              text: "Recent"
              color: root.foreground
              opacity: 0.7
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.recentEntries
              delegate: Loader {
                required property var modelData
                width: lists.width
                sourceComponent: entryRow
                onLoaded: item.entry = modelData
              }
            }

            Text {
              visible: root.data && root.entries.length === 0
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.Wrap
              text: "No location use recorded."
              color: root.foreground
              opacity: 0.7
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
          }
        }

        Component {
          id: entryRow
          BorderSurface {
            id: row
            property var entry: ({})
            width: parent ? parent.width : 0
            height: Math.max(root.touchSize, rowText.implicitHeight + Style.spacing.lg * 2)
            radius: Style.cornerRadius
            color: row.entry.active ? Util.alpha(Commons.Color.accent, Style.selectedFillAlpha)
              : Style.normalFillFor(root.foreground, Commons.Color.accent)
            borderSpec: Border.controlSpec(row.entry.active ? "selected" : "normal", root.foreground, Commons.Color.accent)

            Column {
              id: rowText
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.lg
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.lg
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.spacing.xs
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: LocationModel.title(row.entry)
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: LocationModel.processLine(row.entry)
                color: root.foreground
                opacity: 0.7
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                text: LocationModel.timing(row.entry, root.twelveHour)
                color: root.foreground
                opacity: 0.7
                font.family: Style.font.family
                font.pixelSize: Style.font.body
              }
            }
          }
        }

        // ---------- Footer: limits and Clear
        Column {
          id: footer
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          spacing: Style.spacing.md

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            text: "Apps name themselves and the process is what the system saw; neither proves who an app is. Only your own uses are listed: the last 7 days, 50 at most. No locations are stored."
            color: root.foreground
            opacity: 0.7
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          SheetButton {
            width: parent.width
            label: clearWrite.running ? "Clearing…" : root.clearFailed ? "Clear failed · retry" : "Clear history"
            foreground: root.foreground
            enabled: !!root.data && LocationModel.finished(root.entries) > 0 && !clearWrite.running
            onTapped: { root.clearFailed = false; clearWrite.running = true }
          }
        }
      }
    }
  }
}

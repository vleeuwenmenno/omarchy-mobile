// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

Item {
  id: widget
  property var host: null
  property var settings: ({})
  property bool editing: false
  property int cellsWide: 4
  property int cellsHigh: 3
  property var reading: null
  property string failure: ""
  property double until: 0
  property int seconds: 0
  readonly property bool live: seconds > 0
  readonly property bool active: !!host && host.active === true && visible && !editing
  property double lastRead: 0
  property bool restartFast: false
  readonly property color fg: host ? host.foreground : Commons.Color.menu.text
  readonly property color dim: host ? host.dimForeground : Commons.Color.menu.text
  readonly property real heading: {
    const rows = reading && reading.rows ? reading.rows : []
    for (const row of rows) {
      if (row.label === "Compass" && (row.state === "reported" || row.state === "updated"))
        return live ? parseFloat(row.value) : (Math.round(parseFloat(row.value) / 5) * 5) % 360
    }
    return -1
  }

  function refresh() {
    // Small timer jitter must not turn a two-second tick into four seconds.
    if (!active || sampler.running || live || Date.now() - lastRead < 1900) return
    start(false)
  }
  function start(fast) {
    if (!active || sampler.running || !host.canRunCommands) return
    lastRead = Date.now()
    sampler.fastRun = fast
    sampler.command = ["timeout", "-k", "2", fast ? "65" : "10", "python3", "-u", host.dir + "/read-sensors.py"].concat(fast ? ["--stream"] : [])
    sampler.running = true
  }
  function toggle() {
    if (!active) return
    if (live) { stop(); return }
    until = Date.now() + 60000
    seconds = 60
    if (sampler.running) { restartFast = true; sampler.running = false }
    else start(true)
  }
  function stop() {
    seconds = 0
    restartFast = false
    sampler.running = false
  }
  function accept(line) {
    try {
      const data = JSON.parse(line)
      failure = data.error || ""
      if (data.suspended) { stop(); return }
      reading = data
    } catch (e) { failure = "Invalid sensor response"; stop() }
  }
  Component.onCompleted: refresh()
  Component.onDestruction: stop()
  onActiveChanged: { if (!active) stop(); else refresh() }
  Process {
    id: sampler
    property bool fastRun: false
    stdout: SplitParser { onRead: function(line) { widget.accept(line) } }
    onExited: function(code) {
      if (widget.restartFast && widget.active && widget.live) {
        widget.restartFast = false
        widget.start(true)
      } else {
        if (fastRun) widget.seconds = 0
        if (code !== 0 && code !== 143 && code !== 15) widget.failure = "Sensor sampling stopped"
      }
    }
  }
  Timer {
    interval: 2000
    repeat: true
    running: widget.active && !widget.live
    onTriggered: widget.refresh()
  }
  Timer {
    interval: 1000
    repeat: true
    running: widget.live && widget.active
    onTriggered: {
      widget.seconds = Math.max(0, Math.ceil((widget.until - Date.now()) / 1000))
      if (widget.seconds === 0) widget.stop()
    }
  }

  Column {
    anchors.fill: parent
    anchors.margins: Style.spacing.xl
    spacing: Style.spacing.sm
    Row {
      width: parent.width
      height: 40
      Text {
        width: parent.width - 40
        anchors.verticalCenter: parent.verticalCenter
        text: "Sensors"
        textFormat: Text.PlainText
        color: widget.fg
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }
      Rectangle {
        width: 40
        height: 40
        radius: 20
        color: Util.alpha(Commons.Color.accent, widget.live ? 0.30 : 0.10)
        Accessible.role: Accessible.Button
        Accessible.name: widget.live ? "Return to low power" : "Fast readings for 60 seconds"
        Accessible.onPressAction: widget.toggle()
        Text {
          anchors.centerIn: parent
          text: "󰓅"
          textFormat: Text.PlainText
          color: widget.live ? Commons.Color.accent : widget.fg
          font.family: Style.font.family
          font.pixelSize: Style.font.iconLarge
        }
        MouseArea { anchors.fill: parent; enabled: widget.active; onClicked: widget.toggle() }
      }
    }
    Repeater {
      model: widget.reading && widget.reading.rows ? widget.reading.rows
        : [{label: "Orientation", value: "—", state: "waiting"},
           {label: "Light", value: "—", state: "waiting"},
           {label: "Proximity", value: "—", state: "waiting"},
           {label: "Compass", value: "—", state: "waiting"}]
      delegate: Row {
        id: sensorRow
        required property var modelData
        width: parent.width
        height: Math.max(25, Style.font.body + 6)
        Text {
          width: parent.width * 0.40
          text: sensorRow.modelData.label
          textFormat: Text.PlainText
          color: widget.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Text {
          width: parent.width * 0.60
          text: !widget.live && sensorRow.modelData.label === "Compass" && widget.heading >= 0
            ? widget.heading + " °" : sensorRow.modelData.value
          textFormat: Text.PlainText
          horizontalAlignment: Text.AlignRight
          elide: Text.ElideRight
          color: sensorRow.modelData.state === "updated" ? Commons.Color.accent : widget.fg
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }
    }
    Compass {
      width: parent.width
      height: 150
      heading: widget.heading
      detailed: widget.live
      foreground: widget.fg
      dimForeground: widget.dim
      MouseArea { anchors.fill: parent; enabled: widget.active; onClicked: widget.toggle() }
    }
    Text {
      width: parent.width
      text: widget.failure || (widget.live ? "Fast · 5 Hz · " + widget.seconds + "s left"
        : !widget.active ? "Paused · last reported values"
        : "Low power · every 2s · 5° steps")
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: widget.failure ? Commons.Color.urgent : widget.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}

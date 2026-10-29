// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Commons as Commons

Item {
  id: compass
  property real heading: -1
  property bool detailed: false
  property color foreground: Commons.Color.menu.text
  property color dimForeground: Commons.Color.menu.text
  readonly property bool available: isFinite(heading) && heading >= 0
  readonly property real bearing: ((heading % 360) + 360) % 360
  readonly property string direction: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(bearing / 45) % 8]
  implicitHeight: 150

  Item {
    id: ring
    anchors.centerIn: parent
    width: Math.min(parent.width, parent.height) - 8
    height: width
    rotation: compass.available ? -compass.bearing : 0
    opacity: compass.available ? 1 : 0.35
    Repeater {
      model: compass.detailed ? 72 : 12
      delegate: Item {
        id: tick
        required property int index
        anchors.fill: parent
        rotation: index * (compass.detailed ? 5 : 30)
        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          y: 0
          width: 2
          height: tick.index % (compass.detailed ? 18 : 3) === 0 ? 12 : 5
          color: compass.dimForeground
        }
      }
    }
    Repeater {
      model: ["N", "E", "S", "W"]
      delegate: Item {
        id: cardinal
        required property int index
        required property string modelData
        anchors.fill: parent
        rotation: index * 90
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          y: 14
          text: cardinal.modelData
          textFormat: Text.PlainText
          color: cardinal.index === 0 ? Commons.Color.accent : compass.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          rotation: -parent.rotation - ring.rotation
        }
      }
    }
  }
  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    y: 0
    text: "▼"
    textFormat: Text.PlainText
    color: Commons.Color.accent
    font.pixelSize: 13
  }
  Column {
    anchors.centerIn: parent
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: compass.available ? (compass.detailed ? compass.bearing.toFixed(1) : String(Math.round(compass.bearing) % 360)) + "°" : "—"
      textFormat: Text.PlainText
      color: compass.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: compass.available ? compass.direction : "No heading"
      textFormat: Text.PlainText
      color: compass.dimForeground
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}

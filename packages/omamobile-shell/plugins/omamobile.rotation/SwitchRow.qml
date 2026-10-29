// SPDX-License-Identifier: MIT
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A full-width settings row with an optional glyph, a label, an optional
// detail line and a switch at the end, styled like the Wi-Fi panel's radio
// switch. The whole row is the touch target.
BorderSurface {
  id: row
  property string label: ""
  property string detail: ""
  property string glyph: ""
  // Degrees; orientation rows turn one phone glyph.
  property real glyphRotation: 0
  property bool checked: false
  property color foreground: Commons.Color.popups.text
  // An operation in flight: swallow taps.
  property bool busy: false
  signal tapped()

  width: parent ? parent.width : 0
  height: Math.max(56, Style.space(60))
  radius: Style.cornerRadius
  opacity: enabled ? 1 : 0.45
  color: rowTouch.pressed ? Style.pressedFillFor(row.foreground, Commons.Color.accent)
    : row.checked ? Util.alpha(Commons.Color.accent, Style.selectedFillAlpha)
    : Style.normalFillFor(row.foreground, Commons.Color.accent)
  borderSpec: Border.controlSpec(row.checked ? "selected" : "normal", row.foreground, Commons.Color.accent)

  Text {
    id: rowGlyph
    visible: row.glyph !== ""
    anchors.left: parent.left
    anchors.leftMargin: Style.spacing.xl + row.borderLeft
    anchors.verticalCenter: parent.verticalCenter
    width: visible ? Style.space(28) : 0
    textFormat: Text.PlainText
    text: row.glyph
    horizontalAlignment: Text.AlignHCenter
    rotation: row.glyphRotation
    color: row.checked ? Commons.Color.accent : row.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.iconLarge
  }

  Column {
    anchors.left: rowGlyph.visible ? rowGlyph.right : parent.left
    anchors.leftMargin: rowGlyph.visible ? Style.spacing.lg : Style.spacing.xxl + row.borderLeft
    anchors.right: rowSwitch.left
    anchors.rightMargin: Style.spacing.lg
    anchors.verticalCenter: parent.verticalCenter
    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: row.label
      color: row.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
      elide: Text.ElideRight
    }
    Text {
      width: parent.width
      visible: row.detail !== ""
      textFormat: Text.PlainText
      text: row.detail
      color: Qt.darker(row.foreground, 1.4)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }

  ToggleSwitch {
    id: rowSwitch
    anchors.right: parent.right
    anchors.rightMargin: Style.spacing.xl + row.borderRight
    anchors.verticalCenter: parent.verticalCenter
    checked: row.checked
    busy: row.busy
    interactive: false
    foreground: row.foreground
  }

  MouseArea {
    id: rowTouch
    anchors.fill: parent
    enabled: row.enabled && !row.busy
    cursorShape: Qt.PointingHandCursor
    onClicked: row.tapped()
  }
}

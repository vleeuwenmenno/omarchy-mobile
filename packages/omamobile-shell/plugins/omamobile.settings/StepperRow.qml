// SPDX-License-Identifier: MIT
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../omamobile.quicksettings" as QuickSettings

// A number with minus and plus at the end, as Rotation's "Show for" row. The
// buttons stop at the limits; the owner decides the step.
BorderSurface {
  id: row
  property string label: ""
  property string detail: ""
  property string value: ""
  property bool canDecrement: true
  property bool canIncrement: true
  property color foreground: Commons.Color.popups.text
  signal decrement()
  signal increment()

  width: parent ? parent.width : 0
  height: Math.max(64, Style.space(68))
  radius: Style.cornerRadius
  opacity: enabled ? 1 : 0.45
  color: Style.normalFillFor(row.foreground, Commons.Color.accent)
  borderSpec: Border.controlSpec("normal", row.foreground, Commons.Color.accent)

  Column {
    anchors.left: parent.left
    anchors.leftMargin: Style.spacing.xxl + row.borderLeft
    anchors.right: minus.left
    anchors.rightMargin: Style.spacing.sm
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

  QuickSettings.GlyphButton {
    id: minus
    anchors.right: amount.left
    anchors.verticalCenter: parent.verticalCenter
    glyph: String.fromCodePoint(0xF0374)
    foreground: row.foreground
    enabled: row.enabled && row.canDecrement
    onTapped: row.decrement()
  }

  Text {
    id: amount
    anchors.right: plus.left
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(52)
    horizontalAlignment: Text.AlignHCenter
    textFormat: Text.PlainText
    text: row.value
    color: row.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
  }

  QuickSettings.GlyphButton {
    id: plus
    anchors.right: parent.right
    anchors.rightMargin: Style.spacing.sm + row.borderRight
    anchors.verticalCenter: parent.verticalCenter
    glyph: String.fromCodePoint(0xF0415)
    foreground: row.foreground
    enabled: row.enabled && row.canIncrement
    onTapped: row.increment()
  }
}

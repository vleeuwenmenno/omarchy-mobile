// SPDX-License-Identifier: MIT
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A read-only row: a label and its value.
BorderSurface {
  id: row
  property string label: ""
  property string value: ""
  property color foreground: Commons.Color.popups.text

  width: parent ? parent.width : 0
  height: Math.max(48, Style.space(52))
  radius: Style.cornerRadius
  color: Style.normalFillFor(row.foreground, Commons.Color.accent)
  borderSpec: Border.controlSpec("normal", row.foreground, Commons.Color.accent)

  Text {
    id: name
    anchors.left: parent.left
    anchors.leftMargin: Style.spacing.xxl + row.borderLeft
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: row.label
    color: row.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
    font.bold: true
  }

  Text {
    anchors.left: name.right
    anchors.leftMargin: Style.spacing.lg
    anchors.right: parent.right
    anchors.rightMargin: Style.spacing.xxl + row.borderRight
    anchors.verticalCenter: parent.verticalCenter
    horizontalAlignment: Text.AlignRight
    textFormat: Text.PlainText
    text: row.value
    color: Qt.darker(row.foreground, 1.4)
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    elide: Text.ElideLeft
  }
}

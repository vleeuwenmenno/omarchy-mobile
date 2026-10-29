// SPDX-License-Identifier: MIT
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A full-width settings row that opens something: a glyph, a label, a detail
// line and a chevron. The whole row is the touch target.
BorderSurface {
  id: row
  property string label: ""
  property string detail: ""
  property string glyph: ""
  property bool chevron: true
  property color foreground: Commons.Color.popups.text
  signal tapped()

  width: parent ? parent.width : 0
  height: Math.max(56, Style.space(60))
  radius: Style.cornerRadius
  opacity: enabled ? 1 : 0.45
  color: touch.pressed ? Style.pressedFillFor(row.foreground, Commons.Color.accent)
    : Style.normalFillFor(row.foreground, Commons.Color.accent)
  borderSpec: Border.controlSpec("normal", row.foreground, Commons.Color.accent)

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
    color: Commons.Color.accent
    font.family: Style.font.family
    font.pixelSize: Style.font.iconLarge
  }

  Column {
    anchors.left: rowGlyph.visible ? rowGlyph.right : parent.left
    anchors.leftMargin: rowGlyph.visible ? Style.spacing.lg : Style.spacing.xxl + row.borderLeft
    anchors.right: rowChevron.left
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

  Text {
    id: rowChevron
    visible: row.chevron
    anchors.right: parent.right
    anchors.rightMargin: Style.spacing.xl + row.borderRight
    anchors.verticalCenter: parent.verticalCenter
    width: visible ? Style.space(20) : 0
    textFormat: Text.PlainText
    text: String.fromCodePoint(0xF0142)
    horizontalAlignment: Text.AlignHCenter
    color: Qt.darker(row.foreground, 1.4)
    font.family: Style.font.family
    font.pixelSize: Style.font.iconLarge
  }

  MouseArea {
    id: touch
    anchors.fill: parent
    enabled: row.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: row.tapped()
  }
}

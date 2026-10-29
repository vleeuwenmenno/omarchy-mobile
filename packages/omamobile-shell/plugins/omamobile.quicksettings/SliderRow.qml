// SPDX-License-Identifier: MIT
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A full-width slider row for the quick settings sheet: a 44px tappable glyph
// (mute for volume), Omarchy's PanelSlider stretched to a thumb-sized hit area,
// and the value as a percentage.
Item {
  id: root

  property string icon: ""
  property real value: 0
  readonly property bool dragging: slider.dragging
  // Opt-in high-value zone; volume and torch retain their normal colors.
  property real warningThreshold: -1
  property color warningColor: "#ef4444"
  readonly property bool warningEnabled: warningThreshold >= 0 && warningThreshold < 1
  readonly property bool warningActive: warningEnabled && slider.liveValue > warningThreshold
  property bool available: true
  property string unavailableText: ""
  property color foreground: Commons.Color.popups.text
  // Draw the glyph as a selected toggle (brightness's Auto mode).
  property bool iconSelected: false
  property bool iconEnabled: available

  signal moved(real value)
  signal released(real value)
  signal iconClicked()

  readonly property int touchSize: Math.max(44, Style.space(44))

  implicitHeight: touchSize
  opacity: available ? 1 : 0.45

  Item {
    id: iconButton
    width: root.touchSize
    height: root.touchSize
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter

    BorderSurface {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: iconTouch.pressed ? Style.pressedFillFor(root.foreground, Commons.Color.accent)
        : root.iconSelected ? Util.alpha(Commons.Color.accent, Style.selectedFillAlpha) : "transparent"
      borderSpec: root.iconSelected ? Border.controlSpec("selected", root.foreground, Commons.Color.accent) : Border.none()
    }

    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: root.icon
      color: root.iconSelected ? Commons.Color.accent : root.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.display
    }

    MouseArea {
      id: iconTouch
      anchors.fill: parent
      enabled: root.iconEnabled
      onClicked: root.iconClicked()
    }
  }

  // Draw the segmented track behind PanelSlider, leaving its thumb and
  // pointer handling above it. Only the portion beyond the threshold is red.
  Item {
    visible: root.available && root.warningEnabled
    x: slider.x
    y: slider.y + (slider.height - slider.trackHeight) / 2
    width: slider.width
    height: slider.trackHeight

    Rectangle {
      anchors.fill: parent
      radius: height / 2
      color: Style.selectedFillFor(root.foreground, Commons.Color.accent)
    }
    Rectangle {
      x: parent.width * root.warningThreshold
      width: parent.width * (1 - root.warningThreshold)
      height: parent.height
      radius: height / 2
      color: root.warningColor
      opacity: 0.35
    }
    Rectangle {
      width: parent.width * Math.min(slider.progress, root.warningThreshold)
      height: parent.height
      radius: height / 2
      color: Commons.Color.accent
    }
    Rectangle {
      x: parent.width * root.warningThreshold
      width: parent.width * Math.max(0, slider.progress - root.warningThreshold)
      height: parent.height
      radius: height / 2
      color: root.warningColor
    }
  }

  PanelSlider {
    id: slider
    visible: root.available
    anchors.left: iconButton.right
    anchors.leftMargin: Style.spacing.lg
    anchors.right: valueText.left
    anchors.rightMargin: Style.spacing.lg
    anchors.verticalCenter: parent.verticalCenter
    height: root.touchSize
    value: root.value
    minimum: 0
    maximum: 1
    step: 0.05
    trackHeight: Math.max(6, Style.space(6))
    knobSize: Math.max(22, Style.space(22))
    trackColor: root.warningEnabled ? "transparent" : Style.selectedFillFor(root.foreground, Commons.Color.accent)
    fillColor: root.warningEnabled ? "transparent" : Commons.Color.accent
    knobColor: root.warningActive ? root.warningColor : root.foreground
    tickColor: Commons.Color.popups.background
    onMoved: function(value) { root.moved(value) }
    onReleased: function(value) { root.released(value) }
  }

  Text {
    visible: !root.available
    anchors.left: iconButton.right
    anchors.leftMargin: Style.spacing.lg
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: root.unavailableText
    color: Qt.darker(root.foreground, 1.4)
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Text {
    id: valueText
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    width: root.available ? Style.space(40) : 0
    horizontalAlignment: Text.AlignRight
    textFormat: Text.PlainText
    text: root.available ? Math.round(slider.liveValue * 100) + "%" : ""
    color: root.warningActive ? root.warningColor : root.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
}

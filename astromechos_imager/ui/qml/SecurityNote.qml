// SecurityNote.qml — compact "⚠ Security note" interactive link.
//
// Reusable component dropped next to a section title (Step 4 Customize):
//   * Inline amber ⚠ glyph + "Security note" label
//   * Subtle opacity breathing at rest (pauses on hover / popup open)
//   * Click → floating Popup with the full warning text
//   * Theme-aware amber: darker orange on Light (WCAG AA on white surface),
//     warm yellow on Dark (WCAG AA on dark surface)
//   * Zero layout impact on the parent — the popup floats above the
//     Flickable and never participates in card sizing.
//
// Usage:
//   SecurityNote {
//       warningTitle: "SECURITY NOTE"
//       warningText:  "Your message…"
//   }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: root

    property string warningText: ""
    property string warningTitle: "SECURITY NOTE"
    // Popup horizontal offset relative to this Item's origin. Negative
    // pulls the popup left so its right edge stays near the icon when
    // the icon sits near the right side of a wider parent.
    property int popupOffsetX: -260

    visible: warningText !== ""
    implicitWidth:  row.implicitWidth
    implicitHeight: row.implicitHeight

    // ── Theme-aware amber palette (WCAG AA against respective surfaces) ──
    // Light surface ≈ #ffffff → needs a darker burnt-orange.
    // Dark surface  ≈ #1a1f24 → needs a warmer mid-yellow.
    readonly property color _amberRest:
        theme.mode === "light" ? "#b8521a" : "#f0b840"
    readonly property color _amberHover:
        theme.mode === "light" ? "#e0671f" : "#ffd070"
    readonly property color _amberHalo:
        theme.mode === "light"
            ? Qt.rgba(0.72, 0.32, 0.10, 0.20)
            : Qt.rgba(0.94, 0.72, 0.25, 0.25)
    readonly property color _amberCurrent:
        hoverArea.containsMouse || popup.opened ? _amberHover : _amberRest

    // Subtle opacity breathing — pauses on hover / open to avoid
    // competing with what the operator is reading.
    SequentialAnimation on opacity {
        running: !popup.opened && !hoverArea.containsMouse
        loops: Animation.Infinite
        NumberAnimation { to: 0.60; duration: 1100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.00; duration: 1100; easing.type: Easing.InOutSine }
    }

    RowLayout {
        id: row
        spacing: 5
        Text {
            text: "⚠"
            color: root._amberCurrent
            font.family: Theme.fontTitle
            font.pixelSize: 13
            font.bold: true
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
        Text {
            text: "Security note"
            color: root._amberCurrent
            font.family: Theme.fontSubtitle
            font.pixelSize: 10
            font.letterSpacing: 0.8
            font.underline: hoverArea.containsMouse
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
    }

    MouseArea {
        id: hoverArea
        anchors.fill: parent
        anchors.margins: -4   // bigger hit target than the visible glyph
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.opened ? popup.close() : popup.open()
    }

    // Floating popup — anchors below the icon. Does NOT push the
    // parent card's height; closes on outside click / Escape.
    Popup {
        id: popup
        x: root.popupOffsetX
        y: root.height + 6
        width: 360
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent | Popup.CloseOnPressOutside

        background: Rectangle {
            color: theme.colors.colorSurface
            border.color: root._amberRest
            border.width: 1
            radius: Theme.radiusButton
            // Outer halo
            Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                color: "transparent"
                border.color: root._amberHalo
                border.width: 1
                radius: parent.radius + 2
                z: -1
            }
        }

        contentItem: RowLayout {
            spacing: 10
            Text {
                Layout.alignment: Qt.AlignTop
                Layout.leftMargin: 12
                Layout.topMargin: 12
                text: "⚠"
                color: root._amberRest
                font.family: Theme.fontTitle
                font.pixelSize: 22
                font.bold: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 10
                Layout.bottomMargin: 12
                Layout.rightMargin: 12
                spacing: 4
                Text {
                    text: root.warningTitle
                    color: root._amberRest
                    font.family: Theme.fontTitle
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                Text {
                    Layout.fillWidth: true
                    text: root.warningText
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontBody
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    lineHeight: 1.25
                }
            }
        }

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durBase }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.durFast }
        }
    }
}

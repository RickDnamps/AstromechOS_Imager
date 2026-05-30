// Frameless window control button (— □ × + theme toggle).
// Hover-tinted; close variant flashes red on hover.
import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Item {
    id: btn
    width: 44
    height: 36

    property string glyph: ""
    property bool   closeStyle: false
    // Audit High #25: accessible name + tooltip text — both default to the
    // glyph so the wrapper "just works" but callers (main.qml) should
    // override with a human-readable label.
    property string tooltipText: glyph
    property string accessibleName: tooltipText
    signal activated()

    // Buttons live in the dark chrome (header) in both modes, so the hover
    // tint and glyph color use the chrome-context tokens — not the theme
    // palette, which would flip to dark-on-dark in Light mode.
    Rectangle {
        anchors.fill: parent
        color: hover.containsMouse || btn.activeFocus
            ? (btn.closeStyle ? theme.colors.colorBorderError
                              : Qt.rgba(1, 1, 1, 0.08))   // subtle white tint on dark chrome
            : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.durFast } }

        // Focus-visible ring — keyboard-only operators need to see where
        // they are. Drawn inside the button so it doesn't bleed into the
        // adjacent control.
        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            color: "transparent"
            border.color: theme.colors.colorAccentBright
            border.width: 1
            visible: btn.activeFocus
        }
    }

    Text {
        anchors.centerIn: parent
        text: btn.glyph
        color: hover.containsMouse
            ? theme.colors.colorTextOnChrome
            : theme.colors.colorTextOnChromeDim
        font.family: Theme.fontSubtitle
        font.pixelSize: 14
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    // Hover tooltip — built-in Qt Quick Controls 2 popup.
    ToolTip.visible: hover.containsMouse && btn.tooltipText.length > 0
    ToolTip.text: btn.tooltipText
    ToolTip.delay: 500

    Accessible.role: Accessible.Button
    Accessible.name: btn.accessibleName
    Accessible.onPressAction: btn.activated()

    // Keyboard activation.
    activeFocusOnTab: true
    Keys.onSpacePressed:  { event.accepted = true; btn.activated() }
    Keys.onReturnPressed: { event.accepted = true; btn.activated() }
    Keys.onEnterPressed:  { event.accepted = true; btn.activated() }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.activated()
    }
}

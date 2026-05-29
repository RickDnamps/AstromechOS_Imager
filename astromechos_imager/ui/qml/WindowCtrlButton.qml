// Frameless window control button (— □ ×).
// Hover-tinted; close variant flashes red on hover.
import QtQuick
import "Theme.js" as Theme

Item {
    id: btn
    width: 44
    height: 36

    property string glyph: ""
    property bool   closeStyle: false
    signal activated()

    // Buttons live in the dark chrome (header) in both modes, so the hover
    // tint and glyph color use the chrome-context tokens — not the theme
    // palette, which would flip to dark-on-dark in Light mode.
    Rectangle {
        anchors.fill: parent
        color: hover.containsMouse
            ? (btn.closeStyle ? theme.colors.colorBorderError
                              : Qt.rgba(1, 1, 1, 0.08))   // subtle white tint on dark chrome
            : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    Text {
        anchors.centerIn: parent
        text: btn.glyph
        color: (hover.containsMouse && btn.closeStyle)
            ? theme.colors.colorTextOnChrome
            : (hover.containsMouse
                ? theme.colors.colorTextOnChrome
                : theme.colors.colorTextOnChromeDim)
        font.family: Theme.fontSubtitle
        font.pixelSize: 14
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.activated()
    }
}

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

    Rectangle {
        anchors.fill: parent
        color: hover.containsMouse
            ? (btn.closeStyle ? theme.colors.colorBorderError : theme.colors.colorSurface2)
            : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    Text {
        anchors.centerIn: parent
        text: btn.glyph
        color: (hover.containsMouse && btn.closeStyle)
            ? theme.colors.colorTextPrimary
            : theme.colors.colorTextSecondary
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

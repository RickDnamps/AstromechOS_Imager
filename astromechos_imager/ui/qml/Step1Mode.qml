import QtQuick
import QtQuick.Controls

Rectangle {
    color: "#1a1f24"
    anchors.fill: parent

    Text {
        anchors.centerIn: parent
        text: "Step 1 — Mode"
        color: "#e6e6e6"
        font.pixelSize: 24
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button {
            text: "Next"
            onClicked: wizardState.next()
        }
    }
}

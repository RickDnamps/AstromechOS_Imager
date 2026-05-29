import QtQuick
import QtQuick.Controls

Rectangle {
    // Root sized by StackView — do NOT set anchors.fill here.
    color: "#1a1f24"

    Text {
        anchors.centerIn: parent
        text: "Step 6 — Done"
        color: "#e6e6e6"
        font.pixelSize: 24
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button {
            text: "Back"
            onClicked: wizardState.back()
        }
        Button {
            text: "Quit"
            onClicked: Qt.quit()
        }
    }
}

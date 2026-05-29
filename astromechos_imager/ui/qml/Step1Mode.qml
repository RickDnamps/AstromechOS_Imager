import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    color: "#1a1f24"
    anchors.fill: parent

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 16
        width: 420

        Text {
            text: "What do you want to flash?"
            color: "#e6e6e6"
            font.pixelSize: 22
            Layout.bottomMargin: 12
        }

        // Card-style radio buttons for AstromechOS flash mode selection
        Repeater {
            model: [
                { mode: "both",         title: "Flash both (recommended)",
                  desc: "Master + Slave SD cards in one session" },
                { mode: "master_only",  title: "Master only",
                  desc: "Re-flash the master SD card" },
                { mode: "slave_only",   title: "Slave only",
                  desc: "Re-flash the slave SD card" },
            ]
            delegate: Rectangle {
                Layout.fillWidth: true
                height: 64
                radius: 8
                color: wizardState.mode === modelData.mode ? "#2d4a6e" : "#262b30"
                border.color: wizardState.mode === modelData.mode ? "#5e9bd6" : "#3a3f44"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 2
                    Text { text: modelData.title; color: "#e6e6e6"; font.pixelSize: 16; font.bold: true }
                    Text { text: modelData.desc;  color: "#a0a4a8"; font.pixelSize: 12 }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: wizardState.setMode(modelData.mode)
                }
            }
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        Button { text: "Next"; onClicked: wizardState.next() }
    }
}

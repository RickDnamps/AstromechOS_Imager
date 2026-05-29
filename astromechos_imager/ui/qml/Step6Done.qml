import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    color: "#1a1f24"

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        anchors.bottomMargin: 80
        spacing: 16

        Text {
            text: "✓ Done"
            color: "#5ec07a"
            font.pixelSize: 28
            font.bold: true
        }

        Text {
            text: "Your AstromechOS SD card" + (needMaster && needSlave ? "s have" : " has") + " been flashed."
            color: "#e6e6e6"
            font.pixelSize: 15
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            color: "#262b30"
            border.color: "#3a3f44"
            border.width: 1
            radius: 6

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8

                Text { text: "Next steps"; color: "#a0c4e8"; font.pixelSize: 14; font.bold: true }
                Text { text: "1. Eject both SDs (auto-eject already attempted)";    color: "#cfd2d5"; font.pixelSize: 12 }
                Text { text: "2. Insert each card into its Pi 4B (Master ↔ dome, Slave ↔ body)"; color: "#cfd2d5"; font.pixelSize: 12 }
                Text { text: "3. First boot takes ~3 min and reboots automatically"; color: "#cfd2d5"; font.pixelSize: 12 }
                Text { text: "4. SSH via astromech-master.local / astromech-slave.local"; color: "#cfd2d5"; font.pixelSize: 12 }
            }
        }

        Item { Layout.fillHeight: true }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button {
            text: "Flash another"
            onClicked: { wizardState.goto(1); }
        }
        Button {
            text: "Quit"
            onClicked: Qt.quit()
        }
    }
}

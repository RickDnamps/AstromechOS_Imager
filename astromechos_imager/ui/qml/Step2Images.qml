import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.platform 1.1

Rectangle {
    color: "#1a1f24"
    anchors.fill: parent

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    FileDialog {
        id: masterDialog
        title: "Select master image"
        nameFilters: ["Pi OS images (*.img *.xz *.gz *.zip)", "All files (*)"]
        onAccepted: wizardState.setMasterImagePath(file.toString())
    }
    FileDialog {
        id: slaveDialog
        title: "Select slave image"
        nameFilters: ["Pi OS images (*.img *.xz *.gz *.zip)", "All files (*)"]
        onAccepted: wizardState.setSlaveImagePath(file.toString())
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 24
        width: 540

        Text {
            text: "Select source images"
            color: "#e6e6e6"
            font.pixelSize: 22
            Layout.bottomMargin: 8
        }

        // Master row
        Rectangle {
            visible: needMaster
            Layout.fillWidth: true
            height: 80
            radius: 8
            color: "#262b30"
            border.color: wizardState.masterImagePath ? "#5e9bd6" : "#3a3f44"
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Master image"; color: "#e6e6e6"; font.pixelSize: 14; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Button { text: "Browse..."; onClicked: masterDialog.open() }
                }
                Text {
                    text: wizardState.masterImagePath || "(no image selected)"
                    color: wizardState.masterImagePath ? "#a0c4e8" : "#7a8086"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
            }
        }

        // Slave row — same shape, swap "master" -> "slave"
        Rectangle {
            visible: needSlave
            Layout.fillWidth: true
            height: 80
            radius: 8
            color: "#262b30"
            border.color: wizardState.slaveImagePath ? "#5e9bd6" : "#3a3f44"
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Slave image"; color: "#e6e6e6"; font.pixelSize: 14; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Button { text: "Browse..."; onClicked: slaveDialog.open() }
                }
                Text {
                    text: wizardState.slaveImagePath || "(no image selected)"
                    color: wizardState.slaveImagePath ? "#a0c4e8" : "#7a8086"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
            }
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button { text: "Back"; onClicked: wizardState.back() }
        Button {
            text: "Next"
            enabled: (!needMaster || wizardState.masterImagePath !== "")
                  && (!needSlave  || wizardState.slaveImagePath  !== "")
            onClicked: wizardState.next()
        }
    }
}

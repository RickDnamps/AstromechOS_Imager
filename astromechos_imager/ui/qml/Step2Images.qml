import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.platform 1.1
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

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
        spacing: 22
        width: 580

        Text {
            text: "SELECT SOURCE IMAGES"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
            Layout.bottomMargin: 4
        }
        Text {
            text: "Locate the .img / .img.xz / .img.gz files you extracted from each Pi 4B."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 4
        }

        // Master row
        Rectangle {
            visible: needMaster
            Layout.fillWidth: true
            height: 92
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: wizardState.masterImagePath ? theme.colors.colorBorderAccent : theme.colors.colorBorderIdle
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            // Top highlight (glass)
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        text: "MASTER IMAGE"
                        color: theme.colors.colorTextPrimary
                        font.family: Theme.fontTitle
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.4
                    }
                    Item { Layout.fillWidth: true }
                    AstroButton {
                        text: "BROWSE"
                        variant: "secondary"
                        onClicked: masterDialog.open()
                    }
                }
                Text {
                    text: wizardState.masterImagePath || "— no image selected —"
                    color: wizardState.masterImagePath ? theme.colors.colorTextAccent : theme.colors.colorTextTertiary
                    font.family: Theme.fontMono
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                }
            }
        }

        // Slave row
        Rectangle {
            visible: needSlave
            Layout.fillWidth: true
            height: 92
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: wizardState.slaveImagePath ? theme.colors.colorBorderAccent : theme.colors.colorBorderIdle
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        text: "SLAVE IMAGE"
                        color: theme.colors.colorTextPrimary
                        font.family: Theme.fontTitle
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.4
                    }
                    Item { Layout.fillWidth: true }
                    AstroButton {
                        text: "BROWSE"
                        variant: "secondary"
                        onClicked: slaveDialog.open()
                    }
                }
                Text {
                    text: wizardState.slaveImagePath || "— no image selected —"
                    color: wizardState.slaveImagePath ? theme.colors.colorTextAccent : theme.colors.colorTextTertiary
                    font.family: Theme.fontMono
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                }
            }
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton { text: "← BACK"; variant: "secondary"; onClicked: wizardState.back() }
        AstroButton {
            text: "NEXT →"
            variant: "primary"
            enabled: (!needMaster || wizardState.masterImagePath !== "")
                  && (!needSlave  || wizardState.slaveImagePath  !== "")
            onClicked: wizardState.next()
        }
    }
}

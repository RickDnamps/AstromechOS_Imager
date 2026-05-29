import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    // Root sized by StackView — do NOT set anchors.fill here.
    color: "#1a1f24"

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        anchors.bottomMargin: 80
        spacing: 12

        Text {
            text: "Select target SD cards"
            color: "#e6e6e6"
            font.pixelSize: 22
        }
        Text {
            // System drive is excluded at the enumerate_removable_drives() layer
            // (platform/windows.py Phase 4.2) — it never appears in this list.
            text: "Removable drives only — system drive is hidden for safety."
            color: "#a0a4a8"
            font.pixelSize: 12
            Layout.bottomMargin: 8
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#262b30"
            border.color: "#3a3f44"
            border.width: 1
            radius: 6

            ListView {
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                // driveListModel is injected on Windows by build_app(); absent in non-Windows envs
                model: typeof driveListModel !== "undefined" ? driveListModel : null
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 48
                    color: "transparent"
                    Row {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 12

                        Text {
                            text: driveLetters !== "" ? driveLetters : "—"
                            color: "#e6e6e6"
                            font.pixelSize: 14
                            width: 60
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: model.model + " · " + sizeHuman
                            color: "#cfd2d5"
                            font.pixelSize: 13
                            width: 280
                            elide: Text.ElideRight
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Item { width: parent.width - 60 - 280 - 200 - 36; height: 1 }
                        Button {
                            text: wizardState.masterDriveId === physicalDriveId ? "✓ Master" : "Master"
                            enabled: needMaster && wizardState.slaveDriveId !== physicalDriveId
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: wizardState.setMasterDriveId(physicalDriveId)
                        }
                        Button {
                            text: wizardState.slaveDriveId === physicalDriveId ? "✓ Slave" : "Slave"
                            enabled: needSlave && wizardState.masterDriveId !== physicalDriveId
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: wizardState.setSlaveDriveId(physicalDriveId)
                        }
                    }
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
            enabled: (!needMaster || wizardState.masterDriveId !== -1)
                  && (!needSlave  || wizardState.slaveDriveId  !== -1)
            onClicked: wizardState.next()
        }
    }
}

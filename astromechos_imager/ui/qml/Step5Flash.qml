import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    // Root sized by StackView — no anchors.fill here
    color: "#1a1f24"

    property bool isFlashing: flashViewModel.status === "flashing"
    property bool isDone:     flashViewModel.status === "done"
    property bool isError:    flashViewModel.status === "error"

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        anchors.bottomMargin: 80
        spacing: 16

        Text {
            text: isFlashing ? "Flashing — do not unplug" : "Confirm and flash"
            color: "#e6e6e6"
            font.pixelSize: 22
        }

        // ── Summary table (Phase A) ──────────────────────────────────
        Rectangle {
            visible: !isFlashing && !isDone
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            color: "#262b30"
            border.color: "#3a3f44"
            border.width: 1
            radius: 6

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                Text {
                    visible: needMaster
                    text: "Master:  " + wizardState.masterImagePath + "  →  drive " + wizardState.masterDriveId
                    color: "#cfd2d5"
                    font.pixelSize: 13
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
                Text {
                    visible: needSlave
                    text: "Slave:   " + wizardState.slaveImagePath  + "  →  drive " + wizardState.slaveDriveId
                    color: "#cfd2d5"
                    font.pixelSize: 13
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
                Item { Layout.fillHeight: true }

                Text {
                    text: "All data on the target drive(s) will be ERASED."
                    color: "#e8a05e"
                    font.pixelSize: 13
                    font.bold: true
                }
            }
        }

        // ── Progress (Phase B) ───────────────────────────────────────
        ColumnLayout {
            visible: isFlashing || isDone || isError
            Layout.fillWidth: true
            spacing: 12

            ColumnLayout {
                visible: needMaster
                Layout.fillWidth: true
                spacing: 4
                Text { text: "Master · " + flashViewModel.masterPhase; color: "#cfd2d5"; font.pixelSize: 12 }
                ProgressBar { Layout.fillWidth: true; value: flashViewModel.masterProgress; from: 0; to: 1 }
            }
            ColumnLayout {
                visible: needSlave
                Layout.fillWidth: true
                spacing: 4
                Text { text: "Slave · " + flashViewModel.slavePhase; color: "#cfd2d5"; font.pixelSize: 12 }
                ProgressBar { Layout.fillWidth: true; value: flashViewModel.slaveProgress; from: 0; to: 1 }
            }

            Text {
                visible: isDone
                text: "✓ Flash complete"
                color: "#5ec07a"
                font.pixelSize: 14
                font.bold: true
            }
            Text {
                visible: isError
                text: "✗ " + flashViewModel.errorMessage
                color: "#e85a5a"
                font.pixelSize: 13
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
    }

    // ── Action bar ───────────────────────────────────────────────────
    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button {
            visible: !isFlashing && !isDone
            text: "Back"
            onClicked: wizardState.back()
        }
        Button {
            visible: !isFlashing && !isDone && !isError
            text: "WRITE"
            background: Rectangle { color: "#a02828"; radius: 4 }
            contentItem: Text {
                text: "WRITE"
                color: "#ffffff"
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: confirmDialog.open()
        }
        Button {
            visible: isFlashing
            text: "Cancel"
            onClicked: flashViewModel.cancel()
        }
        Button {
            visible: isDone
            text: "Next"
            onClicked: wizardState.next()
        }
    }

    Dialog {
        id: confirmDialog
        title: "Erase target drive(s)?"
        modal: true
        standardButtons: Dialog.Yes | Dialog.Cancel
        onAccepted: flashViewModel.startFromWizard()
        contentItem: Text {
            text: "This will ERASE the target SD card(s). Are you sure?"
            color: "#e6e6e6"
            wrapMode: Text.Wrap
        }
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

    property bool isFlashing: flashViewModel.status === "flashing"
    property bool isDone:     flashViewModel.status === "done"
    property bool isError:    flashViewModel.status === "error"

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        spacing: 18

        // ── Header ────────────────────────────────────────────────────
        ColumnLayout {
            spacing: 4
            Text {
                text: isFlashing ? "FLASHING — DO NOT UNPLUG"
                    : isError    ? "FLASH FAILED"
                    : isDone     ? "FLASH COMPLETE"
                    :              "CONFIRM AND FLASH"
                color: isError    ? theme.colors.colorBorderError
                     : isDone     ? theme.colors.colorAccent
                     :              theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 18
                font.bold: true
                font.letterSpacing: 1.4
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
            Text {
                text: isFlashing ? "Bit-for-bit copy in progress. The Pi will boot from this card."
                    : isError    ? "Review the message below, fix the cause, then retry."
                    : isDone     ? "Eject the card(s) and insert into the Pi 4B."
                    :              "Review the plan below. Writing will erase the targets."
                color: theme.colors.colorTextSecondary
                font.family: Theme.fontBody
                font.pixelSize: 12
            }
        }

        // ── Summary panel (pre-flash) ─────────────────────────────────
        Rectangle {
            visible: !isFlashing && !isDone
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1

            // Top edge highlight
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                Repeater {
                    model: [
                        { vis: needMaster, role: "MASTER", img: wizardState.masterImagePath, drv: wizardState.masterDriveId },
                        { vis: needSlave,  role: "SLAVE",  img: wizardState.slaveImagePath,  drv: wizardState.slaveDriveId  },
                    ]
                    delegate: RowLayout {
                        visible: modelData.vis
                        Layout.fillWidth: true
                        spacing: 12
                        Text {
                            text: modelData.role
                            color: theme.colors.colorTextAccent
                            font.family: Theme.fontTitle
                            font.pixelSize: 10
                            font.bold: true
                            font.letterSpacing: 1.6
                            Layout.preferredWidth: 70
                        }
                        Text {
                            text: modelData.img
                            color: theme.colors.colorTextPrimary
                            font.family: Theme.fontMono
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        Text {
                            text: "→ drive " + modelData.drv
                            color: theme.colors.colorTextSecondary
                            font.family: Theme.fontMono
                            font.pixelSize: 12
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // Hairline warning bar
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: theme.colors.colorBorderWarn
                    opacity: 0.4
                }
                RowLayout {
                    spacing: 8
                    Text {
                        text: "⚠"
                        color: theme.colors.colorBorderWarn
                        font.family: Theme.fontTitle
                        font.pixelSize: 14
                    }
                    Text {
                        text: "ALL DATA ON THE TARGET DRIVE(S) WILL BE ERASED."
                        color: theme.colors.colorBorderWarn
                        font.family: Theme.fontTitle
                        font.pixelSize: 11
                        font.bold: true
                        font.letterSpacing: 1.4
                    }
                }
            }
        }

        // ── Progress panel (during / after flash) ─────────────────────
        Rectangle {
            visible: isFlashing || isDone || isError
            Layout.fillWidth: true
            Layout.preferredHeight: 200
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: isError ? theme.colors.colorBorderError : theme.colors.colorBorderIdle
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14

                // Master progress
                ColumnLayout {
                    visible: needMaster
                    Layout.fillWidth: true
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "MASTER"
                            color: theme.colors.colorTextAccent
                            font.family: Theme.fontTitle
                            font.pixelSize: 10
                            font.bold: true
                            font.letterSpacing: 1.6
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: flashViewModel.masterPhase
                            color: theme.colors.colorTextSecondary
                            font.family: Theme.fontMono
                            font.pixelSize: 11
                        }
                    }
                    // Themed progress bar
                    Rectangle {
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: theme.colors.colorBg
                        border.color: theme.colors.colorBorderIdle
                        border.width: 1
                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.margins: 1
                            width: Math.max(0, (parent.width - 2) * Math.min(1.0, flashViewModel.masterProgress))
                            radius: 2
                            color: theme.colors.colorAccent
                            Behavior on width { NumberAnimation { duration: 120 } }
                        }
                    }
                }
                // Slave progress
                ColumnLayout {
                    visible: needSlave
                    Layout.fillWidth: true
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "SLAVE"
                            color: theme.colors.colorTextAccent
                            font.family: Theme.fontTitle
                            font.pixelSize: 10
                            font.bold: true
                            font.letterSpacing: 1.6
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: flashViewModel.slavePhase
                            color: theme.colors.colorTextSecondary
                            font.family: Theme.fontMono
                            font.pixelSize: 11
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: theme.colors.colorBg
                        border.color: theme.colors.colorBorderIdle
                        border.width: 1
                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.margins: 1
                            width: Math.max(0, (parent.width - 2) * Math.min(1.0, flashViewModel.slaveProgress))
                            radius: 2
                            color: theme.colors.colorAccent
                            Behavior on width { NumberAnimation { duration: 120 } }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Text {
                    visible: isDone
                    text: "✓ FLASH COMPLETE"
                    color: theme.colors.colorAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 1.6
                }
                Text {
                    visible: isError
                    text: "✗ " + flashViewModel.errorMessage
                    color: theme.colors.colorBorderError
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    // ── Action bar ───────────────────────────────────────────────────
    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton {
            visible: !isFlashing && !isDone
            text: "← BACK"
            variant: "secondary"
            onClicked: wizardState.back()
        }
        AstroButton {
            visible: !isFlashing && !isDone && !isError
            text: "⚡ WRITE"
            variant: "danger"
            horizontalPadding: 28
            onClicked: confirmDialog.open()
        }
        AstroButton {
            visible: isFlashing
            text: "CANCEL"
            variant: "secondary"
            onClicked: flashViewModel.cancel()
        }
        AstroButton {
            visible: isDone
            text: "NEXT →"
            variant: "primary"
            onClicked: wizardState.next()
        }
    }

    // ── Themed confirmation dialog ───────────────────────────────────
    // Fixed width avoids the implicitWidth binding loop that Qt's Basic
    // Dialog hits when content wrapMode depends on width.
    Dialog {
        id: confirmDialog
        modal: true
        anchors.centerIn: parent
        width: 480
        padding: 0

        background: Rectangle {
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderError
            border.width: 1
        }

        header: Rectangle {
            color: "transparent"
            implicitHeight: 52
            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 20
                text: "⚠ ERASE TARGET DRIVE(S)?"
                color: theme.colors.colorBorderError
                font.family: Theme.fontTitle
                font.pixelSize: 13
                font.bold: true
                font.letterSpacing: 1.4
            }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                height: 1; color: theme.colors.colorDivider
            }
        }

        contentItem: Text {
            text: "This will ERASE the target SD card(s) and write the selected image. " +
                  "There is no undo. Proceed only if the drive letters look correct."
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontBody
            font.pixelSize: 13
            wrapMode: Text.Wrap
            width: 440
            leftPadding: 20
            rightPadding: 20
            topPadding: 20
            bottomPadding: 4
        }

        footer: RowLayout {
            spacing: 10
            Item { Layout.fillWidth: true }
            AstroButton {
                text: "CANCEL"
                variant: "secondary"
                onClicked: confirmDialog.reject()
            }
            AstroButton {
                text: "⚡ ERASE & WRITE"
                variant: "danger"
                horizontalPadding: 18
                onClicked: confirmDialog.accept()
            }
            Item { width: 18 }
        }

        onAccepted: flashViewModel.startFromWizard()
    }
}

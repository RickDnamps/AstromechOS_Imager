import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: Theme.colorBg

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        anchors.bottomMargin: 88
        spacing: 18

        // ── Headline ──────────────────────────────────────────────────
        RowLayout {
            spacing: 16
            Layout.bottomMargin: 4

            // Success indicator — filled cyan circle with a check mark.
            Rectangle {
                width: 44; height: 44; radius: 22
                color: Theme.colorAccent
                Layout.alignment: Qt.AlignVCenter
                Text {
                    anchors.centerIn: parent
                    text: "✓"
                    color: Theme.colorTextOnAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 22
                    font.bold: true
                }
                // Subtle pulsing halo
                Rectangle {
                    anchors.centerIn: parent
                    width: 60; height: 60; radius: 30
                    color: Theme.colorAccent
                    opacity: 0.18
                    z: -1
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite; running: true
                        NumberAnimation { to: 0.08; duration: 1400; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0.28; duration: 1400; easing.type: Easing.InOutSine }
                    }
                }
            }

            ColumnLayout {
                spacing: 2
                Layout.alignment: Qt.AlignVCenter
                Text {
                    text: "COMPLETE"
                    color: Theme.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 22
                    font.bold: true
                    font.letterSpacing: 2.2
                }
                Text {
                    text: needMaster && needSlave
                        ? "Both AstromechOS SD cards have been flashed."
                        : "Your AstromechOS SD card has been flashed."
                    color: Theme.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 13
                }
            }
        }

        // ── Next steps panel ──────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 232
            color: Theme.colorSurface
            border.color: Theme.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard

            // Top edge highlight (glass)
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                Text {
                    text: "NEXT STEPS"
                    color: Theme.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.8
                }

                Repeater {
                    model: [
                        "Eject both SDs (auto-eject already attempted)",
                        "Insert each card into its Pi 4B (Master ↔ dome, Slave ↔ body)",
                        "First boot takes ~3 min and reboots automatically",
                        "SSH via astromech-master.local / astromech-slave.local",
                    ]
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        // Step number badge
                        Rectangle {
                            Layout.preferredWidth: 22; Layout.preferredHeight: 22
                            radius: 11
                            color: "transparent"
                            border.color: Theme.colorBorderAccent
                            border.width: 1
                            Text {
                                anchors.centerIn: parent
                                text: (index + 1).toString()
                                color: Theme.colorAccent
                                font.family: Theme.fontTitle
                                font.pixelSize: 10
                                font.bold: true
                            }
                        }
                        Text {
                            text: modelData
                            color: Theme.colorTextPrimary
                            font.family: Theme.fontBody
                            font.pixelSize: 13
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton {
            text: "FLASH ANOTHER"
            variant: "secondary"
            onClicked: { wizardState.goto(1); }
        }
        AstroButton {
            text: "QUIT"
            variant: "primary"
            onClicked: Qt.quit()
        }
    }
}

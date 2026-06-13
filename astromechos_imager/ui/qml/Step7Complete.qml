import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    color: theme.colors.colorBg

    // Sequential Deployment Assistant: derived from the role-completion
    // history.
    property bool needMaster: wizardState.completedRoles.indexOf("master") >= 0
    property bool needSlave:  wizardState.completedRoles.indexOf("slave")  >= 0
    property bool bothDone:   needMaster && needSlave

    // Next-steps list reflects what was actually flashed this session:
    // the full two-card path versus the single-card (partial) path.
    property var nextStepsModel: {
        if (wizardState.completedRoles.length >= 2) {
            return [
                "Insert each card into its Pi 4B (Master → dome, Slave → body).",
                "Power on both — first boot takes ~3 min, then a self-reboot.",
                "Join Wi-Fi \"Astromech-XXXX\" (suffix from the Master's CPU ID) with your hotspot password.",
                "Open http://192.168.4.1:5000 for the dashboard (default admin password \"astro\").",
            ]
        }
        var role = wizardState.completedRoles[0] || "master"
        var roleName = role === "master" ? "MASTER (dome)" : "SLAVE (body)"
        var missing  = role === "master" ? "SLAVE (body)"  : "MASTER (dome)"
        return [
            "Insert the " + roleName + " card into its Pi 4B.",
            "Re-run the Imager to flash the " + missing + " card when ready.",
        ]
    }

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
                color: theme.colors.colorAccent
                Layout.alignment: Qt.AlignVCenter
                Text {
                    anchors.centerIn: parent
                    text: "✓"
                    color: theme.colors.colorTextOnAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 22
                    font.bold: true
                }
                // Subtle pulsing halo
                Rectangle {
                    anchors.centerIn: parent
                    width: 60; height: 60; radius: 30
                    color: theme.colors.colorAccent
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
                    // Distinguish partial vs full deployment so the operator
                    // isn't told the session is fully done after only one role.
                    text: root.bothDone ? "DEPLOYMENT COMPLETE" : "PARTIAL DEPLOYMENT"
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 22
                    font.bold: true
                    font.letterSpacing: 2.2
                }
                Text {
                    text: root.bothDone
                        ? "Both AstromechOS SD cards have been flashed."
                        : "Your AstromechOS SD card has been flashed."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 13
                }
            }
        }

        // ── Next steps panel ──────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            // Size to content (+36 = 2×18 inner margins) so the longer
            // network/dashboard guidance never clips on wrap.
            Layout.preferredHeight: stepsCol.implicitHeight + 36
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard

            // Top edge highlight (glass)
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                id: stepsCol
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                Text {
                    text: "NEXT STEPS"
                    color: theme.colors.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.8
                }

                Repeater {
                    model: root.nextStepsModel
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        // Step number badge
                        Rectangle {
                            Layout.preferredWidth: 22; Layout.preferredHeight: 22
                            radius: 11
                            color: "transparent"
                            border.color: theme.colors.colorBorderAccent
                            border.width: 1
                            Text {
                                anchors.centerIn: parent
                                text: (index + 1).toString()
                                color: theme.colors.colorAccent
                                font.family: Theme.fontTitle
                                font.pixelSize: 10
                                font.bold: true
                            }
                        }
                        Text {
                            text: modelData
                            color: theme.colors.colorTextPrimary
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

        // Diagnostic export result (ZIP path or error). Kept in the layout
        // flow above the reserved action-bar zone so it never overlaps the
        // buttons.
        Text {
            id: diagResult
            Layout.fillWidth: true
            text: ""
            visible: text !== ""
            color: text.indexOf("ERROR") === 0
                ? theme.colors.colorBorderError
                : theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 11
            elide: Text.ElideMiddle
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton {
            text: "EXPORT DIAGNOSTIC"
            variant: "secondary"
            onClicked: {
                var p = flashViewModel.exportDiagnostic()
                diagResult.text = p.indexOf("ERROR") === 0
                    ? p : ("Diagnostic bundle saved: " + p)
            }
        }
        AstroButton {
            text: "FLASH ANOTHER"
            variant: "secondary"
            onClicked: {
                // A fresh sequential session must wipe completedRoles AND
                // mint a fresh bootstrap SSID. wizardState.endSession() does
                // both (it regenerates hotspotSsid) so the next pair never
                // reuses the previous robot's wlan0 rendezvous.
                wizardState.endSession()
                wizardState.goto(1)
            }
        }
        AstroButton {
            text: "QUIT"
            variant: "primary"
            onClicked: Qt.quit()
        }
    }
}

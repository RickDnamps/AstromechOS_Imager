// AstromechOS Imager — Step 6 "Next Card".
//
// Sequential Deployment Assistant loop point. After a successful flash
// in Step 5 Ops, the operator lands here. Two paths:
//
//   * cycleIndex == 1 and proposedNextRole != "" — show "INSERT NEXT
//     CARD" with the auto-proposed role; CONTINUE resets per-cycle
//     state and jumps back to Step 4 Role (the SAME session SSID and
//     Step 2 Config carry through).
//
//   * completedRoles.length >= 2 — show "DEPLOYMENT COMPLETE";
//     FINISH advances to Step 7 Complete.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

    // "" | "master" | "slave" — empty when both roles already done OR
    // (defensively) when nothing has been flashed yet (operator
    // shouldn't be on this screen in that case but UI must still
    // render safely).
    property string nextRole: wizardState.proposedNextRole
    property bool bothDone: wizardState.completedRoles.length >= 2

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 22
        width: 580

        Text {
            text: bothDone
                  ? "DEPLOYMENT COMPLETE"
                  : "CARD " + wizardState.cycleIndex + " OF 2 FLASHED"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 20
            font.bold: true
            font.letterSpacing: 1.6
            Layout.alignment: Qt.AlignHCenter
            horizontalAlignment: Text.AlignHCenter
        }

        Text {
            visible: !bothDone
            text: nextRole === "master"
                  ? "Insert the SECOND SD card. It will be flashed as MASTER (Dome)."
                  : nextRole === "slave"
                  ? "Insert the SECOND SD card. It will be flashed as SLAVE (Body)."
                  : "Insert the next SD card to continue the deployment."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            Layout.alignment: Qt.AlignHCenter
        }

        Text {
            visible: bothDone
            text: "Both Master and Slave cards have been written. The shared hotspot SSID ensures runtime pairing on first boot."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            Layout.alignment: Qt.AlignHCenter
        }

        // ── Session SSID recap ───────────────────────────────────────
        Rectangle {
            visible: flashViewModel.sessionSsid !== ""
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 360
            implicitHeight: 60
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                Text {
                    text: "HOTSPOT SSID"
                    color: theme.colors.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                Text {
                    text: flashViewModel.sessionSsid
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontMono
                    font.pixelSize: 12
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        // ── Completed roles recap ────────────────────────────────────
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 360
            implicitHeight: completedCol.implicitHeight + 24
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard

            ColumnLayout {
                id: completedCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                Text {
                    text: "FLASHED THIS SESSION"
                    color: theme.colors.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                Repeater {
                    model: wizardState.completedRoles
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text {
                            text: "✓"
                            color: theme.colors.colorTextSuccess
                            font.family: Theme.fontTitle
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Text {
                            text: (modelData + "").toUpperCase()
                            color: theme.colors.colorTextPrimary
                            font.family: Theme.fontTitle
                            font.pixelSize: 11
                            font.bold: true
                            font.letterSpacing: 1.4
                            Layout.fillWidth: true
                        }
                    }
                }
                Text {
                    visible: wizardState.completedRoles.length === 0
                    text: "(none — return to Step 4 Role)"
                    color: theme.colors.colorTextTertiary
                    font.family: Theme.fontBody
                    font.pixelSize: 11
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
            visible: !bothDone
            text: "DONE (SKIP SECOND CARD)"
            variant: "secondary"
            onClicked: wizardState.goto(7)
        }
        AstroButton {
            visible: !bothDone
            text: "INSERT NEXT CARD → CONTINUE"
            variant: "primary"
            horizontalPadding: 22
            onClicked: {
                wizardState.resetForNextCycle()
                wizardState.goto(4)   // back to Step 4 Role
            }
        }
        AstroButton {
            visible: bothDone
            text: "FINISH →"
            variant: "primary"
            horizontalPadding: 24
            onClicked: wizardState.next()
        }
    }
}

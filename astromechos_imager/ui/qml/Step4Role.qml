// AstromechOS Imager — Step 4 "Role".
//
// Sequential Deployment Assistant: one card per cycle. The operator
// has ONE SD card connected; this screen detects it, asks "write this
// as MASTER or SLAVE?", and assigns the corresponding drive id on the
// wizard state. The auto-proposed role (after the first cycle) is
// pre-highlighted so the operator just hits NEXT.
//
//   * driveCount == 0  → "AWAITING SD CARD" empty-state animation
//   * driveCount == 1  → role-pick UI (MASTER / SLAVE)
//   * driveCount >= 2  → red banner — only ONE card allowed in
//                        sequential mode (leave only one connected)
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    color: theme.colors.colorBg

    // Live count from the C++ model — the hidden ListView pattern was
    // dropped because Qt 6 does not instantiate a delegate with
    // width=0/height=0/visible=false, so the delegate's Component.onCompleted
    // never fired and the firstDrive* properties stayed at their defaults
    // even when a card was plugged in. DriveListModel now exposes a `count`
    // Property + dedicated firstDrive* Properties for direct binding.
    readonly property int driveCount: driveListModel ? driveListModel.count : 0
    readonly property bool hasOneCard: driveCount === 1
    readonly property bool tooManyCards: driveCount >= 2

    // Pre-highlight the auto-proposed role for cycle 2+ (the operator
    // is free to override). "" before any flash.
    readonly property string proposed: wizardState.proposedNextRole

    // Read-only bindings to the live drive model — these track the model
    // automatically and stay correct when a card is inserted/removed
    // mid-step, which the old hidden-ListView capture pattern did not.
    readonly property int    firstDriveId:      driveListModel ? driveListModel.firstDriveId      : -1
    readonly property string firstDriveLetters: driveListModel ? driveListModel.firstDriveLetters : ""
    readonly property string firstDriveModel:   driveListModel ? driveListModel.firstDriveModel   : ""
    readonly property string firstDriveSize:    driveListModel ? driveListModel.firstDriveSize    : ""

    function _assignRole(role) {
        wizardState.setCurrentRole(role)
        if (firstDriveId === -1) return
        if (role === "master") {
            wizardState.setMasterDriveId(firstDriveId)
        } else if (role === "slave") {
            wizardState.setSlaveDriveId(firstDriveId)
        }
    }

    // Cycle 2+: one role is already done (greyed out, non-selectable), so the
    // remaining role is the ONLY choice — auto-SELECT it (not just highlight)
    // so the operator just hits NEXT instead of clicking the obvious card.
    // Re-runs when the card is inserted after the step loads.
    function _autoSelectProposed() {
        if (hasOneCard && proposed !== "" && wizardState.currentRole !== proposed)
            _assignRole(proposed)
    }
    Component.onCompleted: _autoSelectProposed()
    onProposedChanged: _autoSelectProposed()
    onDriveCountChanged: _autoSelectProposed()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        spacing: 14

        Text {
            text: "INSERT SD CARD"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
        }
        Text {
            text: "Sequential deployment flashes ONE card per cycle. Insert the card you want to write next, then pick its role."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 6
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        // ── Detected drive card ──────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: theme.colors.colorSurface
            border.color: tooManyCards ? theme.colors.colorBorderError
                : hasOneCard           ? theme.colors.colorBorderAccent
                                       : theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            // Empty-state overlay — visible when no drive is detected.
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 14
                visible: driveCount === 0
                Text {
                    text: "⌖"   // crosshair / waiting glyph
                    color: theme.colors.colorAccentDim
                    font.family: Theme.fontTitle
                    font.pixelSize: 56
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: driveCount === 0
                        NumberAnimation { to: 0.35; duration: 1100; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0.95; duration: 1100; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    text: "AWAITING SD CARD"
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 2.0
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                }
                Text {
                    text: "Insert ONE removable card — it will appear here within ~2 s."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                }
            }

            // Too-many-cards red banner
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 12
                visible: tooManyCards
                width: 460
                Text {
                    text: "⚠ MULTIPLE SD CARDS DETECTED"
                    color: theme.colors.colorBorderError
                    font.family: Theme.fontTitle
                    font.pixelSize: 14
                    font.bold: true
                    font.letterSpacing: 1.6
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
                Text {
                    text: "Sequential deployment writes one card at a time. Leave ONLY the card you want to flash now connected — unplug the others, then this screen will let you pick a role."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
            }

            // Single-card view — drive info + role pick
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 18
                visible: hasOneCard

                // Drive row
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
                    color: theme.colors.colorBg
                    border.color: theme.colors.colorBorderAccent
                    border.width: 1
                    radius: Theme.radiusButton
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 14
                        Text {
                            text: root.firstDriveLetters !== "" ? root.firstDriveLetters : "—"
                            color: theme.colors.colorTextAccent
                            font.family: Theme.fontMono
                            font.pixelSize: 14
                            font.bold: true
                            Layout.preferredWidth: 64
                        }
                        Text {
                            text: root.firstDriveModel !== ""
                                  ? (root.firstDriveModel + " · " + root.firstDriveSize)
                                  : "—"
                            color: theme.colors.colorTextSecondary
                            font.family: Theme.fontBody
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }

                // Role-pick section
                Text {
                    text: "WRITE THIS CARD AS"
                    color: theme.colors.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.6
                    Layout.topMargin: 4
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    // MASTER card
                    Rectangle {
                        // Audit bug H2: a completed role card is
                        // visually de-emphasised and the MouseArea is
                        // disabled so the operator can't re-flash it.
                        property bool masterDone: wizardState.completedRoles.indexOf("master") >= 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 110
                        opacity: masterDone ? 0.5 : 1.0
                        color: wizardState.currentRole === "master"
                               ? theme.colors.colorSurfaceAccent
                               : theme.colors.colorSurface
                        border.color: wizardState.currentRole === "master"
                               ? theme.colors.colorAccentBright
                               : (proposed === "master" ? theme.colors.colorBorderAccent : theme.colors.colorBorderIdle)
                        border.width: wizardState.currentRole === "master" ? 2 : 1
                        radius: Theme.radiusCard
                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on color        { ColorAnimation { duration: Theme.durFast } }
                        Behavior on opacity      { NumberAnimation { duration: Theme.durFast } }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: "MASTER"
                                    color: theme.colors.colorTextPrimary
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 13
                                    font.bold: true
                                    font.letterSpacing: 1.6
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    visible: wizardState.completedRoles.indexOf("master") >= 0
                                    text: "✓ DONE"
                                    color: theme.colors.colorTextSuccess
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.letterSpacing: 1.2
                                }
                                Text {
                                    visible: proposed === "master" && wizardState.currentRole !== "master"
                                    text: "PROPOSED"
                                    color: theme.colors.colorTextAccent
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 9
                                    font.bold: true
                                    font.letterSpacing: 1.2
                                }
                            }
                            Text {
                                text: "Dome Pi 4B (4 GB) — Flask, dashboard, PCA9685"
                                color: theme.colors.colorTextSecondary
                                font.family: Theme.fontBody
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            Item { Layout.fillHeight: true }
                        }
                        MouseArea {
                            anchors.fill: parent
                            // Audit bug H2: disable clicks on a
                            // completed role to prevent re-flashing
                            // the same role twice in one session.
                            enabled: wizardState.completedRoles.indexOf("master") < 0
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            onClicked: root._assignRole("master")
                        }
                    }

                    // SLAVE card
                    Rectangle {
                        // Audit bug H2: parallel treatment with MASTER.
                        property bool slaveDone: wizardState.completedRoles.indexOf("slave") >= 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 110
                        opacity: slaveDone ? 0.5 : 1.0
                        color: wizardState.currentRole === "slave"
                               ? theme.colors.colorSurfaceAccent
                               : theme.colors.colorSurface
                        border.color: wizardState.currentRole === "slave"
                               ? theme.colors.colorAccentBright
                               : (proposed === "slave" ? theme.colors.colorBorderAccent : theme.colors.colorBorderIdle)
                        border.width: wizardState.currentRole === "slave" ? 2 : 1
                        radius: Theme.radiusCard
                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on color        { ColorAnimation { duration: Theme.durFast } }
                        Behavior on opacity      { NumberAnimation { duration: Theme.durFast } }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: "SLAVE"
                                    color: theme.colors.colorTextPrimary
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 13
                                    font.bold: true
                                    font.letterSpacing: 1.6
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    visible: wizardState.completedRoles.indexOf("slave") >= 0
                                    text: "✓ DONE"
                                    color: theme.colors.colorTextSuccess
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.letterSpacing: 1.2
                                }
                                Text {
                                    visible: proposed === "slave" && wizardState.currentRole !== "slave"
                                    text: "PROPOSED"
                                    color: theme.colors.colorTextAccent
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 9
                                    font.bold: true
                                    font.letterSpacing: 1.2
                                }
                            }
                            Text {
                                text: "Body Pi 4B (2 GB) — UART listener, VESC, audio"
                                color: theme.colors.colorTextSecondary
                                font.family: Theme.fontBody
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            Item { Layout.fillHeight: true }
                        }
                        MouseArea {
                            anchors.fill: parent
                            // Audit bug H2: see MASTER MouseArea above.
                            enabled: wizardState.completedRoles.indexOf("slave") < 0
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            onClicked: root._assignRole("slave")
                        }
                    }
                }

                // Help text bottom
                Text {
                    text: "This card will be flashed as " +
                          (wizardState.currentRole !== "" ?
                              wizardState.currentRole.toUpperCase() : "PENDING")
                    color: wizardState.currentRole !== "" ? theme.colors.colorTextAccent : theme.colors.colorTextTertiary
                    font.family: Theme.fontTitle
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.4
                    Layout.alignment: Qt.AlignHCenter
                    horizontalAlignment: Text.AlignHCenter
                }

                Item { Layout.fillHeight: true }
            }

            // (No hidden ListView here — DriveListModel exposes count +
            // firstDrive* Properties directly. See the readonly bindings
            // at the top of this file.)
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
            enabled: hasOneCard
                && ((wizardState.currentRole === "master" && wizardState.masterDriveId !== -1)
                 || (wizardState.currentRole === "slave"  && wizardState.slaveDriveId  !== -1))
            onClicked: {
                if (flashViewModel.status === "error") {
                    flashViewModel.resetForNextCycle()
                }
                wizardState.next()
            }
        }
    }
}

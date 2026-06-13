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

    // Live count from the C++ model via direct Properties. A hidden-ListView
    // capture pattern can't be used here: Qt 6 does not instantiate a
    // delegate with width=0/height=0/visible=false, so the delegate's
    // Component.onCompleted never fires and the captured values stay at their
    // defaults even when a card is plugged in. DriveListModel exposes a
    // `count` Property + dedicated firstDrive* Properties for direct binding.
    readonly property int driveCount: driveListModel ? driveListModel.count : 0
    readonly property bool hasOneCard: driveCount === 1
    readonly property bool tooManyCards: driveCount >= 2

    // Pre-highlight the auto-proposed role for cycle 2+ (the operator
    // is free to override). "" before any flash.
    readonly property string proposed: wizardState.proposedNextRole

    // The role for THIS card is IMPOSED by the deployment sequence, NOT a
    // free choice: the first card MUST be MASTER (a Slave is useless without
    // its Master — they share the per-session rendezvous SSID and pair
    // master-first), the second is the remaining SLAVE. "" once both are
    // done. The screen auto-selects this and DISABLES the other option so the
    // operator can't, e.g., flash a Slave first.
    readonly property string imposedRole:
        wizardState.completedRoles.indexOf("master") < 0 ? "master"
        : (wizardState.completedRoles.indexOf("slave") < 0 ? "slave" : "")

    // Read-only bindings to the live drive model — these track the model
    // automatically and stay correct when a card is inserted/removed
    // mid-step.
    readonly property int    firstDriveId:      driveListModel ? driveListModel.firstDriveId      : -1
    readonly property string firstDriveLetters: driveListModel ? driveListModel.firstDriveLetters : ""
    readonly property string firstDriveModel:   driveListModel ? driveListModel.firstDriveModel   : ""
    readonly property string firstDriveSize:    driveListModel ? driveListModel.firstDriveSize    : ""
    // USB FIXED media (external SSD/HDD — e.g. the operator's image-source
    // drive) — eligible to LIST but never auto-selected.
    readonly property bool   firstDriveSuspect: driveListModel
        && driveListModel.firstDriveSuspect !== undefined
        ? driveListModel.firstDriveSuspect : false

    // The drive id currently held by WizardState for the imposed role —
    // the NEXT gate requires it to match the LIVE first drive, so a card
    // swap (pull A, insert B) can never flash a stale id.
    readonly property int selectedDriveId:
        wizardState.currentRole === "master" ? wizardState.masterDriveId
        : wizardState.currentRole === "slave" ? wizardState.slaveDriveId
        : -1

    // True once a single live card is detected and its id matches the one
    // armed on the wizard state — a card swap leaves the stale id behind and
    // re-arms this to false. Gates both the WRITE button and the inline
    // confirm block (SHA toggle + erase warning).
    readonly property bool cardArmed: hasOneCard
        && selectedDriveId !== -1
        && selectedDriveId === firstDriveId

    function _assignRole(role) {
        wizardState.setCurrentRole(role)
        if (firstDriveId === -1) return
        if (role === "master") {
            wizardState.setMasterDriveId(firstDriveId)
        } else if (role === "slave") {
            wizardState.setSlaveDriveId(firstDriveId)
        }
    }

    // The role is imposed (master first, then slave), so auto-SELECT it — the
    // operator just hits NEXT. The opposite card is disabled + dimmed. Re-runs
    // when the card is inserted after the step loads AND when the single
    // drive's id changes (card swap), so a swapped card never leaves a stale
    // drive id armed. Suspect FIXED disks are never auto-selected; the
    // operator must click the explicit override.
    function _autoSelectImposed() {
        if (!hasOneCard || imposedRole === "" || firstDriveSuspect) return
        if (wizardState.currentRole !== imposedRole
                || selectedDriveId !== firstDriveId)
            _assignRole(imposedRole)
    }
    Component.onCompleted: _autoSelectImposed()
    onImposedRoleChanged: _autoSelectImposed()
    onDriveCountChanged: _autoSelectImposed()
    onFirstDriveIdChanged: _autoSelectImposed()

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
            text: "Sequential deployment flashes ONE card per cycle. The role is assigned automatically — MASTER first, then SLAVE. Insert the next card and hit NEXT."
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

            // Automount-defense amber strip — mountvol /N failed (typically a
            // non-elevated run): Windows can still auto-mount + probe a card
            // and pop "Format this disk?". Tell the operator instead of
            // silently degrading.
            Rectangle {
                visible: typeof systemStatus !== "undefined" && systemStatus
                         && systemStatus.automountDefenseActive === false
                anchors.top: parent.top
                anchors.topMargin: 8
                anchors.horizontalCenter: parent.horizontalCenter
                width: 460
                height: automountWarnText.implicitHeight + 14
                radius: 6
                color: "transparent"
                border.color: theme.colors.colorBorderWarn
                border.width: 1
                Text {
                    id: automountWarnText
                    anchors.centerIn: parent
                    width: parent.width - 20
                    text: "⚠ Windows automount is still ON (run the Imager as administrator). Format pop-ups may appear — do NOT click Format."
                    color: theme.colors.colorBorderWarn
                    font.family: Theme.fontBody
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            // Suspect USB FIXED disk — looks like an external SSD/HDD, not
            // an SD card (e.g. a large image-source SSD that passes the
            // eligibility filter). Never auto-selected; the operator must
            // explicitly override. Some SD readers behind USB-SATA bridges
            // legitimately report "Fixed", hence the override instead of a
            // hard block.
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 12
                visible: hasOneCard && firstDriveSuspect
                         && selectedDriveId !== firstDriveId
                width: 460
                Text {
                    text: "⚠ USB FIXED DISK DETECTED"
                    color: theme.colors.colorBorderWarn
                    font.family: Theme.fontTitle
                    font.pixelSize: 14
                    font.bold: true
                    font.letterSpacing: 1.6
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
                Text {
                    text: firstDriveModel + " (" + firstDriveSize + ") reports "
                          + "itself as a FIXED disk — that is usually an external "
                          + "SSD/HDD, not an SD card. It was NOT auto-selected. "
                          + "Unplug it and insert the SD card, or — only if this "
                          + "really is your SD reader — override below."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
                AstroButton {
                    text: "USE THIS FIXED DISK ANYWAY"
                    variant: "secondary"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: _assignRole(imposedRole)
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

            // Single-card view — drive info + role pick. Hidden while an
            // un-overridden suspect FIXED disk shows its warning banner.
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 18
                visible: hasOneCard && (!firstDriveSuspect
                                        || selectedDriveId === firstDriveId)

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
                        // A completed role card is visually de-emphasised and
                        // its MouseArea is disabled so the operator can't
                        // re-flash it.
                        property bool masterDone: wizardState.completedRoles.indexOf("master") >= 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 110
                        // Dimmed when already flashed OR when MASTER isn't the
                        // role imposed for this card (can't pick it out of turn).
                        opacity: (masterDone || root.imposedRole !== "master") ? 0.5 : 1.0
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
                            // Selectable ONLY when MASTER is the imposed role
                            // for this card. A completed role is never the
                            // imposed one, so it stays disabled.
                            enabled: root.imposedRole === "master"
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            onClicked: root._assignRole("master")
                        }
                    }

                    // SLAVE card
                    Rectangle {
                        // Parallel treatment with MASTER: a completed role
                        // card is de-emphasised and its MouseArea disabled.
                        property bool slaveDone: wizardState.completedRoles.indexOf("slave") >= 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 110
                        // Dimmed when already flashed OR when SLAVE isn't the
                        // role imposed for this card (MASTER must go first).
                        opacity: (slaveDone || root.imposedRole !== "slave") ? 0.5 : 1.0
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
                            // Selectable ONLY when SLAVE is the imposed role —
                            // i.e. the Master is already done. Can't flash a
                            // Slave first.
                            enabled: root.imposedRole === "slave"
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

            // DriveListModel exposes count + firstDrive* Properties
            // directly. See the readonly bindings at the top of this file.
        }

        // ── Inline confirm controls (SHA toggle + erase warning) ──────
        // The integrity toggle and destructive-write warning sit beside the
        // card pick so WRITE is reachable without an extra screen. Shown
        // only once a valid target card is armed.
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.cardArmed
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Rectangle {
                    Layout.preferredWidth: 18; Layout.preferredHeight: 18
                    radius: 4
                    color: wizardState.verifyIntegrity ? theme.colors.colorAccent : "transparent"
                    border.color: wizardState.verifyIntegrity ? theme.colors.colorAccent : theme.colors.colorBorderIdle
                    border.width: 1
                    Behavior on color        { ColorAnimation { duration: Theme.durFast } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                    Text {
                        anchors.centerIn: parent; text: "✓"
                        color: theme.colors.colorTextOnAccent
                        font.family: Theme.fontTitle; font.pixelSize: 12; font.bold: true
                        visible: wizardState.verifyIntegrity
                    }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: wizardState.setVerifyIntegrity(!wizardState.verifyIntegrity)
                    }
                }
                Text {
                    text: "🛡 VERIFY IMAGE INTEGRITY (SHA-256) BEFORE FLASH"
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.4
                    Layout.fillWidth: true
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: wizardState.setVerifyIntegrity(!wizardState.verifyIntegrity)
                    }
                }
            }

            RowLayout {
                spacing: 8
                Text {
                    text: "⚠"; color: theme.colors.colorBorderWarn
                    font.family: Theme.fontTitle; font.pixelSize: 14
                }
                Text {
                    text: "ALL DATA ON THE TARGET DRIVE WILL BE ERASED."
                    color: theme.colors.colorBorderWarn
                    font.family: Theme.fontTitle; font.pixelSize: 11
                    font.bold: true; font.letterSpacing: 1.4
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
            text: "⚡ WRITE"
            variant: "danger"
            horizontalPadding: 28
            // selectedDriveId must equal the LIVE first drive id: a card
            // swap (pull A, insert B) leaves the stale id A armed while the
            // row displays B. Also blocks the un-overridden suspect-FIXED
            // case (selectedDriveId stays -1).
            enabled: root.cardArmed
            onClicked: confirmDialog.open()
        }
    }

    // ── Destructive-write confirmation ────────────────────────────────
    // The operator confirms and launches the flash from the card-pick
    // screen. On accept it kicks the flash worker and advances to the Ops
    // progress screen.
    Dialog {
        id: confirmDialog
        objectName: "confirmDialog"   // found by scripts/ui_tour.py for the screenshot
        modal: true
        anchors.centerIn: parent
        width: 520
        padding: 0
        background: Rectangle {
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderError
            border.width: 2
        }
        header: Rectangle {
            implicitHeight: 60
            color: Qt.rgba(theme.colors.colorBorderError.r,
                           theme.colors.colorBorderError.g,
                           theme.colors.colorBorderError.b, 0.07)
            radius: Theme.radiusCard
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24; anchors.rightMargin: 24
                spacing: 12
                Text {
                    text: "⚠"; color: theme.colors.colorBorderError
                    font.family: Theme.fontTitle; font.pixelSize: 20; font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    text: "ERASE TARGET DRIVE?"
                    color: theme.colors.colorBorderError
                    font.family: Theme.fontTitle; font.pixelSize: 14
                    font.bold: true; font.letterSpacing: 1.6
                }
            }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                height: 1; color: theme.colors.colorDivider
            }
        }
        contentItem: Text {
            text: wizardState.verifyIntegrity
                ? "Image checksum will be verified, then the selected target SD card will be ERASED and rewritten. This action is irreversible — confirm the drive letter above matches the card you intend to flash."
                : "The selected target SD card will be ERASED and rewritten with the chosen image. This action is irreversible — confirm the drive letter above matches the card you intend to flash."
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontBody; font.pixelSize: 13
            wrapMode: Text.Wrap; lineHeight: 1.35
            leftPadding: 24; rightPadding: 24
            topPadding: 22; bottomPadding: 22
        }
        footer: Rectangle {
            implicitHeight: 72
            color: "transparent"
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                height: 1; color: theme.colors.colorDivider
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20; anchors.rightMargin: 20
                anchors.topMargin: 14; anchors.bottomMargin: 14
                spacing: 12
                Item { Layout.fillWidth: true }
                AstroButton {
                    text: "CANCEL"; variant: "secondary"
                    onClicked: confirmDialog.reject()
                }
                AstroButton {
                    text: "⚡ ERASE & WRITE"; variant: "danger"
                    horizontalPadding: 24; Layout.minimumWidth: 180
                    onClicked: confirmDialog.accept()
                }
            }
        }
        onAccepted: {
            if (flashViewModel.status === "error")
                flashViewModel.resetForNextCycle()
            flashViewModel.startFromWizard()
            wizardState.next()
        }
    }
}

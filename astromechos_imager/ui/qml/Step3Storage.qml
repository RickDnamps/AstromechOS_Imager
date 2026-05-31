import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        spacing: 14

        Text {
            text: "SELECT TARGET SD CARDS"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
        }
        Text {
            // System drive is excluded at the enumerate_removable_drives() layer
            // (platform/windows.py Phase 4.2) — it never appears in this list.
            text: "Removable drives only — the system drive is hidden for safety."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 6
        }

        // ── Single-card mode affordance ───────────────────────────────────
        // When the operator has inserted exactly ONE removable SD card while
        // the wizard mode is still "both" (the default), the NEXT button
        // can never enable — both masterDriveId AND slaveDriveId must be
        // assigned, but a single drive can only fill one slot. Rather than
        // leaving the operator stuck on a greyed-out NEXT, this banner
        // offers to switch to master_only or slave_only in one click.
        // The mode swap is non-destructive: drive assignments are preserved
        // (see WizardState.setMode — only the _mode field changes).
        Rectangle {
            Layout.fillWidth: true
            visible: driveList.count === 1 && wizardState.mode === "both"
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderAccent
            border.width: 1
            radius: Theme.radiusCard
            implicitHeight: singleCardCol.implicitHeight + 28

            ColumnLayout {
                id: singleCardCol
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Text {
                    text: "ONLY 1 SD DETECTED — WRITE AS:"
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 12
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AstroButton {
                        text: "USE AS MASTER"
                        variant: "secondary"
                        onClicked: wizardState.setMode("master_only")
                    }
                    AstroButton {
                        text: "USE AS SLAVE"
                        variant: "secondary"
                        onClicked: wizardState.setMode("slave_only")
                    }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        // ── Restore-dual-mode affordance ──────────────────────────────────
        // Inverse case: operator picked master_only or slave_only earlier
        // (e.g. via the banner above) but now has ≥2 cards inserted. Offer
        // a single-click return to dual-write mode without sending them
        // back to Step 1.
        Rectangle {
            Layout.fillWidth: true
            visible: driveList.count >= 2 && wizardState.mode !== "both"
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard
            implicitHeight: restoreDualRow.implicitHeight + 20

            RowLayout {
                id: restoreDualRow
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10

                Text {
                    text: "2+ cards detected — currently single-card mode."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
                AstroButton {
                    text: "RESTORE DUAL MODE →"
                    variant: "secondary"
                    horizontalPadding: 14
                    verticalPadding: 7
                    onClicked: wizardState.setMode("both")
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard

            // Empty-state overlay — visible when no drive is detected.
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 14
                visible: !driveList.count
                Text {
                    text: "⌖"   // crosshair / waiting glyph
                    color: theme.colors.colorAccentDim
                    font.family: Theme.fontTitle
                    font.pixelSize: 56
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                    // Pulse only while the empty state is showing. Bind to the
                    // model count instead of `parent.visible` — animations
                    // created via `on property` don't expose a visual parent.
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: !driveList.count
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
                    text: "Insert a removable card — it will appear here within ~2 s."
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                }
            }

            ListView {
                id: driveList
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: typeof driveListModel !== "undefined" ? driveListModel : null
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 56
                    color: "transparent"
                    // Hairline divider between rows
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                        height: 1
                        color: theme.colors.colorDivider
                        opacity: 0.6
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 14

                        Text {
                            text: driveLetters !== "" ? driveLetters : "—"
                            color: theme.colors.colorTextAccent
                            font.family: Theme.fontMono
                            font.pixelSize: 13
                            font.bold: true
                            width: 64
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: model.model + " · " + sizeHuman
                            color: theme.colors.colorTextSecondary
                            font.family: Theme.fontBody
                            font.pixelSize: 13
                            width: 280
                            elide: Text.ElideRight
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Item { width: Math.max(0, parent.width - 64 - 280 - 240); height: 1 }
                        AstroButton {
                            text: wizardState.masterDriveId === physicalDriveId ? "✓ MASTER" : "MASTER"
                            variant: "secondary"
                            selected: wizardState.masterDriveId === physicalDriveId
                            enabled: needMaster && wizardState.slaveDriveId !== physicalDriveId
                            horizontalPadding: 14
                            verticalPadding: 8
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: wizardState.setMasterDriveId(physicalDriveId)
                        }
                        AstroButton {
                            text: wizardState.slaveDriveId === physicalDriveId ? "✓ SLAVE" : "SLAVE"
                            variant: "secondary"
                            selected: wizardState.slaveDriveId === physicalDriveId
                            enabled: needSlave && wizardState.masterDriveId !== physicalDriveId
                            horizontalPadding: 14
                            verticalPadding: 8
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
        anchors.margins: 24
        spacing: 10
        AstroButton { text: "← BACK"; variant: "secondary"; onClicked: wizardState.back() }
        AstroButton {
            text: "NEXT →"
            variant: "primary"
            enabled: (!needMaster || wizardState.masterDriveId !== -1)
                  && (!needSlave  || wizardState.slaveDriveId  !== -1)
            onClicked: wizardState.next()
        }
    }
}

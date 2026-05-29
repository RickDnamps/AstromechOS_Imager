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
        anchors.margins: 28
        anchors.bottomMargin: 88
        spacing: 14

        Text {
            text: "SELECT TARGET SD CARDS"
            color: Theme.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
        }
        Text {
            // System drive is excluded at the enumerate_removable_drives() layer
            // (platform/windows.py Phase 4.2) — it never appears in this list.
            text: "Removable drives only — the system drive is hidden for safety."
            color: Theme.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 6
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.colorSurface
            border.color: Theme.colorBorderIdle
            border.width: 1
            radius: Theme.radiusCard

            // Empty-state overlay — visible when no drive is detected.
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 14
                visible: !driveList.count
                Text {
                    text: "⌖"   // crosshair / waiting glyph
                    color: Theme.colorAccentDim
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
                    color: Theme.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 2.0
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                }
                Text {
                    text: "Insert a removable card — it will appear here within ~2 s."
                    color: Theme.colorTextSecondary
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
                        color: Theme.colorDivider
                        opacity: 0.6
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 14

                        Text {
                            text: driveLetters !== "" ? driveLetters : "—"
                            color: Theme.colorTextAccent
                            font.family: Theme.fontMono
                            font.pixelSize: 13
                            font.bold: true
                            width: 64
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: model.model + " · " + sizeHuman
                            color: Theme.colorTextSecondary
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

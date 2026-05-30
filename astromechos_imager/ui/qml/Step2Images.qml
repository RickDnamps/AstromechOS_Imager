import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.platform 1.1
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

    property bool needMaster: wizardState.mode === "both" || wizardState.mode === "master_only"
    property bool needSlave:  wizardState.mode === "both" || wizardState.mode === "slave_only"

    // Block "NEXT" only on a HARD mismatch — the role marker (or filename
    // pattern, in legacy-image mode) actively says we'd flash the wrong card.
    // Soft states like "checking" or "unknown_marker_absent" let the operator
    // proceed: the FlashJob self-validates before writing the trigger marker.
    readonly property bool masterRoleBlocks: wizardState.masterImageRoleStatus === "mismatch"
    readonly property bool slaveRoleBlocks:  wizardState.slaveImageRoleStatus  === "mismatch"

    FileDialog {
        id: masterDialog
        title: "Select master image"
        nameFilters: ["Pi OS images (*.img *.xz *.gz *.zip)", "All files (*)"]
        onAccepted: wizardState.setMasterImagePath(file.toString())
    }
    FileDialog {
        id: slaveDialog
        title: "Select slave image"
        nameFilters: ["Pi OS images (*.img *.xz *.gz *.zip)", "All files (*)"]
        onAccepted: wizardState.setSlaveImagePath(file.toString())
    }

    // ── Reusable role-status badge (lives below the path line) ────────
    Component {
        id: roleBadge
        RowLayout {
            id: badgeRow
            spacing: 8
            property string status: "none"
            property string roleLabel: "MASTER"
            property string filenameHint: ""

            // Status dot (animated when checking)
            Rectangle {
                width: 8; height: 8; radius: 4
                color: badgeRow.status === "ok"          ? "#5ec07a"
                     : badgeRow.status === "mismatch"    ? theme.colors.colorBorderError
                     : badgeRow.status === "checking"    ? theme.colors.colorAccent
                     : badgeRow.status === "unknown_marker_absent" ? theme.colors.colorBorderWarn
                     :                                     "transparent"
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
                SequentialAnimation on opacity {
                    running: badgeRow.status === "checking"
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.4; duration: 600; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
                }
            }
            Text {
                Layout.fillWidth: true
                color: badgeRow.status === "ok"          ? "#5ec07a"
                     : badgeRow.status === "mismatch"    ? theme.colors.colorBorderError
                     : badgeRow.status === "checking"    ? theme.colors.colorTextSecondary
                     : badgeRow.status === "unknown_marker_absent" ? theme.colors.colorBorderWarn
                     :                                     theme.colors.colorTextTertiary
                font.family: Theme.fontTitle
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 1.4
                wrapMode: Text.WordWrap
                text:
                    badgeRow.status === "ok"          ? "✓ ASTROMECHOS " + badgeRow.roleLabel + " VERIFIED (marker present)"
                  : badgeRow.status === "mismatch"    ? "✗ MISMATCH — THIS IMAGE IS NOT A " + badgeRow.roleLabel
                  : badgeRow.status === "checking"    ? "VERIFYING ROLE…"
                  : badgeRow.status === "unknown_marker_absent" ?
                        (badgeRow.filenameHint === ""
                            ? "⚠ NO MARKER, NO FILENAME HINT — proceed only if you trust the source"
                            : "⚠ NO MARKER FOUND — relying on filename hint (" + badgeRow.filenameHint.toUpperCase() + ")")
                  : ""
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 22
        width: 580

        Text {
            text: "SELECT SOURCE IMAGES"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
            Layout.bottomMargin: 4
        }
        Text {
            text: "Locate the AstromechOS .img / .img.xz / .img.gz files — downloaded from the project releases, or extracted from your existing R2."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            Layout.bottomMargin: 4
        }

        // ── Master row ────────────────────────────────────────────────
        Rectangle {
            visible: needMaster
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: masterRoleBlocks ? theme.colors.colorBorderError
                : wizardState.masterImagePath ? theme.colors.colorBorderAccent
                : theme.colors.colorBorderIdle
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        text: "MASTER IMAGE"
                        color: theme.colors.colorTextPrimary
                        font.family: Theme.fontTitle
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.4
                    }
                    Item { Layout.fillWidth: true }
                    AstroButton {
                        text: "BROWSE"
                        variant: "secondary"
                        onClicked: masterDialog.open()
                    }
                }
                Text {
                    text: wizardState.masterImagePath || "— no image selected —"
                    color: wizardState.masterImagePath ? theme.colors.colorTextAccent : theme.colors.colorTextTertiary
                    font.family: Theme.fontMono
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                }
                Loader {
                    Layout.fillWidth: true
                    active: wizardState.masterImagePath !== ""
                    sourceComponent: roleBadge
                    onLoaded: {
                        item.status = wizardState.masterImageRoleStatus
                        item.roleLabel = "MASTER"
                        item.filenameHint = wizardState.masterFilenameHint
                    }
                    Connections {
                        target: wizardState
                        function onMasterImageRoleStatusChanged(s) {
                            if (parent.item) parent.item.status = s
                        }
                        function onMasterFilenameHintChanged(h) {
                            if (parent.item) parent.item.filenameHint = h
                        }
                    }
                }
            }
        }

        // ── Slave row ─────────────────────────────────────────────────
        Rectangle {
            visible: needSlave
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: slaveRoleBlocks ? theme.colors.colorBorderError
                : wizardState.slaveImagePath ? theme.colors.colorBorderAccent
                : theme.colors.colorBorderIdle
            border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        text: "SLAVE IMAGE"
                        color: theme.colors.colorTextPrimary
                        font.family: Theme.fontTitle
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.4
                    }
                    Item { Layout.fillWidth: true }
                    AstroButton {
                        text: "BROWSE"
                        variant: "secondary"
                        onClicked: slaveDialog.open()
                    }
                }
                Text {
                    text: wizardState.slaveImagePath || "— no image selected —"
                    color: wizardState.slaveImagePath ? theme.colors.colorTextAccent : theme.colors.colorTextTertiary
                    font.family: Theme.fontMono
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                }
                Loader {
                    Layout.fillWidth: true
                    active: wizardState.slaveImagePath !== ""
                    sourceComponent: roleBadge
                    onLoaded: {
                        item.status = wizardState.slaveImageRoleStatus
                        item.roleLabel = "SLAVE"
                        item.filenameHint = wizardState.slaveFilenameHint
                    }
                    Connections {
                        target: wizardState
                        function onSlaveImageRoleStatusChanged(s) {
                            if (parent.item) parent.item.status = s
                        }
                        function onSlaveFilenameHintChanged(h) {
                            if (parent.item) parent.item.filenameHint = h
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
            enabled: (!needMaster || (wizardState.masterImagePath !== "" && !masterRoleBlocks))
                  && (!needSlave  || (wizardState.slaveImagePath  !== "" && !slaveRoleBlocks))
            onClicked: wizardState.next()
        }
    }
}

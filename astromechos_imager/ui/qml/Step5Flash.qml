import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme
Rectangle {
    id: root
    color: theme.colors.colorBg
    property bool isVerifying: flashViewModel.status === "verifying"
    property bool isFlashing:  flashViewModel.status === "flashing"
    property bool isDone:      flashViewModel.status === "done"
    property bool isError:     flashViewModel.status === "error"
    // One cycle = one role. Progress rendered via shared TaskTracker +
    // GlobalProgressBar (option 2B reusability).
    property bool needMaster: wizardState.currentRole === "master"
    property bool needSlave:  wizardState.currentRole === "slave"

    // ── Role-aware property selection ─────────────────────────────────
    // The flash pipeline routes progress/hash/sidecar into master* OR slave*
    // depending on the role flashed this cycle. The UI MUST read the matching
    // set — reading master* during a SLAVE cycle showed "no sidecar" + a
    // frozen bar (the slave's real values live in slave*).
    function _hashProgress() { return needSlave ? (flashViewModel.slaveHashProgress || 0) : (flashViewModel.masterHashProgress || 0) }
    function _phase()        { return needSlave ? (flashViewModel.slavePhase || "")        : (flashViewModel.masterPhase || "") }
    function _progress()     { return needSlave ? (flashViewModel.slaveProgress || 0)      : (flashViewModel.masterProgress || 0) }
    function _sidecarMatch() { return needSlave ? flashViewModel.slaveHashSidecarMatch     : flashViewModel.masterHashSidecarMatch }
    function _throughput()   { return needSlave ? (flashViewModel.slaveThroughputBps || 0) : (flashViewModel.masterThroughputBps || 0) }

    // ── Stage model for TaskTracker (option 1B 4-stage layout) ────────
    function _buildStages() {
        if (!flashViewModel) return []
        var hp = _hashProgress()
        var p = _phase()
        var prog = _progress()
        var hashDone = hp >= 1.0 || isFlashing || isDone
        var verifyOn = wizardState ? wizardState.verifyIntegrity : true
        // Stage 1: SHA-256 — option 3B (skipped state)
        var s1 = "pending", s1det = ""
        if (!verifyOn)                              { s1 = "skipped"; s1det = "skipped" }
        else if (isError && !hashDone)              { s1 = "failed" }
        else if (isVerifying && !hashDone)          { s1 = "active"; s1det = Math.round(hp * 100) + " %" }
        else if (hashDone) {
            s1 = "done"
            var m = _sidecarMatch()
            s1det = m === true ? "✓ matches sidecar"
                  : m === false ? "✗ mismatch"
                  : "no sidecar"
        }
        // Stage 2: Streaming & writing (option 1B — combined)
        var s2 = "pending", s2det = ""
        var s2Active = isFlashing && (p === "preparing" || p === "decompress_write")
        var s2Done = (p === "verify" || p === "customizing" || isDone)
        if (s2Active) {
            s2 = "active"
            s2det = p === "preparing" ? "preparing…" : Math.round(prog * 100) + " %"
        } else if (s2Done)                                       { s2 = "done"; s2det = "✓ OK" }
        else if (isError && (s1 === "done" || s1 === "skipped")) { s2 = "failed" }
        // Stage 3: Verifying integrity (readback)
        var s3 = "pending", s3det = ""
        if (isFlashing && p === "verify")           { s3 = "active"; s3det = Math.round(prog * 100) + " %" }
        else if (p === "customizing" || isDone)     { s3 = "done"; s3det = "✓ OK" }
        else if (isError && s2 === "done")          { s3 = "failed" }
        // Stage 4: Applying personalization
        var s4 = "pending", s4det = ""
        if (isFlashing && p === "customizing")      { s4 = "active"; s4det = "personalizing…" }
        else if (isDone)                            { s4 = "done"; s4det = "✓ ready to boot" }
        else if (isError && s3 === "done")          { s4 = "failed" }
        return [
            { label: "Validating source (SHA-256)",    status: s1, detail: s1det },
            { label: "Streaming & writing to SD",      status: s2, detail: s2det },
            { label: "Verifying integrity (readback)", status: s3, detail: s3det },
            { label: "Applying personalization",       status: s4, detail: s4det }
        ]
    }

    // ── GlobalProgressBar derivation helpers ──────────────────────────
    function _globalProgress() {
        if (!flashViewModel) return 0.0
        if (isDone)      return 1.0
        if (isError)     return 0   // floor holds the last value via monotonic
        if (isVerifying) return _hashProgress() * 0.05
        if (isFlashing) {
            var p = _phase()
            var prog = _progress()
            if (p === "preparing")        return 0.05
            if (p === "decompress_write") return 0.05 + prog * 0.55
            if (p === "verify")           return 0.60 + prog * 0.35
            if (p === "customizing")      return 0.95
        }
        return 0.0
    }
    function _globalMode() {
        if (!flashViewModel) return "determinate"
        var p = _phase()
        return (isFlashing && (p === "preparing" || p === "customizing")) ? "indeterminate" : "determinate"
    }
    function _globalLabel() {
        if (!flashViewModel) return ""
        var p = _phase()
        if (isFlashing && p === "customizing") return "Personalizing…"
        if (isFlashing && p === "preparing")   return "Preparing…"
        return ""
    }
    // Reset monotonic floor between role cycles so master 100% doesn't pin slave full.
    Connections {
        target: wizardState
        function onCurrentRoleChanged() { if (globalBar) globalBar.resetFloor() }
    }
    Component {
        id: summaryRow
        RowLayout {
            property string roleLabel: ""
            property string imagePath: ""
            property int    driveId: 0
            Layout.fillWidth: true
            spacing: 12
            Text {
                text: roleLabel
                color: theme.colors.colorTextAccent
                font.family: Theme.fontTitle; font.pixelSize: 10
                font.bold: true; font.letterSpacing: 1.6
                Layout.preferredWidth: 70
            }
            Text {
                text: imagePath
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontMono; font.pixelSize: 12
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            Text {
                text: "→ " + (driveListModel ? driveListModel.labelForDriveId(driveId) : ("drive " + driveId))
                color: theme.colors.colorTextSecondary
                font.family: Theme.fontMono; font.pixelSize: 12
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        spacing: 16

        // ── Header ────────────────────────────────────────────────────
        ColumnLayout {
            spacing: 4
            // Role tag — UPPERCASE, baked directly into the title so the
            // operator can never miss which card is being acted on.
            // Reads as "FLASHING MASTER — DO NOT UNPLUG" / "VERIFYING
            // SLAVE IMAGE INTEGRITY…" / "MASTER FLASH COMPLETE" etc.
            Text {
                property string roleTag: needMaster ? "MASTER"
                                        : needSlave  ? "SLAVE"
                                        :              ""
                text: isVerifying ? "VERIFYING " + roleTag + " IMAGE INTEGRITY…"
                    : isFlashing  ? "FLASHING " + roleTag + " — DO NOT UNPLUG"
                    : isError     ? roleTag + " FLASH FAILED"
                    : isDone      ? roleTag + " FLASH COMPLETE"
                    :               "CONFIRM AND FLASH " + roleTag
                color: isError     ? theme.colors.colorBorderError
                     : isDone      ? theme.colors.colorAccent
                     : isVerifying ? theme.colors.colorAccent
                     :               theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 18; font.bold: true; font.letterSpacing: 1.4
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
            Text {
                // Tracker conveys per-phase status — subtitle stays high-level.
                text: isVerifying ? "Hashing each image and comparing with the sidecar checksum (if any)."
                    : isFlashing  ? "Bit-for-bit copy in progress. The Pi will boot from this card."
                    : isError     ? "Review the message below, fix the cause, then retry."
                    : isDone      ? "Eject the card(s) and insert into the Pi 4B."
                    :               "Review the plan below. Writing will erase the targets."
                color: theme.colors.colorTextSecondary
                font.family: Theme.fontBody; font.pixelSize: 12
            }
        }

        // ── Shared task tracker (verifying / flashing / done / error) ─
        TaskTracker {
            id: tracker
            visible: isVerifying || isFlashing || isDone || isError
            Layout.fillWidth: true
            Layout.topMargin: 8
            stages: _buildStages()
        }

        // ── Integrity verification toggle (idle state only) ───────────
        RowLayout {
            visible: !isVerifying && !isFlashing && !isDone && !isError
            spacing: 12
            Layout.fillWidth: true
            Rectangle {
                id: shieldBox
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

        // ── Summary panel (idle state) ────────────────────────────────
        Rectangle {
            visible: !isVerifying && !isFlashing && !isDone && !isError
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 1; height: 1; radius: parent.radius
                color: Qt.rgba(1, 1, 1, 0.04)
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12
                Loader {
                    active: needMaster; visible: active; Layout.fillWidth: true; sourceComponent: summaryRow
                    onLoaded: { item.roleLabel = "MASTER"; item.imagePath = wizardState.masterImagePath; item.driveId = wizardState.masterDriveId }
                }
                Loader {
                    active: needSlave; visible: active; Layout.fillWidth: true; sourceComponent: summaryRow
                    onLoaded: { item.roleLabel = "SLAVE"; item.imagePath = wizardState.slaveImagePath; item.driveId = wizardState.slaveDriveId }
                }
                Item { Layout.fillHeight: true }
                Rectangle {
                    Layout.fillWidth: true; height: 1
                    color: theme.colors.colorBorderWarn; opacity: 0.4
                }
                RowLayout {
                    spacing: 8
                    Text {
                        text: "⚠"; color: theme.colors.colorBorderWarn
                        font.family: Theme.fontTitle; font.pixelSize: 14
                    }
                    Text {
                        text: "ALL DATA ON THE TARGET DRIVE(S) WILL BE ERASED."
                        color: theme.colors.colorBorderWarn
                        font.family: Theme.fontTitle; font.pixelSize: 11
                        font.bold: true; font.letterSpacing: 1.4
                    }
                }
            }
        }

        // ── Error message (compact) ───────────────────────────────────
        Text {
            visible: isError && flashViewModel
            text: flashViewModel ? "✗ " + flashViewModel.errorMessage : ""
            color: theme.colors.colorBorderError
            font.family: Theme.fontBody; font.pixelSize: 12
            wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.topMargin: 4
        }
        Item { Layout.fillHeight: true }   // pushes the global bar to the bottom

        // ── Global progress bar (active across all live phases) ───────
        GlobalProgressBar {
            id: globalBar
            visible: isVerifying || isFlashing || isDone || isError
            Layout.fillWidth: true
            Layout.bottomMargin: 12
            value: _globalProgress()
            mode: _globalMode()
            label: _globalLabel()
            monotonic: true
            throughputBps: flashViewModel ? _throughput() : 0
        }
    }

    // ── Action bar ───────────────────────────────────────────────────
    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton {
            visible: isError
            text: "↻ RETRY"
            variant: "primary"
            horizontalPadding: 28
            onClicked: {
                flashViewModel.resetForNextCycle()
                confirmDialog.open()
            }
        }
        AstroButton { visible: !isVerifying && !isFlashing && !isDone; text: "← BACK"; variant: "secondary"; onClicked: wizardState.back() }
        AstroButton { visible: !isVerifying && !isFlashing && !isDone && !isError; text: "⚡ WRITE"; variant: "danger"; horizontalPadding: 28; onClicked: confirmDialog.open() }
        AstroButton { visible: isVerifying || isFlashing; text: "CANCEL"; variant: "secondary"; onClicked: flashViewModel.cancel() }
        AstroButton { visible: isDone; text: "NEXT →"; variant: "primary"; onClicked: wizardState.next() }
    }

    // ── Themed confirmation dialog (commit 8eaabc7) ──────────────────
    // 60px tinted header (sep. ⚠ glyph); 22/24 body padding; footer 1px
    // divider + 14 vpad; 2px destructive border (colorBorderError).
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
                    text: "ERASE TARGET DRIVE(S)?"
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
                ? "Image checksums will be verified, then the selected target SD card(s) will be ERASED and rewritten. This action is irreversible — confirm the drive letters above match the cards you intend to flash."
                : "The selected target SD card(s) will be ERASED and rewritten with the chosen image(s). This action is irreversible — confirm the drive letters above match the cards you intend to flash."
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
        // resetFloor() clears the GlobalProgressBar's monotonic floor so a
        // RETRY (same role → no onCurrentRoleChanged) doesn't keep the bar
        // pinned at the previous run's 100%.
        onAccepted: { if (globalBar) globalBar.resetFloor(); flashViewModel.startFromWizard() }
    }

    // ── Blocking "cancelling / restoring card" overlay ────────────────────
    // While a cancel winds down, the worker thread is still flushing and —
    // when the write had started — quick-formatting the card back to a clean
    // exFAT volume. Without a modal block the WRITE-ready view reappears the
    // instant CANCEL is clicked, so the operator could yank the card (or
    // re-flash) before the restore finishes. This modal covers the whole
    // window, eats all input, and cannot be dismissed; it auto-closes when
    // the worker reports done (status leaves "cancelling").
    Popup {
        id: cancelOverlay
        parent: Overlay.overlay
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        width: 520
        modal: true
        closePolicy: Popup.NoAutoClose
        padding: 0
        background: Rectangle {
            radius: Theme.radiusCard
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderIdle
            border.width: 1
        }
        contentItem: ColumnLayout {
            spacing: 16
            Item { Layout.preferredHeight: 8 }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 14
                BusyIndicator {
                    running: cancelOverlay.visible
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                }
                Text {
                    text: "CANCELLING"
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle; font.pixelSize: 16
                    font.bold: true; font.letterSpacing: 1.6
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 28; Layout.rightMargin: 28
                horizontalAlignment: Text.AlignHCenter
                text: flashViewModel.masterPhase === "restoring_card"
                    ? "Restoring the card to a clean, readable state…"
                    : "Stopping the write and cleaning up…"
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontBody; font.pixelSize: 13
                wrapMode: Text.Wrap; lineHeight: 1.35
            }
            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 28; Layout.rightMargin: 28
                Layout.bottomMargin: 10
                horizontalAlignment: Text.AlignHCenter
                text: "⚠ Do not remove the card."
                color: theme.colors.colorBorderError
                font.family: Theme.fontBody; font.pixelSize: 12; font.bold: true
            }
        }
        Connections {
            target: flashViewModel
            function onStatusChanged() {
                if (flashViewModel.status === "cancelling")
                    cancelOverlay.open()
                else
                    cancelOverlay.close()
            }
        }
    }
}
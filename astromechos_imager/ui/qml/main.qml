import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

ApplicationWindow {
    id: root
    // Old-school splash: while the splash shows (displayedStepIdx === -1)
    // the window matches the splash ARTWORK's aspect ratio so the image
    // fills it EXACTLY — no borders, no crop. The source PNG is 800×600 but
    // has ~71 px of pure-black bars baked into its top + bottom; we crop
    // those at render (sourceClipRect below) leaving 800×456 (≈1.754), so
    // the splash window is sized 982×560 (same ratio). It grows to the
    // wizard size the moment the first step appears.
    width:  displayedStepIdx >= 0 ? 960 : 982
    height: displayedStepIdx >= 0 ? 688 : 560
    minimumWidth: 760
    minimumHeight: 560
    visible: true
    title: "AstromechOS Imager"
    color: theme.colors.colorBg
    // Frameless: no native title bar — we draw our own header.
    flags: Qt.Window | Qt.FramelessWindowHint

    // Step labels: index 0 = splash; 1..7 mirror WizardState.currentStep.
    // Sequential Deployment Assistant: Landing → Config → Images →
    // Role → Ops (flash) → Cycle (insert next card) → Complete.
    readonly property var stepLabels: [
        "WELCOME",
        "01 / LANDING",
        "02 / CONFIG",
        "03 / IMAGES",
        "04 / ROLE",
        "05 / OPS",
        "06 / NEXT CARD",
        "07 / COMPLETE",
    ]
    // -1 while splash is showing, 0..6 = currentStep-1 once advanced.
    property int displayedStepIdx: -1

    // ── Quit guard (audit defect F4) ──────────────────────────────────
    // Closing mid-flash used to fire aboutToQuit → enable_automount WHILE
    // the writer streamed (Windows could mount + probe the half-written
    // card) and killed the worker thread mid-write, leaving a RAW card
    // with no exFAT recovery. Intercept close, confirm, cancel cleanly,
    // and only quit once the worker has wound down.
    property bool quitPending: false
    readonly property bool flashBusy: flashViewModel
        && (flashViewModel.status === "verifying"
            || flashViewModel.status === "flashing"
            || flashViewModel.status === "cancelling")

    onClosing: (close) => {
        if (flashBusy) {
            close.accepted = false
            quitConfirmDialog.open()
        }
    }

    Connections {
        target: flashViewModel
        function onStatusChanged() {
            if (root.quitPending && !root.flashBusy)
                Qt.quit()
        }
    }

    Dialog {
        id: quitConfirmDialog
        modal: true
        anchors.centerIn: parent
        title: "Flash in progress"
        standardButtons: Dialog.Yes | Dialog.No
        Text {
            text: "A card is being written. Cancel the flash and quit?\n" +
                  "The card will be recovered to a clean exFAT volume first."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
        onAccepted: {
            root.quitPending = true
            if (flashViewModel.status === "verifying"
                    || flashViewModel.status === "flashing")
                flashViewModel.cancel()
            // already "cancelling": just wait for onStatusChanged
        }
    }

    // ── Custom header (drag region + controls) ────────────────────────
    header: Rectangle {
        id: headerBar
        height: 60
        // Hidden during the splash so the splash screen is JUST the image
        // (old-school standalone splash, no app chrome). Appears once the
        // wizard starts (displayedStepIdx leaves -1). ApplicationWindow
        // reclaims the space for the content while hidden.
        visible: root.displayedStepIdx >= 0
        color: theme.colors.colorHeader

        // Hairline bottom border
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1; color: theme.colors.colorDivider
        }

        // Drag handler covers the whole bar — children that intercept
        // events (the window-control buttons) opt-out via their own
        // MouseAreas.
        DragHandler {
            target: null
            grabPermissions: PointerHandler.CanTakeOverFromAnything
            onActiveChanged: if (active) root.startSystemMove()
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 8
            spacing: 14

            // R2 pastille
            Rectangle {
                width: 30; height: 30; radius: 15
                color: "transparent"
                border.color: theme.colors.colorAccent
                border.width: 1.5
                Layout.alignment: Qt.AlignVCenter
                // Inner dot — "active LED"
                Rectangle {
                    anchors.centerIn: parent
                    width: 8; height: 8; radius: 4
                    color: theme.colors.colorAccent
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: true
                    NumberAnimation { to: 0.55; duration: 1400; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.00; duration: 1400; easing.type: Easing.InOutSine }
                }
            }
            ColumnLayout {
                spacing: 1
                Layout.alignment: Qt.AlignVCenter
                Text {
                    text: "ASTROMECHOS IMAGER"
                    color: theme.colors.colorTextOnChrome
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 2.2
                }
                Text {
                    text: root.displayedStepIdx >= 0 ? root.stepLabels[root.displayedStepIdx + 1] : root.stepLabels[0]
                    color: theme.colors.colorAccent   // accent ressort assez sur le chrome sombre
                    font.family: Theme.fontSubtitle
                    font.pixelSize: 10
                    font.letterSpacing: 1.8
                }
            }

            Item { Layout.fillWidth: true }   // spacer

            // ── Animated step pips ────────────────────────────────────
            Row {
                spacing: 8
                visible: root.displayedStepIdx >= 0
                Repeater {
                    model: 7
                    delegate: Item {
                        width: 18; height: 18
                        Rectangle {
                            id: dot
                            anchors.centerIn: parent
                            readonly property bool isActive:    index === root.displayedStepIdx
                            readonly property bool isCompleted: index <  root.displayedStepIdx
                            width: isActive ? 14 : 9
                            height: width
                            radius: width / 2
                            color: isActive    ? theme.colors.colorAccent
                                 : isCompleted ? theme.colors.colorAccentDim
                                 :                theme.colors.colorChromePipInactive
                            border.color: isActive ? theme.colors.colorAccentBright : "transparent"
                            border.width: isActive ? 1 : 0
                            Behavior on color  { ColorAnimation  { duration: Theme.durBase } }
                            Behavior on width  { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                            Behavior on height { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                        }
                        // Soft glow halo around the active pip
                        Rectangle {
                            anchors.centerIn: parent
                            width: dot.isActive ? 22 : 0
                            height: width
                            radius: width / 2
                            color: theme.colors.colorAccent
                            opacity: dot.isActive ? 0.22 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                            Behavior on width   { NumberAnimation { duration: Theme.durBase } }
                            z: -1
                        }
                    }
                }
            }

            Item { Layout.preferredWidth: 16 }   // separator

            // ── Theme toggle (sun/moon) ──────────────────────────────
            // Audit High #25: every icon-only header button now carries
            // a tooltipText + accessibleName so screen readers, sighted
            // keyboard users, and hover-discovery all work.
            WindowCtrlButton {
                Layout.alignment: Qt.AlignVCenter
                glyph: theme.mode === "light" ? "☾" : "☀"
                tooltipText: theme.mode === "light"
                    ? "Switch to dark theme"
                    : "Switch to light theme"
                accessibleName: tooltipText
                onActivated: theme.toggle()
            }

            // ── Window controls ──────────────────────────────────────
            // Only Close — Minimize and Maximize intentionally omitted
            // (single-purpose imaging session; no need to background it
            // or reflow the layout). The X glyph is sized up to fill the
            // visual slot the two missing buttons used to occupy.
            WindowCtrlButton {
                Layout.alignment: Qt.AlignVCenter
                glyph: "×"
                glyphSize: 24
                closeStyle: true
                tooltipText: "Close"
                accessibleName: "Close window"
                // Route through close() so the onClosing quit-guard can
                // intercept a mid-flash exit (Qt.quit() would bypass it).
                onActivated: root.close()
            }
        }
    }

    // ── Custom footer ────────────────────────────────────────────────
    footer: Rectangle {
        height: 28
        visible: root.displayedStepIdx >= 0   // hidden during splash (see header)
        color: theme.colors.colorHeader
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            height: 1; color: theme.colors.colorDivider
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            Text {
                text: "v" + appVersion + " · BUILD READY"
                color: theme.colors.colorTextOnChromeDim
                font.family: Theme.fontSubtitle
                font.pixelSize: 9
                font.letterSpacing: 1.5
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "ASTROMECHOS © 2026 · GPLv3"
                color: theme.colors.colorTextOnChromeDim
                font.family: Theme.fontSubtitle
                font.pixelSize: 9
                font.letterSpacing: 1.5
            }
        }
    }

    // ── Wizard step components ───────────────────────────────────────
    Component { id: splashComponent
        Item {
            id: splashRoot
            // 0 → 1 over the splash window; drives the fake module loader.
            property real progress: 0
            readonly property var modules: [
                "Initializing core subsystems",
                "Loading drive enumerator",
                "Mounting image codecs (xz / gz / zip)",
                "Arming flash engine",
                "Verifying vendor tools",
                "Ready",
            ]

            Image {
                anchors.fill: parent
                source: splashImageUrl
                // Crop the pure-black top/bottom bars baked into the PNG
                // (source is 800×600; real artwork is rows 71..527 = 800×456).
                sourceClipRect: Qt.rect(0, 71, 800, 456)
                fillMode: Image.PreserveAspectFit   // window matches 1.754 → exact fill
                smooth: true
                asynchronous: true
            }

            // ── Fake "loading modules" progress (old-school splash) ──────
            ColumnLayout {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 26
                width: Math.min(parent.width * 0.62, 540)
                spacing: 9

                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    // Step the module label across the bar's progress.
                    text: splashRoot.modules[Math.min(
                              splashRoot.modules.length - 1,
                              Math.floor(splashRoot.progress * splashRoot.modules.length))]
                          + (splashRoot.progress < 1 ? " …" : "")
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontMono   // boot-log / console vibe
                    font.pixelSize: 11
                    font.letterSpacing: 0.5
                    elide: Text.ElideRight
                }

                // Progress track + fill
                Rectangle {
                    Layout.fillWidth: true
                    height: 4
                    radius: 2
                    color: Qt.rgba(theme.colors.colorTextTertiary.r,
                                   theme.colors.colorTextTertiary.g,
                                   theme.colors.colorTextTertiary.b, 0.25)
                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        width: parent.width * splashRoot.progress
                        color: theme.colors.colorAccent
                    }
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: Math.round(splashRoot.progress * 100) + " %"
                    color: theme.colors.colorTextTertiary
                    font.family: Theme.fontMono
                    font.pixelSize: 10
                }
            }

            // Animate the bar across the splash — slow enough to actually
            // read the module names tick by (≈ 4 s, ~0.66 s per module).
            NumberAnimation on progress {
                from: 0; to: 1
                duration: 4000
                running: true
                easing.type: Easing.InOutCubic
            }
        }
    }
    // Sequential Deployment Assistant — 7-step wizard. Component
    // names follow the role of each screen (Landing / Config / Images
    // / Role / Flash / NextCard / Complete) rather than the legacy
    // mode-picker numbering.
    Component { id: step1Component; Step1Landing  {} }
    Component { id: step2Component; Step2Config   {} }
    Component { id: step3Component; Step3Images   {} }
    Component { id: step4Component; Step4Role     {} }
    Component { id: step5Component; Step5Flash    {} }
    Component { id: step6Component; Step6NextCard {} }
    Component { id: step7Component; Step7Complete {} }

    function _componentForStep(s) {
        switch (s) {
            case 1: return step1Component;
            case 2: return step2Component;
            case 3: return step3Component;
            case 4: return step4Component;
            case 5: return step5Component;
            case 6: return step6Component;
            case 7: return step7Component;
            default: return step1Component;
        }
    }

    StackView {
        id: stack
        anchors.fill: parent
        initialItem: splashComponent

        replaceEnter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0;  to: 1;  duration: Theme.durSlow; easing.type: Easing.OutCubic }
                NumberAnimation { property: "x";       from: 26; to: 0;  duration: Theme.durSlow; easing.type: Easing.OutCubic }
            }
        }
        replaceExit: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 1;  to: 0;   duration: Theme.durBase; easing.type: Easing.InCubic }
                NumberAnimation { property: "x";       from: 0;  to: -26; duration: Theme.durBase; easing.type: Easing.InCubic }
            }
        }
        pushEnter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durBase } }
        pushExit:  Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.durFast } }
    }

    // Auto-advance splash → current wizard step after the fake module
    // loader finishes (4000 ms animation + a short beat to read "Ready").
    Timer {
        interval: 4300
        running: true
        repeat: false
        onTriggered: {
            stack.replace(root._componentForStep(wizardState.currentStep))
            root.displayedStepIdx = wizardState.currentStep - 1
        }
    }

    Connections {
        target: wizardState
        function onCurrentStepChanged(s) {
            stack.replace(root._componentForStep(s))
            root.displayedStepIdx = s - 1
        }
    }

    // Audit Low #49: bigger corner grip (Win11 recommends ≥ 24 px hit
    // targets) PLUS invisible 4-pixel resize strips on every edge, so
    // users get the native expected resize behaviour even though
    // FramelessWindowHint killed native edge detection.
    Item {
        id: resizeEdges
        anchors.fill: parent
        z: 99

        // Top edge
        MouseArea {
            anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
            height: 4
            cursorShape: Qt.SizeVerCursor
            onPressed: root.startSystemResize(Qt.TopEdge)
        }
        // Bottom edge
        MouseArea {
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            height: 4
            cursorShape: Qt.SizeVerCursor
            onPressed: root.startSystemResize(Qt.BottomEdge)
        }
        // Left edge
        MouseArea {
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.left: parent.left
            width: 4
            cursorShape: Qt.SizeHorCursor
            onPressed: root.startSystemResize(Qt.LeftEdge)
        }
        // Right edge
        MouseArea {
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
            width: 4
            cursorShape: Qt.SizeHorCursor
            onPressed: root.startSystemResize(Qt.RightEdge)
        }
        // Corner grip — visible, 24×24 hit target.
        Rectangle {
            width: 24; height: 24
            anchors.bottom: parent.bottom; anchors.right: parent.right
            color: "transparent"
            Repeater {
                model: 3
                delegate: Rectangle {
                    width: 2; height: 2; radius: 1
                    color: theme.colors.colorTextTertiary
                    x: 10 + index * 4
                    y: 10 + index * 4
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SizeFDiagCursor
                onPressed: root.startSystemResize(Qt.BottomEdge | Qt.RightEdge)
            }
        }
    }
}

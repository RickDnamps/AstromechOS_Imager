import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

ApplicationWindow {
    id: root
    width: 920
    height: 640
    minimumWidth: 760
    minimumHeight: 560
    visible: true
    title: "AstromechOS Imager"
    color: theme.colors.colorBg
    // Frameless: no native title bar — we draw our own header.
    flags: Qt.Window | Qt.FramelessWindowHint

    // Step labels: index 0 = splash; 1..5 mirror WizardState.currentStep.
    // (Zero-Touch: step 4 "Customize" is gone — SSH keys are auto-injected.)
    readonly property var stepLabels: [
        "WELCOME",
        "01 / MODE",
        "02 / IMAGES",
        "03 / STORAGE",
        "04 / CONFIRM & FLASH",
        "05 / COMPLETE",
    ]
    // -1 while splash is showing, 0..4 = currentStep-1 once advanced.
    property int displayedStepIdx: -1

    // ── Custom header (drag region + controls) ────────────────────────
    header: Rectangle {
        id: headerBar
        height: 60
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
                    model: 5
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
            Row {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                WindowCtrlButton {
                    glyph: "—"
                    tooltipText: "Minimize"
                    accessibleName: "Minimize window"
                    onActivated: root.showMinimized()
                }
                WindowCtrlButton {
                    glyph: root.visibility === Window.Maximized ? "❐" : "▢"
                    tooltipText: root.visibility === Window.Maximized
                        ? "Restore"
                        : "Maximize"
                    accessibleName: tooltipText + " window"
                    onActivated: root.visibility = (root.visibility === Window.Maximized ? Window.Windowed : Window.Maximized)
                }
                WindowCtrlButton {
                    glyph: "×"
                    closeStyle: true
                    tooltipText: "Close"
                    accessibleName: "Close window"
                    onActivated: Qt.quit()
                }
            }
        }
    }

    // ── Custom footer ────────────────────────────────────────────────
    footer: Rectangle {
        height: 28
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
        Image {
            source: splashImageUrl
            fillMode: Image.PreserveAspectFit
            smooth: true
            asynchronous: true
        }
    }
    Component { id: step1Component; Step1Mode {} }
    Component { id: step2Component; Step2Images {} }
    Component { id: step3Component; Step3Storage {} }
    Component { id: step4Component; Step4Flash {} }
    Component { id: step5Component; Step5Done {} }

    function _componentForStep(s) {
        switch (s) {
            case 1: return step1Component;
            case 2: return step2Component;
            case 3: return step3Component;
            case 4: return step4Component;
            case 5: return step5Component;
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

    // Auto-advance splash → current wizard step after 1500 ms
    Timer {
        interval: 1500
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

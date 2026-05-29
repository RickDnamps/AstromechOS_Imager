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
    color: Theme.colorBg
    // Frameless: no native title bar — we draw our own header.
    flags: Qt.Window | Qt.FramelessWindowHint

    // Step labels: index 0 = splash; 1..6 mirror WizardState.currentStep.
    readonly property var stepLabels: [
        "WELCOME",
        "01 / MODE",
        "02 / IMAGES",
        "03 / STORAGE",
        "04 / CUSTOMIZE",
        "05 / CONFIRM & FLASH",
        "06 / COMPLETE",
    ]
    // -1 while splash is showing, 0..5 = currentStep-1 once advanced.
    property int displayedStepIdx: -1

    // ── Custom header (drag region + controls) ────────────────────────
    header: Rectangle {
        id: headerBar
        height: 60
        color: Theme.colorHeader

        // Hairline bottom border
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1; color: Theme.colorDivider
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
                border.color: Theme.colorAccent
                border.width: 1.5
                Layout.alignment: Qt.AlignVCenter
                // Inner dot — "active LED"
                Rectangle {
                    anchors.centerIn: parent
                    width: 8; height: 8; radius: 4
                    color: Theme.colorAccent
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
                    color: Theme.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 2.2
                }
                Text {
                    text: root.displayedStepIdx >= 0 ? root.stepLabels[root.displayedStepIdx + 1] : root.stepLabels[0]
                    color: Theme.colorTextAccent
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
                    model: 6
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
                            color: isActive    ? Theme.colorAccent
                                 : isCompleted ? Theme.colorAccentDim
                                 :                Theme.colorDivider
                            border.color: isActive ? Theme.colorAccentBright : "transparent"
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
                            color: Theme.colorAccent
                            opacity: dot.isActive ? 0.22 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                            Behavior on width   { NumberAnimation { duration: Theme.durBase } }
                            z: -1
                        }
                    }
                }
            }

            Item { Layout.preferredWidth: 16 }   // separator

            // ── Window controls ──────────────────────────────────────
            Row {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                WindowCtrlButton {
                    glyph: "—"
                    onActivated: root.showMinimized()
                }
                WindowCtrlButton {
                    glyph: root.visibility === Window.Maximized ? "❐" : "▢"
                    onActivated: root.visibility = (root.visibility === Window.Maximized ? Window.Windowed : Window.Maximized)
                }
                WindowCtrlButton {
                    glyph: "×"
                    closeStyle: true
                    onActivated: Qt.quit()
                }
            }
        }
    }

    // ── Custom footer ────────────────────────────────────────────────
    footer: Rectangle {
        height: 28
        color: Theme.colorHeader
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            height: 1; color: Theme.colorDivider
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            Text {
                text: "v" + appVersion + " · BUILD READY"
                color: Theme.colorTextTertiary
                font.family: Theme.fontSubtitle
                font.pixelSize: 9
                font.letterSpacing: 1.5
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "ASTROMECHOS © 2026 · GPLv3"
                color: Theme.colorTextTertiary
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
    Component { id: step4Component; Step4Customize {} }
    Component { id: step5Component; Step5Flash {} }
    Component { id: step6Component; Step6Done {} }

    function _componentForStep(s) {
        switch (s) {
            case 1: return step1Component;
            case 2: return step2Component;
            case 3: return step3Component;
            case 4: return step4Component;
            case 5: return step5Component;
            case 6: return step6Component;
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

    // Bottom-right corner resize grip — single-handle resize affordance
    // since FramelessWindowHint kills native edge detection.
    Rectangle {
        width: 14; height: 14
        anchors.bottom: parent.bottom; anchors.right: parent.right
        color: "transparent"
        z: 99
        // Visual: two diagonal dashes
        Repeater {
            model: 2
            delegate: Rectangle {
                width: 1.5; height: 1.5; radius: 0.75
                color: Theme.colorTextTertiary
                x: 6 + index * 4
                y: 6 + index * 4
            }
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeFDiagCursor
            onPressed: root.startSystemResize(Qt.BottomEdge | Qt.RightEdge)
        }
    }
}

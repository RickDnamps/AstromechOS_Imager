import QtQuick
import QtQuick.Controls
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 800
    height: 600
    visible: true
    title: "AstromechOS Imager"
    color: "#101418"

    // Step components — created lazily so QML errors in one don't kill startup.
    // Root items intentionally do NOT set anchors.fill: parent — StackView
    // manages their geometry by setting width/height directly.
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
    }

    // Auto-advance splash → current wizard step after 1500 ms
    Timer {
        interval: 1500
        running: true
        repeat: false
        onTriggered: stack.replace(root._componentForStep(wizardState.currentStep))
    }

    Connections {
        target: wizardState
        function onCurrentStepChanged(s) {
            stack.replace(root._componentForStep(s));
        }
    }
}

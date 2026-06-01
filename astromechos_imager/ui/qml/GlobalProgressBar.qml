// GlobalProgressBar.qml — single, always-visible progress bar.
//
// Two modes:
//   * "determinate"   — animated fill 0..1, percent label above
//   * "indeterminate" — animated stripe + free-form label above
//
// Monotonic guard prevents visual regressions when phase math briefly
// emits a smaller fraction (e.g. transitioning from verify 100% to
// customizing where we only have "elapsed time"). Caller resets the
// floor via resetFloor() between cycles.
import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: root

    // ── Public surface ────────────────────────────────────────────────
    property real value: 0                    // 0..1
    property string mode: "determinate"        // "determinate" | "indeterminate"
    property string label: ""                 // shown when indeterminate
    property bool monotonic: true             // bar never goes backward

    // ── Internals ─────────────────────────────────────────────────────
    property real _floor: 0

    function resetFloor() { _floor = 0 }

    onValueChanged: {
        if (monotonic) _floor = Math.max(_floor, value)
        else           _floor = value
    }

    implicitHeight: 28

    // ── Percent / label overlay (above the bar) ───────────────────────
    Text {
        id: overlayLabel
        anchors.right: parent.right
        anchors.bottom: track.top
        anchors.bottomMargin: 4
        text: mode === "indeterminate"
              ? label
              : Math.round(_floor * 100) + " %"
        font.family: Theme.fontMono
        font.pixelSize: 11
        color: theme.colors.colorTextSecondary
    }

    // ── Track ─────────────────────────────────────────────────────────
    Rectangle {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 8
        radius: 4
        color: theme.colors.colorBorderIdle
        clip: true

        // Determinate fill
        Rectangle {
            id: fill
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * Math.min(1.0, root._floor)
            radius: 4
            color: theme.colors.colorAccent
            visible: root.mode === "determinate"
            Behavior on width {
                NumberAnimation { duration: 300; easing.type: Easing.OutQuad }
            }
        }

        // Indeterminate moving stripe
        Rectangle {
            id: stripe
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.max(40, parent.width * 0.25)
            radius: 4
            color: theme.colors.colorAccent
            opacity: 0.7
            visible: root.mode === "indeterminate"
            x: -width
            NumberAnimation on x {
                from: -stripe.width
                to: track.width
                duration: 1100
                loops: Animation.Infinite
                running: stripe.visible
            }
        }
    }
}

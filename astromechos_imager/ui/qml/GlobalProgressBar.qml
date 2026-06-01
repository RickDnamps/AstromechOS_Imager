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
    // Live write/verify bandwidth, bytes/sec. 0 => badge hidden (no
    // sample yet, or non-bandwidth phase like preparing/customizing).
    property real throughputBps: 0

    // ── Internals ─────────────────────────────────────────────────────
    property real _floor: 0

    function resetFloor() { _floor = 0 }

    // Format bytes/sec as "X.X Mo/s". Returns "" for values too small
    // to be meaningful — the overlay row hides the badge in that case
    // so we don't print "0.0 Mo/s" during preparing / customizing.
    function _formatSpeed(bps) {
        if (bps <= 0) return ""
        var mbps = bps / (1024 * 1024)
        if (mbps < 0.1) return ""
        return mbps.toFixed(1) + " Mo/s"
    }

    onValueChanged: {
        if (monotonic) _floor = Math.max(_floor, value)
        else           _floor = value
    }

    implicitHeight: 28

    // ── Speed badge (left of percent) ─────────────────────────────────
    Text {
        id: speedLabel
        anchors.right: overlayLabel.left
        anchors.rightMargin: 6
        anchors.bottom: track.top
        anchors.bottomMargin: 4
        // Hidden when no sample (0 bps), when format would underflow,
        // and during the indeterminate phase (no real bytes flowing —
        // the stripe is purely decorative).
        property string _speedText: root.mode === "indeterminate"
                                    ? ""
                                    : root._formatSpeed(root.throughputBps)
        visible: _speedText.length > 0
        text: _speedText.length > 0 ? (_speedText + " ·") : ""
        font.family: Theme.fontMono
        font.pixelSize: 11
        color: theme.colors.colorTextSecondary
        opacity: visible ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200 } }
    }

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

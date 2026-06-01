// TaskTracker.qml — read-only visualization of sequential task stages.
//
// Pure derivation: caller owns `stages` and mutates it; this view re-renders.
// No internal state. Status: "pending" | "active" | "done" | "skipped" | "failed".
import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

ColumnLayout {
    id: root

    // Each element: { label: string, status: string, detail: string }
    // detail is optional. Unknown status falls through to pending visual.
    property var stages: []

    spacing: 10

    Repeater {
        model: root.stages
        delegate: RowLayout {
            Layout.fillWidth: true
            spacing: 14
            implicitHeight: 28

            // ── Status icon (fixed 28px column) ──
            Item {
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                Layout.alignment: Qt.AlignVCenter

                // Glyph variant: done / failed / pending / skipped
                Text {
                    anchors.centerIn: parent
                    visible: modelData.status !== "active"
                    text: modelData.status === "done"    ? "✓"
                        : modelData.status === "failed"  ? "✗"
                        : modelData.status === "skipped" ? "—"
                        :                                  "○"
                    font.pixelSize: (modelData.status === "done" || modelData.status === "failed") ? 18 : 16
                    font.bold: (modelData.status === "done" || modelData.status === "failed")
                    color: modelData.status === "done"   ? theme.colors.colorAccent
                         : modelData.status === "failed" ? theme.colors.colorBorderError
                         :                                 theme.colors.colorTextSecondary
                    opacity: (modelData.status === "pending" || modelData.status === "skipped") ? 0.45 : 1.0
                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                }

                // Active variant: rotating ring spinner
                Rectangle {
                    anchors.centerIn: parent
                    visible: modelData.status === "active"
                    width: 16; height: 16
                    radius: 8
                    color: "transparent"
                    border.color: theme.colors.colorAccent
                    border.width: 2
                    Rectangle {
                        width: 4; height: 4; radius: 2
                        color: theme.colors.colorAccent
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.topMargin: -1
                    }
                    RotationAnimator on rotation {
                        from: 0; to: 360; duration: 1500
                        loops: Animation.Infinite; running: true
                    }
                }
            }

            // ── Stage label (content-sized, so the detail can sit right
            //    next to it instead of being shoved to the far right) ──
            Text {
                Layout.alignment: Qt.AlignVCenter
                Layout.maximumWidth: parent.width * 0.62   // elide ultra-long labels
                elide: Text.ElideRight
                text: modelData.label || ""
                font.family: Theme.fontBody
                font.pixelSize: 13
                font.bold: modelData.status === "active" || modelData.status === "failed"
                color: modelData.status === "failed" ? theme.colors.colorBorderError
                     : (modelData.status === "active" || modelData.status === "done")
                        ? theme.colors.colorTextPrimary
                        : theme.colors.colorTextSecondary
                opacity: (modelData.status === "pending" || modelData.status === "skipped") ? 0.55 : 1.0
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
            }

            // ── Detail (the %) — sits RIGHT AFTER the label for readability ──
            Text {
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: 6
                text: modelData.detail || ""
                visible: text !== ""
                font.family: Theme.fontMono
                font.pixelSize: 11
                font.bold: modelData.status === "active"
                color: modelData.status === "active" ? theme.colors.colorTextAccent
                                                      : theme.colors.colorTextSecondary
            }

            // Spacer absorbs the remaining width, keeping label + detail left.
            Item { Layout.fillWidth: true }
        }
    }
}

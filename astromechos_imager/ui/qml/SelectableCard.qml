// SelectableCard — reusable card-style chooser with hover / pressed /
// selected states, glassmorphism look, and a flexible icon slot.
//
// Usage:
//   SelectableCard {
//       title: "Master"
//       subtitle: "Dome — 4 GB Pi 4B"
//       selected: wizardState.mode === "master_only"
//       onClicked: wizardState.setMode("master_only")
//       iconComponent: R2HeadIcon { }
//   }
//
// Pure visual component. Selection state and click handler are owned by
// the caller.
import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: card

    // ── Public API ────────────────────────────────────────────────────
    property string title: ""
    property string subtitle: ""
    property bool   selected: false
    property bool   enabledLook: true
    // Component for the left-side icon. Pass a `Component { R2HeadIcon {} }`
    // and we instantiate it via Loader (the Loader is what gets parented
    // into the layout, which is the only way that doesn't conflict with
    // the caller's QML scope).
    property Component iconComponent: null
    signal clicked()

    // ── Geometry ──────────────────────────────────────────────────────
    implicitHeight: 76
    Layout.fillWidth: true
    radius: Theme.radiusCard
    border.width: 1

    // ── State-derived styling ─────────────────────────────────────────
    readonly property bool _hover:   hoverArea.containsMouse && card.enabledLook
    readonly property bool _pressed: hoverArea.pressed       && card.enabledLook

    color: card.selected ? Theme.colorSurfaceAccent
         : card._pressed ? Theme.colorBg
         : card._hover   ? Theme.colorSurface2
         :                  Theme.colorSurface

    border.color: card.selected ? Theme.colorBorderAccent
                : card._hover   ? Theme.colorBorderHover
                :                  Theme.colorBorderIdle

    // Subtle scale lift on hover — micro-interaction
    scale: card._pressed ? 0.985
         : (card._hover && !card.selected) ? 1.012
         : 1.0

    opacity: card.enabledLook ? 1.0 : 0.45

    Behavior on color        { ColorAnimation  { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation  { duration: Theme.durFast } }
    Behavior on scale        { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
    Behavior on opacity      { NumberAnimation { duration: Theme.durBase } }

    // ── Glassmorphism: subtle top-edge highlight + soft inner gradient ─
    // Cheap fake-glass — a 1px highlight at top that reads as glass and
    // a faint diagonal gradient. No GPU blur cost, just paint.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        height: 1
        radius: parent.radius
        color: Qt.rgba(1, 1, 1, card.selected ? 0.08 : 0.04)
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: parent.radius - 1
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, card.selected ? 0.035 : 0.02) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.0) }
        }
    }

    // ── Selection indicator strip on the left edge ────────────────────
    Rectangle {
        width: 3
        height: parent.height - 16
        anchors.left: parent.left
        anchors.leftMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        radius: 1.5
        color: card.selected ? Theme.colorAccent : "transparent"
        opacity: card.selected ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: Theme.durBase } }

        // Soft glow when selected
        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 6
            height: parent.height
            radius: 4
            color: Theme.colorAccentGlow
            opacity: card.selected ? 0.22 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
            z: -1
        }
    }

    // ── Content ───────────────────────────────────────────────────────
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 22
        anchors.rightMargin: 18
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        spacing: 14

        // Icon slot — Loader instantiates the caller's Component when set.
        Loader {
            id: iconSlot
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            Layout.alignment: Qt.AlignVCenter
            active: card.iconComponent !== null
            sourceComponent: card.iconComponent
            visible: active
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 3

            Text {
                text: card.title
                color: Theme.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 15
                font.bold: true
                font.letterSpacing: 0.6
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Text {
                text: card.subtitle
                visible: card.subtitle.length > 0
                color: card.selected ? Theme.colorTextAccent : Theme.colorTextSecondary
                font.family: Theme.fontBody
                font.pixelSize: 12
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
        }

        // Right-side chevron-ish status dot — accent when selected.
        Rectangle {
            Layout.preferredWidth: 10
            Layout.preferredHeight: 10
            Layout.alignment: Qt.AlignVCenter
            radius: 5
            color: card.selected ? Theme.colorAccent : Theme.colorBorderIdle
            opacity: card.selected || card._hover ? 1.0 : 0.55
            Behavior on color   { ColorAnimation  { duration: Theme.durFast } }
            Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        }
    }

    MouseArea {
        id: hoverArea
        anchors.fill: parent
        hoverEnabled: card.enabledLook
        cursorShape: card.enabledLook ? Qt.PointingHandCursor : Qt.ForbiddenCursor
        enabled: card.enabledLook
        onClicked: card.clicked()
    }
}

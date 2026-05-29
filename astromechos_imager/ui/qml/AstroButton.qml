// AstroButton — unified action button matching the SelectableCard
// techno-droïde visual language (Orbitron caps, cyan-teal accents,
// scale-on-hover micro-interaction, glow on press).
//
// Variants:
//   "primary"   — filled accent, dark text. Use for the single primary CTA
//                 per screen (Next, Continue, Start).
//   "secondary" — outlined accent, accent text. Use for neutral actions
//                 (Back, Browse, Cancel).
//   "danger"    — filled red, white text. Use for destructive actions
//                 (WRITE, Erase, Delete).
//
// Optional `selected` flips a secondary into a filled accent look — used
// for toggle-style assignment buttons (Step 3 Master/Slave).
//
// Wraps QtQuick.Controls Button under the hood so it inherits proper
// focus/keyboard/accessibility behavior.
import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Button {
    id: btn

    property string variant: "primary"   // "primary" | "secondary" | "danger"
    property bool   selected: false       // toggle-fill for secondary

    // Defaults — callers can override `horizontalPadding` / `verticalPadding`
    // (built-in Control properties) directly without redeclaring them.
    padding: 0
    horizontalPadding: 22
    verticalPadding: 11

    font.family: Theme.fontTitle
    font.pixelSize: 11
    font.bold: true
    font.letterSpacing: 1.4

    hoverEnabled: enabled

    // ── Derived colors per variant + state ────────────────────────────
    readonly property color _bgIdle:
        variant === "primary"   ? theme.colors.colorAccent
      : variant === "danger"    ? theme.colors.colorBorderError
      : selected                ? theme.colors.colorSurfaceAccent
      :                            "transparent"

    readonly property color _bgHover:
        variant === "primary"   ? theme.colors.colorAccentBright
      : variant === "danger"    ? Qt.lighter(theme.colors.colorBorderError, 1.10)
      : selected                ? Qt.lighter(theme.colors.colorSurfaceAccent, 1.15)
      :                            theme.colors.colorSurface2

    readonly property color _bgPressed:
        variant === "primary"   ? theme.colors.colorAccentDim
      : variant === "danger"    ? Qt.darker(theme.colors.colorBorderError, 1.10)
      :                            theme.colors.colorBg

    readonly property color _borderIdle:
        variant === "primary"   ? theme.colors.colorAccent
      : variant === "danger"    ? theme.colors.colorBorderError
      : selected                ? theme.colors.colorBorderAccent
      :                            theme.colors.colorBorderIdle

    readonly property color _borderHover:
        variant === "primary"   ? theme.colors.colorAccentBright
      : variant === "danger"    ? Qt.lighter(theme.colors.colorBorderError, 1.20)
      :                            theme.colors.colorBorderAccent

    readonly property color _fgIdle:
        variant === "primary"   ? theme.colors.colorTextOnAccent
      : variant === "danger"    ? theme.colors.colorTextPrimary
      : selected                ? theme.colors.colorAccent
      :                            theme.colors.colorAccent

    background: Rectangle {
        radius: Theme.radiusButton
        border.width: 1
        color:         btn.enabled ? (btn.pressed ? btn._bgPressed     : btn.hovered ? btn._bgHover     : btn._bgIdle)
                                   : Qt.rgba(0.18, 0.20, 0.22, 0.35)
        border.color:  btn.enabled ? (btn.hovered ? btn._borderHover  : btn._borderIdle)
                                   : Qt.rgba(0.30, 0.34, 0.38, 0.5)
        Behavior on color        { ColorAnimation { duration: Theme.durFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

        // Glow halo on hover — only visible for filled variants.
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: btn.variant === "danger" ? theme.colors.colorBorderError : theme.colors.colorAccent
            opacity: btn.hovered && btn.enabled && (btn.variant === "primary" || btn.variant === "danger") ? 0.28 : 0
            z: -1
            Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        }
        // Subtle inner top highlight (glass)
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 1; height: 1
            radius: parent.radius
            color: Qt.rgba(1, 1, 1, 0.05)
            visible: btn.variant !== "secondary"
        }
    }

    contentItem: Text {
        text: btn.text
        font: btn.font
        color: btn.enabled ? btn._fgIdle : theme.colors.colorTextTertiary
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    scale: pressed && enabled ? 0.96
         : hovered && enabled ? 1.025
         : 1.0
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
}

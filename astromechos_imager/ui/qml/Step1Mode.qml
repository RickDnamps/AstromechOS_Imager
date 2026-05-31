import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    // Root sized by StackView — do NOT set anchors.fill here.
    color: theme.colors.colorBg

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 18
        width: 500

        Text {
            text: "WHAT DO YOU WANT TO FLASH?"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
            Layout.bottomMargin: 8
        }
        Text {
            text: "Pick the SD cards you need to (re)write. FLASH BOTH writes Master + Slave in the same session and needs 2 SD-USB adapters connected at the same time; pick MASTER ONLY or SLAVE ONLY to flash one card at a time with a single adapter."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 4
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        SelectableCard {
            title: "FLASH BOTH"
            subtitle: "Master + Slave in one session — needs 2 SD-USB adapters connected"
            selected: wizardState.mode === "both"
            onClicked: wizardState.setMode("both")
            iconComponent: Component { R2BothIcon { } }
        }
        SelectableCard {
            title: "MASTER ONLY"
            subtitle: "Re-flash the dome Pi 4B (4 GB) — Flask, dashboard, PCA9685"
            selected: wizardState.mode === "master_only"
            onClicked: wizardState.setMode("master_only")
            iconComponent: Component { R2HeadIcon { } }
        }
        SelectableCard {
            title: "SLAVE ONLY"
            subtitle: "Re-flash the body Pi 4B (2 GB) — UART listener, VESC, audio"
            selected: wizardState.mode === "slave_only"
            onClicked: wizardState.setMode("slave_only")
            iconComponent: Component { R2BodyIcon { } }
        }
    }

    // ── Footer navigation: Next ───────────────────────────────────────
    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        AstroButton {
            text: "NEXT →"
            variant: "primary"
            onClicked: wizardState.next()
        }
    }
}

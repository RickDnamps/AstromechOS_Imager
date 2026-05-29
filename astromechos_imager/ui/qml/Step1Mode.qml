import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    // Root sized by StackView — do NOT set anchors.fill here.
    color: Theme.colorBg

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 18
        width: 500

        Text {
            text: "WHAT DO YOU WANT TO FLASH?"
            color: Theme.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 18
            font.bold: true
            font.letterSpacing: 1.4
            Layout.bottomMargin: 8
        }
        Text {
            text: "Pick the SD cards you need to (re)write. The recommended path covers both."
            color: Theme.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            Layout.bottomMargin: 4
        }

        SelectableCard {
            title: "FLASH BOTH"
            subtitle: "Master + Slave SD cards in one session — recommended"
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

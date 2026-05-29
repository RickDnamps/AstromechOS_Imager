import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: Theme.colorBg

    property bool advancedOpen: false

    ScrollView {
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        clip: true

        ColumnLayout {
            width: parent.width - 56
            spacing: 18

            // ── Header ────────────────────────────────────────────────
            ColumnLayout {
                spacing: 4
                Text {
                    text: "CUSTOMIZE YOUR ASTROMECHOS PAIR"
                    color: Theme.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 18
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                Text {
                    text: "Set the SSH key required for first boot, then optionally tweak hostnames, fork URL and Wi-Fi."
                    color: Theme.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 12
                }
            }

            // ── REQUIRED — authorized_keys ───────────────────────────
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    text: "SSH PUBLIC KEY(S)"
                    color: Theme.colorTextSecondary
                    font.family: Theme.fontTitle
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.5
                }
                Text {
                    text: "Required — paste your ssh-ed25519 / ssh-rsa pubkey, one per line."
                    color: Theme.colorTextTertiary
                    font.family: Theme.fontBody
                    font.pixelSize: 11
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 130
                    radius: Theme.radiusCard
                    color: Theme.colorSurface
                    border.width: 1
                    border.color: keysArea.text === "" ? Theme.colorBorderIdle
                        : (wizardState.hasValidAuthorizedKey(keysArea.text) ? Theme.colorBorderAccent
                                                                            : Theme.colorBorderError)
                    Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

                    // Top edge highlight (glass)
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.margins: 1; height: 1; radius: parent.radius
                        color: Qt.rgba(1, 1, 1, 0.04)
                    }

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 8
                        TextArea {
                            id: keysArea
                            text: wizardState.authorizedKeys
                            color: Theme.colorTextPrimary
                            font.family: Theme.fontMono
                            font.pixelSize: 12
                            wrapMode: TextArea.NoWrap
                            selectByMouse: true
                            placeholderText: "ssh-ed25519 AAAA... user@host"
                            placeholderTextColor: Theme.colorTextTertiary
                            background: Rectangle { color: "transparent" }
                            onTextChanged: wizardState.setAuthorizedKeys(text)
                        }
                    }
                }
            }

            // ── ADVANCED (collapsible) ────────────────────────────────
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: advChevron.implicitHeight + 4
                Layout.topMargin: 4

                RowLayout {
                    id: advChevron
                    anchors.left: parent.left
                    spacing: 8

                    Text {
                        text: advancedOpen ? "▾" : "▸"
                        color: Theme.colorAccent
                        font.family: Theme.fontTitle
                        font.pixelSize: 14
                        Behavior on rotation { NumberAnimation { duration: Theme.durFast } }
                    }
                    Text {
                        text: "ADVANCED"
                        color: Theme.colorAccent
                        font.family: Theme.fontTitle
                        font.pixelSize: 11
                        font.bold: true
                        font.letterSpacing: 1.6
                    }
                    Rectangle {
                        Layout.preferredWidth: 200
                        Layout.preferredHeight: 1
                        Layout.leftMargin: 6
                        color: Theme.colorDivider
                        Layout.alignment: Qt.AlignVCenter
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: advancedOpen = !advancedOpen
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: advancedOpen
                spacing: 14

                AstroField {
                    label: "MASTER HOSTNAME"
                    text: wizardState.hostnameMaster
                    placeholderText: "astromech-master"
                    onEdited: wizardState.setHostnameMaster(value)
                }
                AstroField {
                    label: "SLAVE HOSTNAME"
                    text: wizardState.hostnameSlave
                    placeholderText: "astromech-slave"
                    onEdited: wizardState.setHostnameSlave(value)
                }
                AstroField {
                    label: "CUSTOM FORK URL"
                    text: wizardState.repoUrl
                    placeholderText: "https://github.com/.../AstromechOS.git (optional)"
                    onEdited: wizardState.setRepoUrl(value)
                }

                // ── Reuse toggles ─────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    spacing: 8
                    Repeater {
                        model: [
                            { label: "Reuse ed25519 keypair from previous run", get: function(){return wizardState.reusePairKey},  set: function(v){wizardState.setReusePairKey(v)} },
                            { label: "Reuse hotspot bootstrap from previous run", get: function(){return wizardState.reuseHotspot}, set: function(v){wizardState.setReuseHotspot(v)} },
                        ]
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            Rectangle {
                                id: box
                                Layout.preferredWidth: 18; Layout.preferredHeight: 18
                                radius: 4
                                color: modelData.get() ? Theme.colorAccent : "transparent"
                                border.color: modelData.get() ? Theme.colorAccent : Theme.colorBorderIdle
                                border.width: 1
                                Behavior on color        { ColorAnimation { duration: Theme.durFast } }
                                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                                Text {
                                    anchors.centerIn: parent
                                    text: "✓"
                                    color: Theme.colorTextOnAccent
                                    font.family: Theme.fontTitle
                                    font.pixelSize: 12
                                    font.bold: true
                                    visible: modelData.get()
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: modelData.set(!modelData.get())
                                }
                            }
                            Text {
                                text: modelData.label
                                color: Theme.colorTextPrimary
                                font.family: Theme.fontBody
                                font.pixelSize: 12
                                Layout.fillWidth: true
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: modelData.set(!modelData.get())
                                }
                            }
                        }
                    }
                }

                // ── Wi-Fi subsection ──────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 10
                    spacing: 6
                    Text {
                        text: "WI-FI (OPTIONAL — wlan1 home network)"
                        color: Theme.colorTextSecondary
                        font.family: Theme.fontTitle
                        font.pixelSize: 10
                        font.bold: true
                        font.letterSpacing: 1.5
                    }
                    Text {
                        text: "Configure le Wi-Fi domestique pour le dongle WLAN1. Laissé vide = aucun fichier généré."
                        color: Theme.colorTextTertiary
                        font.family: Theme.fontBody
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
                AstroField {
                    label: "SSID"
                    text: wizardState.wifiSsid
                    placeholderText: "MyHomeNetwork"
                    onEdited: wizardState.setWifiSsid(value)
                }
                AstroField {
                    label: "PASSWORD"
                    text: wizardState.wifiPsk
                    placeholderText: "WPA2 passphrase (8–63 chars)"
                    echoMode: TextInput.Password
                    onEdited: wizardState.setWifiPsk(value)
                }
            }
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton { text: "← BACK"; variant: "secondary"; onClicked: wizardState.back() }
        AstroButton {
            text: "NEXT →"
            variant: "primary"
            enabled: wizardState.hasValidAuthorizedKey(wizardState.authorizedKeys)
            onClicked: wizardState.next()
        }
    }
}

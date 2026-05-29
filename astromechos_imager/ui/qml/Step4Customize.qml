import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    // Root sized by StackView — no anchors.fill here
    color: "#1a1f24"

    property bool advancedOpen: false

    ScrollView {
        anchors.fill: parent
        anchors.bottomMargin: 72
        anchors.margins: 24
        clip: true

        ColumnLayout {
            width: parent.width - 48
            spacing: 16

            Text {
                text: "Customize your AstromechOS pair"
                color: "#e6e6e6"
                font.pixelSize: 22
            }

            // ── REQUIRED — authorized_keys ───────────────────────────
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: "Your SSH public key(s) — one per line"
                    color: "#e6e6e6"
                    font.pixelSize: 14
                    font.bold: true
                }
                Text {
                    text: "Paste your ssh-ed25519 / ssh-rsa pubkey. Required."
                    color: "#a0a4a8"
                    font.pixelSize: 12
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 120
                    color: "#262b30"
                    border.color: keysArea.text === "" ? "#3a3f44"
                        : (wizardState.hasValidAuthorizedKey(keysArea.text) ? "#5e9bd6" : "#c0533a")
                    border.width: 1
                    radius: 4
                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 4
                        TextArea {
                            id: keysArea
                            text: wizardState.authorizedKeys
                            color: "#e6e6e6"
                            font.family: "Consolas"
                            font.pixelSize: 12
                            wrapMode: TextArea.NoWrap
                            placeholderText: "ssh-ed25519 AAAA... user@host"
                            placeholderTextColor: "#5a5f64"
                            background: Rectangle { color: "transparent" }
                            onTextChanged: wizardState.setAuthorizedKeys(text)
                        }
                    }
                }
            }

            // ── ADVANCED (collapsible) ───────────────────────────────
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                spacing: 6
                Text {
                    text: advancedOpen ? "▾  Advanced" : "▸  Advanced"
                    color: "#a0c4e8"
                    font.pixelSize: 13
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: advancedOpen = !advancedOpen
                    }
                }
                Item { Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: advancedOpen
                spacing: 12

                // Hostname overrides
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text { text: "Master hostname:"; color: "#cfd2d5"; font.pixelSize: 12; Layout.preferredWidth: 130 }
                    TextField {
                        text: wizardState.hostnameMaster
                        Layout.fillWidth: true
                        onTextChanged: wizardState.setHostnameMaster(text)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text { text: "Slave hostname:"; color: "#cfd2d5"; font.pixelSize: 12; Layout.preferredWidth: 130 }
                    TextField {
                        text: wizardState.hostnameSlave
                        Layout.fillWidth: true
                        onTextChanged: wizardState.setHostnameSlave(text)
                    }
                }

                // Custom AstromechOS fork URL
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text { text: "Custom fork URL:"; color: "#cfd2d5"; font.pixelSize: 12; Layout.preferredWidth: 130 }
                    TextField {
                        text: wizardState.repoUrl
                        Layout.fillWidth: true
                        placeholderText: "https://github.com/.../AstromechOS.git (optional)"
                        onTextChanged: wizardState.setRepoUrl(text)
                    }
                }

                // Reuse toggles
                CheckBox {
                    text: "Reuse ed25519 keypair from previous run"
                    checked: wizardState.reusePairKey
                    onToggled: wizardState.setReusePairKey(checked)
                }
                CheckBox {
                    text: "Reuse hotspot bootstrap from previous run"
                    checked: wizardState.reuseHotspot
                    onToggled: wizardState.setReuseHotspot(checked)
                }

                // Spacer
                Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }

                // ── Wi-Fi block ────────────────────────────────────────────────
                Text {
                    text: "Wi-Fi (optional — wlan1 home network)"
                    color: "#a0c4e8"
                    font.pixelSize: 13
                    font.bold: true
                    Layout.topMargin: 6
                }
                Text {
                    text: "Configure le Wi-Fi domestique pour le dongle WLAN1. Laissé vide = aucun fichier généré."
                    color: "#a0a4a8"
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text { text: "SSID:"; color: "#cfd2d5"; font.pixelSize: 12; Layout.preferredWidth: 130 }
                    TextField {
                        text: wizardState.wifiSsid
                        Layout.fillWidth: true
                        placeholderText: "MyHomeNetwork"
                        onTextChanged: wizardState.setWifiSsid(text)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text { text: "Password:"; color: "#cfd2d5"; font.pixelSize: 12; Layout.preferredWidth: 130 }
                    TextField {
                        text: wizardState.wifiPsk
                        Layout.fillWidth: true
                        placeholderText: "WPA2 passphrase (8–63 chars)"
                        echoMode: TextInput.Password
                        onTextChanged: wizardState.setWifiPsk(text)
                    }
                }
            }
        }
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 12
        Button { text: "Back"; onClicked: wizardState.back() }
        Button {
            text: "Next"
            enabled: wizardState.hasValidAuthorizedKey(wizardState.authorizedKeys)
            onClicked: wizardState.next()
        }
    }
}

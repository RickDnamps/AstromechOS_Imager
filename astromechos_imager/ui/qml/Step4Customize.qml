// AstromechOS Imager — Step 4 "Customize".
//
// Captures the operator inputs needed for cold rootfs surgery
// (UID-1000 account) and dual-WLAN provisioning (domestic Wi-Fi on
// wlan1 + private hotspot PSK for wlan0). NEXT is hard-gated on the
// required-field validators.
//
// Field layout (3 grouped cards):
//   1. Linux account (UID-1000) — username + password (required)
//   2. Domestic Wi-Fi (wlan1)   — SSID + PSK (optional, must be
//                                  fully provided or fully empty)
//   3. Private Robot Hotspot    — PSK only (required); the SSID is
//      (wlan0 bootstrap)         auto-generated per burn by the
//                                Imager (Astromech-XXXX) and is
//                                NOT exposed for editing.
//
// Layout discipline: every card uses
// ``Layout.preferredHeight: innerColumn.implicitHeight + 2*padding``
// so the outer ColumnLayout can stack the cards without overlap.
// (A bare ``ColumnLayout { anchors.fill: parent }`` does NOT export
//  implicitHeight upward — the parent Rectangle would collapse to 0.)
//
// Visual: Orbitron everywhere (per feedback-orbitron memory),
// soft glassmorphic field surfaces, focus-visible accent borders,
// live ✓/✗ validity glyphs at the row's right edge.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    color: theme.colors.colorBg

    // ── Live validity (cached per keystroke so visuals + NEXT gate stay in sync) ──
    property bool installUserOk:       wizardState.isValidInstallUser(userField.text)
    property bool installPasswordOk:   wizardState.isValidInstallPassword(passField.text)
    property bool wifiSsidOk:          wizardState.isValidWifiSsid(wifiSsidField.text)
    property bool wifiPskOk:           wizardState.isValidWifiPsk(wifiPskField.text)
    property bool hotspotPasswordOk:   wizardState.isValidHotspotPassword(hotspotField.text)

    property bool wifiPairAllEmpty:    wifiSsidField.text === "" && wifiPskField.text === ""
    property bool wifiPairValid:       wifiPairAllEmpty || (wifiSsidOk && wifiPskOk)

    property bool formValid:           installUserOk
                                    && installPasswordOk
                                    && hotspotPasswordOk
                                    && wifiPairValid

    function _flush() {
        wizardState.setInstallUser(userField.text)
        wizardState.setInstallPassword(passField.text)
        wizardState.setWifiSsid(wifiSsidField.text)
        wizardState.setWifiPsk(wifiPskField.text)
        wizardState.setHotspotPassword(hotspotField.text)
    }

    Component.onCompleted: {
        userField.text     = wizardState.installUser
        passField.text     = wizardState.installPassword
        wifiSsidField.text = wizardState.wifiSsid
        wifiPskField.text  = wizardState.wifiPsk
        hotspotField.text  = wizardState.hotspotPassword
    }

    // ── Reusable themed field (label row + input rectangle + helper) ──
    component AstroField: ColumnLayout {
        id: field
        spacing: 5
        Layout.fillWidth: true

        property alias text: input.text
        property alias placeholder: input.placeholderText
        property alias echoMode: input.echoMode
        property string label: ""
        property string helper: ""
        property bool ok: false
        property bool optional: false
        signal edited()

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: field.label
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 11
                font.bold: true
                font.letterSpacing: 1.4
            }
            Item { Layout.fillWidth: true }
            Text {
                readonly property bool showInvalid:
                    !field.ok && (field.optional ? input.text !== "" : true)
                text: field.ok ? "✓" : showInvalid ? "✗" : "·"
                color: field.ok ? theme.colors.colorAccent
                     : showInvalid ? theme.colors.colorBorderError
                     :               theme.colors.colorTextTertiary
                font.family: Theme.fontTitle
                font.pixelSize: 14
                font.bold: true
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            radius: Theme.radiusButton
            color: theme.colors.colorBg
            readonly property color _borderResting:
                  field.ok                              ? theme.colors.colorBorderAccent
                : (field.optional && input.text === "") ? theme.colors.colorBorderIdle
                : input.text === ""                     ? theme.colors.colorBorderIdle
                :                                          theme.colors.colorBorderError
            border.color: input.activeFocus ? theme.colors.colorAccentBright : _borderResting
            border.width: input.activeFocus ? 2 : 1
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.width { NumberAnimation { duration: Theme.durFast } }

            TextField {
                id: input
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                font.family: Theme.fontBody  // Orbitron — see feedback-orbitron memory
                font.pixelSize: 12
                color: theme.colors.colorTextPrimary
                placeholderTextColor: theme.colors.colorTextTertiary
                selectionColor: theme.colors.colorAccentDim
                selectedTextColor: theme.colors.colorTextPrimary
                background: Item {}
                verticalAlignment: TextInput.AlignVCenter
                onTextEdited: field.edited()
            }
        }

        Text {
            text: field.helper
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 11
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: field.helper !== ""
            lineHeight: 1.2
        }
    }

    // ── Reusable section card. The Rectangle's Layout.preferredHeight
    //    is bound to the inner ColumnLayout's implicitHeight so the
    //    outer form can stack cards without overlap.
    component SectionCard: Rectangle {
        id: card
        Layout.fillWidth: true
        Layout.preferredHeight: cardCol.implicitHeight + 20   // 10 top + 10 bottom

        property string title: ""
        property string subtitle: ""
        default property alias _children: cardCol.data

        color: theme.colors.colorSurface
        border.color: theme.colors.colorBorderIdle
        border.width: 1
        radius: Theme.radiusCard

        ColumnLayout {
            id: cardCol
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            // Section header — title + subtitle, no divider for compactness
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: card.title
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontTitle
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 1.8
                }
                Text {
                    text: card.subtitle
                    color: theme.colors.colorTextSecondary
                    font.family: Theme.fontBody
                    font.pixelSize: 11
                    visible: card.subtitle !== ""
                    wrapMode: Text.WordWrap
                    lineHeight: 1.2
                    Layout.fillWidth: true
                }
            }
        }
    }

    // ── Scrollable content (fits ≥ 560 px window per main.qml minH) ───
    Flickable {
        id: scroll
        anchors.fill: parent
        anchors.leftMargin: 28
        anchors.rightMargin: 28
        anchors.topMargin: 16
        anchors.bottomMargin: 64
        contentWidth: width
        contentHeight: form.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: form
            width: scroll.width
            spacing: 8

            // ── Page header ───────────────────────────────────────────
            // Title only — the page subtitle was redundant with the
            // per-section subtitles and ate 16 px of vertical real
            // estate that the 3rd card needs.
            Text {
                Layout.fillWidth: true
                text: "CUSTOMIZE DEPLOYMENT"
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 16
                font.bold: true
                font.letterSpacing: 1.4
            }

            // ── Section 1: Linux account ──────────────────────────────
            SectionCard {
                title: "LINUX ACCOUNT  ·  UID-1000"
                subtitle: "Account used to log into the robot."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    AstroField {
                        id: userField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        label: "USERNAME"
                        ok: installUserOk
                        onEdited: _flush()
                    }
                    AstroField {
                        id: passField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        label: "PASSWORD"
                        ok: installPasswordOk
                        echoMode: TextInput.Password
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 2: Domestic Wi-Fi (wlan1) ─────────────────────
            SectionCard {
                title: "EXTERNAL / DOMESTIC NETWORK  ·  wlan1"
                subtitle: "Optional — connects your robot to your home network."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    AstroField {
                        id: wifiSsidField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        label: "DOMESTIC Wi-Fi SSID"
                        placeholder: "Your home Wi-Fi name (optional)"
                        helper: "Leave both fields empty to skip."
                        ok: wifiSsidOk
                        optional: true
                        onEdited: _flush()
                    }
                    AstroField {
                        id: wifiPskField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        label: "Wi-Fi PASSWORD"
                        placeholder: "Your home Wi-Fi password"
                        ok: wifiPskOk
                        optional: true
                        echoMode: TextInput.Password
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 3: Private Robot Hotspot (wlan0) ──────────────
            SectionCard {
                title: "PRIVATE ROBOT HOTSPOT  ·  wlan0"
                subtitle: "Used by the two halves of the robot to find each other."

                AstroField {
                    id: hotspotField
                    label: "PRIVATE ROBOT HOTSPOT PASSWORD"
                    ok: hotspotPasswordOk
                    echoMode: TextInput.Password
                    onEdited: _flush()
                }
            }

            // bottom breathing room
            Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    // ── Navigation ────────────────────────────────────────────────────
    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 10
        AstroButton {
            text: "← BACK"
            variant: "secondary"
            onClicked: { _flush(); wizardState.back() }
        }
        AstroButton {
            text: "NEXT →"
            variant: "primary"
            enabled: formValid
            onClicked: { _flush(); wizardState.next() }
        }
    }
}

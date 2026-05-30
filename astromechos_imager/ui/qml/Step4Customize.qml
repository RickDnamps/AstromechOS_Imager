// AstromechOS Imager — Step 4 "Customize".
//
// Captures the operator inputs needed for cold rootfs surgery
// (UID-1000 account) and dual-WLAN provisioning (domestic Wi-Fi on
// wlan1 + private hotspot PSK for wlan0). The NEXT button is hard-
// gated on all required-field validators returning true; the WRITE
// button in Step 5 (Confirm & Flash) inherits the same validity.
//
// Field layout (3 grouped clusters):
//   1. Linux account (UID-1000) — username + password (required)
//   2. Domestic Wi-Fi (wlan1)   — SSID + PSK (optional, must be
//                                  fully provided or fully empty)
//   3. Private Robot Hotspot    — PSK only (required); the SSID is
//      (wlan0 bootstrap)         auto-generated per burn by the
//                                Imager (Astromech-XXXX) and is
//                                NOT exposed for editing.
//
// Visual: Orbitron everywhere (per feedback-orbitron memory),
// glassmorphic field surfaces, focus-visible accent borders,
// live ✓/✗ validity glyphs to the right of each label.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    color: theme.colors.colorBg

    // ── Live validity (cached per keystroke so visuals + NEXT gate stay in sync) ──
    property bool installUserOk:       wizardState.isValidInstallUser(userField.text)
    property bool installPasswordOk:   wizardState.isValidInstallPassword(passField.text)
    property bool wifiSsidOk:          wizardState.isValidWifiSsid(wifiSsidField.text)
    property bool wifiPskOk:           wizardState.isValidWifiPsk(wifiPskField.text)
    property bool hotspotPasswordOk:   wizardState.isValidHotspotPassword(hotspotField.text)

    // Domestic Wi-Fi is optional: accepted when BOTH empty, or both valid.
    property bool wifiPairAllEmpty:    wifiSsidField.text === "" && wifiPskField.text === ""
    property bool wifiPairValid:       wifiPairAllEmpty || (wifiSsidOk && wifiPskOk)

    property bool formValid:           installUserOk
                                    && installPasswordOk
                                    && hotspotPasswordOk
                                    && wifiPairValid

    // Push edits into wizardState the moment the operator types, so the
    // WRITE step downstream always sees fresh values.
    function _flush() {
        wizardState.setInstallUser(userField.text)
        wizardState.setInstallPassword(passField.text)
        wizardState.setWifiSsid(wifiSsidField.text)
        wizardState.setWifiPsk(wifiPskField.text)
        wizardState.setHotspotPassword(hotspotField.text)
    }

    // Hydrate from wizardState when the step is shown (Back → Next reuse).
    Component.onCompleted: {
        userField.text    = wizardState.installUser
        passField.text    = wizardState.installPassword
        wifiSsidField.text = wizardState.wifiSsid
        wifiPskField.text  = wizardState.wifiPsk
        hotspotField.text  = wizardState.hotspotPassword
    }

    // ── Reusable themed field ─────────────────────────────────────────
    component AstroField: ColumnLayout {
        id: field
        spacing: 6

        property alias text: input.text
        property alias placeholder: input.placeholderText
        property alias echoMode: input.echoMode
        property string label: ""
        property string helper: ""
        property bool ok: false
        // Optional: tag the field as "optional" so the empty case stays
        // visually neutral (no red border / no ✗ glyph).
        property bool optional: false

        // Always emit on every keystroke, so the parent's `_flush()` runs.
        signal edited()

        Layout.fillWidth: true

        RowLayout {
            spacing: 8
            Layout.fillWidth: true
            Text {
                text: field.label
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 11
                font.bold: true
                font.letterSpacing: 1.2
            }
            Item { Layout.fillWidth: true }
            Text {
                // Show ✓ when valid; ✗ only when invalid AND the user has
                // typed something (or the field is required and empty).
                readonly property bool showInvalid:
                    !field.ok && (field.optional ? input.text !== "" : true)
                text: field.ok ? "✓" : showInvalid ? "✗" : "·"
                color: field.ok ? theme.colors.colorAccent
                     : showInvalid ? theme.colors.colorBorderError
                     :               theme.colors.colorTextTertiary
                font.family: Theme.fontTitle
                font.pixelSize: 12
                font.bold: true
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            radius: Theme.radiusButton
            color: theme.colors.colorSurface
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
                font.pixelSize: 13
                color: theme.colors.colorTextPrimary
                placeholderTextColor: theme.colors.colorTextTertiary
                selectionColor: theme.colors.colorAccentDim
                selectedTextColor: theme.colors.colorTextPrimary
                background: Item {}
                verticalAlignment: TextInput.AlignVCenter
                // Right-click is intentionally swallowed for password
                // fields — no clipboard leak via copy-as-text.
                onTextEdited: field.edited()
            }
        }

        Text {
            text: field.helper
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 10
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: field.helper !== ""
        }
    }

    // ── Reusable section header ───────────────────────────────────────
    component SectionHeader: ColumnLayout {
        id: section
        property string title: ""
        property string subtitle: ""
        Layout.fillWidth: true
        spacing: 2
        Text {
            text: section.title
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 13
            font.bold: true
            font.letterSpacing: 1.6
        }
        Text {
            text: section.subtitle
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 11
            visible: section.subtitle !== ""
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    // ── Scrollable content (fits ≥ 560 px window per main.qml minH) ───
    Flickable {
        id: scroll
        anchors.fill: parent
        anchors.margins: 28
        anchors.bottomMargin: 88
        contentWidth: width
        contentHeight: form.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: form
            width: scroll.width
            spacing: 18

            // ── Page header ───────────────────────────────────────────
            Text {
                text: "CUSTOMIZE DEPLOYMENT"
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 18
                font.bold: true
                font.letterSpacing: 1.4
            }
            Text {
                text: "These values are written into the SD card BEFORE the Pi boots. " +
                      "The Linux account is renamed by COLD rootfs surgery; the wlan0 " +
                      "bootstrap SSID is auto-generated per burn."
                color: theme.colors.colorTextSecondary
                font.family: Theme.fontBody
                font.pixelSize: 12
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                Layout.bottomMargin: 4
            }

            // ── Section 1: Linux account ──────────────────────────────
            SectionHeader {
                title: "LINUX ACCOUNT (UID-1000)"
                subtitle: "Replaces the Golden Image's default user offline, via libext2fs."
            }
            Rectangle {
                Layout.fillWidth: true
                color: theme.colors.colorSurface
                border.color: theme.colors.colorBorderIdle
                border.width: 1
                radius: Theme.radiusCard
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.paddingCard
                    spacing: Theme.spacingCard
                    AstroField {
                        id: userField
                        label: "USERNAME"
                        placeholder: "e.g. artoo, deetoo, threepio"
                        helper: "Lowercase letters / digits / -_, max 32 chars, starts with a letter or _."
                        ok: installUserOk
                        onEdited: _flush()
                    }
                    AstroField {
                        id: passField
                        label: "PASSWORD"
                        placeholder: "≥ 8 ASCII printable characters"
                        helper: "Hashed with SHA512-CRYPT (5000 rounds) and written directly to /etc/shadow."
                        ok: installPasswordOk
                        echoMode: TextInput.Password
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 2: Domestic Wi-Fi (wlan1) ─────────────────────
            SectionHeader {
                title: "EXTERNAL / DOMESTIC NETWORK (wlan1 ONLY)"
                subtitle: "Optional — fill both fields or leave both empty. WPA2-PSK only."
            }
            Rectangle {
                Layout.fillWidth: true
                color: theme.colors.colorSurface
                border.color: theme.colors.colorBorderIdle
                border.width: 1
                radius: Theme.radiusCard
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.paddingCard
                    spacing: Theme.spacingCard
                    AstroField {
                        id: wifiSsidField
                        label: "DOMESTIC Wi-Fi SSID"
                        placeholder: "Your home / workshop network name"
                        helper: "1-32 UTF-8 bytes. Leave empty to skip domestic Wi-Fi entirely."
                        ok: wifiSsidOk
                        optional: true
                        onEdited: _flush()
                    }
                    AstroField {
                        id: wifiPskField
                        label: "Wi-Fi PASSWORD"
                        placeholder: "WPA2 passphrase"
                        helper: "8-63 ASCII printable characters."
                        ok: wifiPskOk
                        optional: true
                        echoMode: TextInput.Password
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 3: Private Robot Hotspot (wlan0) ──────────────
            SectionHeader {
                title: "PRIVATE ROBOT HOTSPOT (wlan0)"
                subtitle: "Master ↔ Slave rendezvous. SSID is auto-generated per burn " +
                          "(Astromech-XXXX); only the password is operator-controlled."
            }
            Rectangle {
                Layout.fillWidth: true
                color: theme.colors.colorSurface
                border.color: theme.colors.colorBorderIdle
                border.width: 1
                radius: Theme.radiusCard
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.paddingCard
                    spacing: Theme.spacingCard
                    AstroField {
                        id: hotspotField
                        label: "PRIVATE ROBOT HOTSPOT PASSWORD"
                        placeholder: "WPA2 passphrase for the wlan0 bootstrap AP"
                        helper: "8-63 ASCII printable characters. Carries through the firstboot handover " +
                                "to the final Astromech_Control_XXXX SSID — keep it secret."
                        ok: hotspotPasswordOk
                        echoMode: TextInput.Password
                        onEdited: _flush()
                    }
                }
            }
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

// AstromechOS Imager — Step 4 "Customize".
//
// Captures operator inputs for the UID-1000 account password (applied by
// cloud-init on the fixed `astromech` user — the USERNAME field is read-only)
// and dual-WLAN provisioning. NON-BLOCKING fallback: empty password / hotspot
// fields are silently substituted with the module-level DEFAULT_* constants
// (astropass / astropass) in
// ``flash_view_model._build_flash_job`` — the WRITE button is only
// gated on the "non-empty AND invalid" case (operator-typed garbage),
// never on the "empty" case (operator wants the default).
//
// Section order (per UX spec):
//   1. ROBOT LOGIN          — Linux UID-1000 (username + password)
//      + ⚠️ security warning band
//   2. INTERNAL ROBOT LINK  — wlan0 hotspot password
//   3. HOME Wi-Fi           — wlan1 SSID + PSK (optional, also
//                              configurable later from the robot's
//                              web UI)
//
// Visual: Orbitron everywhere (per feedback-orbitron memory),
// soft glassmorphic cards with proper Layout.preferredHeight wiring
// so sections don't collapse to 0 height.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    color: theme.colors.colorBg

    // ── Live validity (cached per keystroke) ─────────────────────────
    property bool installUserOk:     wizardState.isValidInstallUser(userField.text)
    property bool installPasswordOk: wizardState.isValidInstallPassword(passField.text)
    property bool wifiSsidOk:        wizardState.isValidWifiSsid(wifiSsidField.text)
    property bool wifiPskOk:         wizardState.isValidWifiPsk(wifiPskField.text)
    property bool hotspotPasswordOk: wizardState.isValidHotspotPassword(hotspotField.text)

    // Wi-Fi (wlan1) is optional: both empty OR both valid is accepted.
    property bool wifiPairAllEmpty:  wifiSsidField.text === "" && wifiPskField.text === ""
    property bool wifiPairValid:     wifiPairAllEmpty || (wifiSsidOk && wifiPskOk)

    // Non-blocking gate: empty fields use defaults; only typed garbage
    // blocks WRITE. Per-field formula: empty OR valid.
    property bool formValid:
           (userField.text    === "" || installUserOk)
        && (passField.text    === "" || installPasswordOk)
        && (hotspotField.text === "" || hotspotPasswordOk)
        && wifiPairValid

    function _flush() {
        wizardState.setInstallUser(userField.text)
        wizardState.setInstallPassword(passField.text)
        wizardState.setWifiSsid(wifiSsidField.text)
        wizardState.setWifiPsk(wifiPskField.text)
        wizardState.setHotspotPassword(hotspotField.text)
    }

    Component.onCompleted: {
        // Username is a fixed system constant, shown read-only. The flashed
        // login is DEFAULT_INSTALL_USER backend-side regardless of this value.
        userField.text     = "astromech"
        passField.text     = wizardState.installPassword
        wifiSsidField.text = wizardState.wifiSsid
        wifiPskField.text  = wizardState.wifiPsk
        hotspotField.text  = wizardState.hotspotPassword
    }

    // ── Reusable themed field (label row + input + helper) ──────────
    component AstroField: ColumnLayout {
        id: field
        spacing: 5
        Layout.fillWidth: true

        property alias text: input.text
        property alias placeholder: input.placeholderText
        property string label: ""
        property string helper: ""
        property bool ok: false
        // Optional fields stay neutral (no red ✗) when empty.
        property bool optional: false
        // Password fields set revealable: true → masked by default with a
        // 👁 toggle to reveal the text (so the operator can check for typos).
        property bool revealable: false
        property bool revealed: false
        // Locked fields are read-only: the value is a fixed system constant
        // (the standardized UID-1000 username) the operator cannot change.
        property bool locked: false
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
                    !field.ok && input.text !== ""
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
                  field.ok                      ? theme.colors.colorBorderAccent
                : input.text === ""             ? theme.colors.colorBorderIdle
                :                                  theme.colors.colorBorderError
            border.color: input.activeFocus ? theme.colors.colorAccentBright : _borderResting
            border.width: input.activeFocus ? 2 : 1
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.width { NumberAnimation { duration: Theme.durFast } }

            TextField {
                id: input
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: (field.revealable || field.locked) ? 38 : 12
                font.family: Theme.fontBody  // Orbitron — see feedback-orbitron memory
                font.pixelSize: 12
                // Locked (fixed) values render dimmed to read as non-editable.
                color: field.locked ? theme.colors.colorTextSecondary
                                     : theme.colors.colorTextPrimary
                placeholderTextColor: theme.colors.colorTextTertiary
                selectionColor: theme.colors.colorAccentDim
                selectedTextColor: theme.colors.colorTextPrimary
                background: Item {}
                verticalAlignment: TextInput.AlignVCenter
                readOnly: field.locked
                // Masked when revealable & not revealed; plain text otherwise.
                echoMode: (field.revealable && !field.revealed)
                          ? TextInput.Password : TextInput.Normal
                onTextEdited: field.edited()
            }

            // 🔒 fixed-value indicator — only on locked (read-only) fields.
            Text {
                visible: field.locked
                anchors.right: parent.right
                anchors.rightMargin: 11
                anchors.verticalCenter: parent.verticalCenter
                text: "🔒"
                font.pixelSize: 13
                color: theme.colors.colorTextTertiary
            }

            // 👁 reveal/hide toggle — only on password (revealable) fields.
            Text {
                visible: field.revealable
                anchors.right: parent.right
                anchors.rightMargin: 11
                anchors.verticalCenter: parent.verticalCenter
                text: field.revealed ? "🙈" : "👁"
                font.pixelSize: 15
                color: field.revealed ? theme.colors.colorAccent
                                      : theme.colors.colorTextTertiary
                opacity: eyeMouse.containsMouse ? 1.0 : 0.85
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                MouseArea {
                    id: eyeMouse
                    anchors.fill: parent
                    anchors.margins: -6      // bigger hit target
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: field.revealed = !field.revealed
                }
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

    // ── Reusable section card with auto-sizing ───────────────────────
    component SectionCard: Rectangle {
        id: card
        Layout.fillWidth: true
        Layout.preferredHeight: cardCol.implicitHeight + 20

        property string title: ""
        property string subtitle: ""
        // Optional pulsing ⚠ icon next to the title; clicking it opens
        // a popup with the warning text. Set to "" (default) to omit.
        property string warningText: ""
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

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        text: card.title
                        color: theme.colors.colorTextPrimary
                        font.family: Theme.fontTitle
                        font.pixelSize: 13
                        font.bold: true
                        font.letterSpacing: 1.8
                    }
                    // Reusable theme-aware Security note (⚠ + popup).
                    // The component is self-contained and only renders
                    // when warningText is non-empty.
                    SecurityNote {
                        objectName: card.title.replace(/[^A-Za-z]/g, "") + "SecNote"
                        Layout.alignment: Qt.AlignVCenter
                        warningText: card.warningText
                    }
                    Item { Layout.fillWidth: true }   // spacer
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

    // ── Scrollable content ───────────────────────────────────────────
    Flickable {
        id: scroll
        anchors.fill: parent
        anchors.leftMargin: 28
        anchors.rightMargin: 28
        anchors.topMargin: 14
        anchors.bottomMargin: 60
        contentWidth: width
        contentHeight: form.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: form
            width: scroll.width
            spacing: 10

            // ── Page title ────────────────────────────────────────────
            Text {
                Layout.fillWidth: true
                text: "CUSTOMIZE DEPLOYMENT"
                color: theme.colors.colorTextPrimary
                font.family: Theme.fontTitle
                font.pixelSize: 16
                font.bold: true
                font.letterSpacing: 1.4
            }

            // ── Section 1: Linux Account ─────────────────────────────
            // ⚠ Security note focuses on the credential-loss + sudo
            // implications. Click the inline link to read the full
            // text in a floating popup; the card's vertical footprint
            // is unchanged.
            SectionCard {
                title: "LINUX ACCOUNT"
                subtitle: "Robot login. Username is fixed (astromech); set a password or leave blank for the default."
                warningText: "Username and password grant SSH plus sudo access on the robot. " +
                             "If you change them and forget the new values, you will be locked " +
                             "out of the robot entirely — no remote SSH, no service restart, " +
                             "no recovery. Re-flashing the SD card with this Imager is the " +
                             "only way back. Use a password you can store safely."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    AstroField {
                        id: userField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "USERNAME"
                        // Fixed system account — read-only. The flashed login is
                        // always DEFAULT_INSTALL_USER (backend-authoritative);
                        // this display is locked to match.
                        locked: true
                        helper: "Fixed system account"
                        ok: installUserOk
                    }
                    AstroField {
                        id: passField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "PASSWORD"
                        placeholder: "astropass"
                        helper: "Used for SSH + sudo"
                        ok: installPasswordOk
                        revealable: true
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 2: Private Robot Hotspot ──────────────────────
            // Separate security note about default-password exposure
            // to nearby Wi-Fi range when operated in public spaces.
            SectionCard {
                title: "PRIVATE ROBOT HOTSPOT"
                subtitle: "Used by the two halves of the robot to find each other."
                warningText: "The default password 'astropass' is publicly known. " +
                             "If you keep it, anyone within Wi-Fi range of the robot " +
                             "(roughly 30 m / 100 ft) can join its private network and " +
                             "reach its services. Set a strong custom password if the " +
                             "robot will be operated at a convention, expo, or any " +
                             "public/shared space."

                // SSID (read-only, auto-generated) + password on one row —
                // same 2-column grid as the Linux account, so it stays compact
                // and aligned. SSID is bound to the single early-generated
                // source wizardState.hotspotSsid.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    AstroField {
                        id: hotspotSsidField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "HOTSPOT SSID"
                        locked: true
                        helper: "Auto-generated per deployment"
                        text: wizardState.hotspotSsid
                        ok: true
                    }
                    AstroField {
                        id: hotspotField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "HOTSPOT PASSWORD"
                        placeholder: "astropass"
                        helper: "Links Master ↔ Slave"
                        ok: hotspotPasswordOk
                        revealable: true
                        onEdited: _flush()
                    }
                }
            }

            // ── Section 3: Home Wi-Fi (optional) ──────────────────────
            SectionCard {
                title: "HOME Wi-Fi"
                subtitle: "Optional (wlan1) — also configurable later from the robot's web UI."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    AstroField {
                        id: wifiSsidField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "Wi-Fi NAME"
                        placeholder: "(leave empty to skip)"
                        ok: wifiSsidOk
                        optional: true
                        onEdited: _flush()
                    }
                    AstroField {
                        id: wifiPskField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        label: "Wi-Fi PASSWORD"
                        placeholder: "(leave empty to skip)"
                        ok: wifiPskOk
                        optional: true
                        revealable: true
                        onEdited: _flush()
                    }
                }
            }

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
            onClicked: {
                // The bootstrap SSID is minted at wizard-state init
                // (wizardState.hotspotSsid) and shown read-only above, so
                // there is nothing to "start" here — just persist the typed
                // fields and advance.
                _flush()
                wizardState.next()
            }
        }
    }
}

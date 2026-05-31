// AstromechOS Imager — Step 1 "Landing".
//
// Sequential Deployment Assistant entry screen. The operator clicks
// START DEPLOYMENT to generate the session-scoped hotspot SSID (one
// SSID baked into BOTH cards so the runtime master/slave handshake
// works without re-flashing) and then advance to Step 2 Config.
//
// FlashViewModel.startSession() is idempotent — going BACK to this
// screen mid-session and clicking START DEPLOYMENT again is a no-op
// on the SSID side.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    // Root sized by StackView — do NOT set anchors.fill here.
    color: theme.colors.colorBg

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 24
        width: 560

        // ── Splash / logo area ───────────────────────────────────────
        Image {
            source: splashImageUrl
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 180
            Layout.preferredHeight: 180
            fillMode: Image.PreserveAspectFit
            smooth: true
            asynchronous: true
        }

        Text {
            text: "ASTROMECHOS IMAGER"
            color: theme.colors.colorTextPrimary
            font.family: Theme.fontTitle
            font.pixelSize: 22
            font.bold: true
            font.letterSpacing: 2.0
            Layout.alignment: Qt.AlignHCenter
            horizontalAlignment: Text.AlignHCenter
        }

        Text {
            text: "SEQUENTIAL DEPLOYMENT ASSISTANT"
            color: theme.colors.colorTextAccent
            font.family: Theme.fontSubtitle
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 1.8
            Layout.alignment: Qt.AlignHCenter
            horizontalAlignment: Text.AlignHCenter
            Layout.bottomMargin: 6
        }

        Text {
            text: "Flash one card at a time. Configure once → deploy Master and Slave with a single shared hotspot SSID."
            color: theme.colors.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            horizontalAlignment: Text.AlignHCenter
        }

        // ── Session SSID preview (only after startSession() ran) ─────
        Rectangle {
            visible: flashViewModel.sessionSsid !== ""
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 360
            implicitHeight: 52
            color: theme.colors.colorSurface
            border.color: theme.colors.colorBorderAccent
            border.width: 1
            radius: Theme.radiusCard
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                Text {
                    text: "SESSION SSID"
                    color: theme.colors.colorTextAccent
                    font.family: Theme.fontTitle
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.4
                }
                Text {
                    text: flashViewModel.sessionSsid
                    color: theme.colors.colorTextPrimary
                    font.family: Theme.fontMono
                    font.pixelSize: 12
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        AstroButton {
            text: "START DEPLOYMENT →"
            variant: "primary"
            horizontalPadding: 28
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 8
            onClicked: {
                flashViewModel.startSession()
                wizardState.next()
            }
        }
    }
}

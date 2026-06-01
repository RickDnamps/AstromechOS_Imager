// AstromechOS Imager — Step 1 "Landing".
//
// Sequential Deployment Assistant entry screen. Pure marketing splash
// — the START DEPLOYMENT button advances to Step 2 Config and nothing
// else. Audit bug C1: previously this screen called
// flashViewModel.startSession(), which baked the SSID before Step 2
// captured the real PSK → SSID/PSK drift on the cards. The session
// hotspot is now minted at the end of Step 2 (Config NEXT button)
// once the PSK is validated.
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
        // The app title is already baked INTO the image, so we don't repeat
        // it as a Text below — the image is the hero, shown large (4:3).
        Image {
            source: splashImageUrl
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 460
            Layout.preferredHeight: 262   // 460 / 1.754 (clipped artwork ratio)
            // Crop the pure-black top/bottom bars baked into the PNG so the
            // landing shows the clean artwork (rows 71..527 = 800×456).
            sourceClipRect: Qt.rect(0, 71, 800, 456)
            fillMode: Image.PreserveAspectFit
            smooth: true
            asynchronous: true
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
                // Step 1 is a pure splash now — SSID is minted by
                // Step 2 Config NEXT (after the operator-typed PSK is
                // validated). Audit bug C1.
                wizardState.next()
            }
        }
    }
}

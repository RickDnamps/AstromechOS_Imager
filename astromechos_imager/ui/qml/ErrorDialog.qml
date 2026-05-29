import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Dialog {
    id: root
    title: titleText
    modal: true
    width: 580
    padding: 0
    anchors.centerIn: parent

    standardButtons: Dialog.Close

    property string titleText: ""
    property string message: ""
    property string hint: ""
    // Severity drives the accent border color. Keep the existing token names
    // because Python emits them verbatim from core/errors.py.
    property string sdState: "SAFE"         // SAFE | GARBAGE | UNCERTAIN | BOOTABLE_NO_FIRSTBOOT | OK
    property bool retryable: false
    property bool exportable: true

    signal retryRequested()
    signal exportRequested()

    function _accentColor() {
        switch (sdState) {
            case "GARBAGE":                 return Theme.colorBorderError
            case "UNCERTAIN":
            case "BOOTABLE_NO_FIRSTBOOT":   return Theme.colorBorderWarn
            case "OK":
            case "SAFE":                    return Theme.colorAccent
            default:                        return Theme.colorBorderIdle
        }
    }

    background: Rectangle {
        radius: Theme.radiusCard
        color: Theme.colorSurface
        border.color: root._accentColor()
        border.width: 1
        // Top glass highlight
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 1; height: 1; radius: parent.radius
            color: Qt.rgba(1, 1, 1, 0.04)
        }
    }

    header: Rectangle {
        color: "transparent"
        implicitHeight: 52
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            spacing: 12
            Text {
                text: root.sdState === "GARBAGE" ? "✗"
                    : root.sdState === "UNCERTAIN" || root.sdState === "BOOTABLE_NO_FIRSTBOOT" ? "⚠"
                    : "ℹ"
                color: root._accentColor()
                font.family: Theme.fontTitle
                font.pixelSize: 16
                font.bold: true
            }
            Text {
                text: root.titleText.toUpperCase()
                color: root._accentColor()
                font.family: Theme.fontTitle
                font.pixelSize: 13
                font.bold: true
                font.letterSpacing: 1.4
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            height: 1; color: Theme.colorDivider
        }
    }

    contentItem: ColumnLayout {
        spacing: 10
        Text {
            text: root.message
            color: Theme.colorTextPrimary
            font.family: Theme.fontBody
            font.pixelSize: 13
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            leftPadding: 20
            rightPadding: 20
            topPadding: 18
        }
        Text {
            visible: root.hint !== ""
            text: "→ " + root.hint
            color: Theme.colorTextSecondary
            font.family: Theme.fontBody
            font.pixelSize: 12
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            leftPadding: 20
            rightPadding: 20
        }
        Item { Layout.preferredHeight: 4 }
    }

    footer: RowLayout {
        spacing: 10
        Item { width: 18 }
        AstroButton {
            visible: root.retryable
            text: "RETRY"
            variant: "secondary"
            onClicked: root.retryRequested()
        }
        AstroButton {
            visible: root.exportable
            text: "EXPORT DIAGNOSTIC"
            variant: "secondary"
            onClicked: root.exportRequested()
        }
        Item { Layout.fillWidth: true }
        AstroButton {
            text: "CLOSE"
            variant: "primary"
            onClicked: root.reject()
        }
        Item { width: 18 }
    }
}

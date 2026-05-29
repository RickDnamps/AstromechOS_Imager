// AstroField — text input with inline Orbitron caps label and themed
// surface. Used wherever the wizard takes a single-line value (hostname,
// fork URL, wifi credentials, etc.).
//
// Usage:
//   AstroField {
//       label: "SSID"
//       text: wizardState.wifiSsid
//       placeholderText: "MyHomeNetwork"
//       onEdited: wizardState.setWifiSsid(value)
//   }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: field

    property string label: ""
    property alias  text:            input.text
    property alias  placeholderText: input.placeholderText
    property alias  echoMode:        input.echoMode
    property bool   valid: true
    signal edited(string value)

    implicitHeight: column.implicitHeight
    implicitWidth:  240
    Layout.fillWidth: true

    ColumnLayout {
        id: column
        anchors.fill: parent
        spacing: 4

        Text {
            visible: field.label.length > 0
            text: field.label
            color: Theme.colorTextSecondary
            font.family: Theme.fontTitle
            font.pixelSize: 10
            font.bold: true
            font.letterSpacing: 1.5
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 36
            radius: Theme.radiusButton
            color: Theme.colorSurface
            border.width: 1
            border.color: !field.valid              ? Theme.colorBorderError
                        : input.activeFocus         ? Theme.colorBorderAccent
                                                    : Theme.colorBorderIdle
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            TextField {
                id: input
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                color: Theme.colorTextPrimary
                placeholderTextColor: Theme.colorTextTertiary
                font.family: Theme.fontMono
                font.pixelSize: 12
                selectByMouse: true
                background: Rectangle { color: "transparent" }
                onTextEdited: field.edited(text)
            }
        }
    }
}

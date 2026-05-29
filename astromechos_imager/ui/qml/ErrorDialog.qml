import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    title: titleText
    modal: true
    width: 560
    standardButtons: Dialog.Close

    property string titleText: ""
    property string message: ""
    property string hint: ""
    property string sdState: "SAFE"         // SAFE | GARBAGE | UNCERTAIN | BOOTABLE_NO_FIRSTBOOT | OK
    property bool retryable: false
    property bool exportable: true

    signal retryRequested()
    signal exportRequested()

    function _bgColor() {
        switch (sdState) {
            case "SAFE":                    return "#2a3f6a"
            case "GARBAGE":                 return "#6a2a2a"
            case "UNCERTAIN":               return "#6a4d2a"
            case "BOOTABLE_NO_FIRSTBOOT":   return "#6a4d2a"
            case "OK":                      return "#6a6a2a"
            default:                        return "#2a2a2a"
        }
    }

    background: Rectangle {
        color: root._bgColor()
        radius: 6
        border.color: Qt.lighter(root._bgColor(), 1.3)
        border.width: 1
    }

    contentItem: ColumnLayout {
        spacing: 12
        Text {
            text: root.message
            color: "#f0f0f0"
            font.pixelSize: 13
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Text {
            visible: root.hint !== ""
            text: "→ " + root.hint
            color: "#d0d4d8"
            font.pixelSize: 12
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        RowLayout {
            spacing: 8
            Layout.fillWidth: true
            Button {
                visible: root.retryable
                text: "Retry"
                onClicked: root.retryRequested()
            }
            Button {
                visible: root.exportable
                text: "Export diagnostic"
                onClicked: root.exportRequested()
            }
            Item { Layout.fillWidth: true }
        }
    }
}

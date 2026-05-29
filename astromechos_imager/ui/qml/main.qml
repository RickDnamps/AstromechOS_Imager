import QtQuick
import QtQuick.Controls
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 800
    height: 600
    visible: true
    title: "AstromechOS Imager"
    color: "#101418"

    Image {
        id: splash
        anchors.fill: parent
        source: splashImageUrl
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: true
    }
}

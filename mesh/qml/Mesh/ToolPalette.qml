import QtQuick
import QtQuick.Controls.Basic

// The tool palette: the click-on-a-part tools and everyday edits. The tool
// that is waiting for a click is highlighted.
Rectangle {
    color: Theme.panel
    Flickable {
        anchors.fill: parent
        anchors.margins: 6
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: column
            width: parent.width
            spacing: 1
            Repeater {
                model: bridge.palette
                delegate: SmallButton {
                    required property var modelData
                    key: modelData
                    width: column.width
                }
            }
        }
    }
}

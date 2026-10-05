import QtQuick
import QtQuick.Controls.Basic

// Every part in the scene. Click to select; Ctrl- or Shift-click to add to
// the selection.
Rectangle {
    color: Theme.panel

    Text {
        anchors.centerIn: parent
        width: parent.width - 32
        visible: bridge.outliner.length === 0
        text: "Nothing here yet. Add a shape from the Insert panel."
        color: Theme.muted
        font.pixelSize: Theme.fontSize
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }

    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 4
        clip: true
        model: bridge.outliner
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        delegate: AbstractButton {
            id: row
            required property var modelData
            width: list.width
            height: 30
            hoverEnabled: true
            contentItem: Item {
                Rectangle {
                    id: swatch
                    x: 6
                    anchors.verticalCenter: parent.verticalCenter
                    width: 14
                    height: 14
                    radius: row.modelData.guide ? 7 : 3
                    color: row.modelData.hole ? "transparent" : row.modelData.color
                    border.color: row.modelData.hole ? row.modelData.color : Theme.border
                    border.width: row.modelData.hole ? 2 : 1
                }
                Text {
                    anchors.left: swatch.right
                    anchors.leftMargin: 8
                    anchors.right: kind.left
                    anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.name
                    color: row.modelData.selected ? Theme.onAccent : Theme.text
                    font.pixelSize: Theme.fontSize
                    elide: Text.ElideRight
                }
                Text {
                    id: kind
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.hole ? "Hole" : row.modelData.kind
                    color: row.modelData.selected ? Theme.onAccent : Theme.muted
                    font.pixelSize: Theme.smallFont
                }
            }
            background: Rectangle {
                radius: Theme.radius - 1
                color: row.modelData.selected ? Theme.accent : rowArea.containsMouse ? Theme.hover : "transparent"
            }
            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: (mouse) => bridge.select(row.modelData.id,
                    (mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) !== 0)
            }
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic

// Thumbnails of everything that can be added. Click one to add it to the
// middle of the workplane, or drag it onto the 3D view to drop it there.
Rectangle {
    id: root
    color: Theme.panel
    readonly property var sections: {
        var names = []
        var items = bridge.insertItems
        for (var i = 0; i < items.length; ++i)
            if (names.indexOf(items[i].section) < 0)
                names.push(items[i].section)
        return names
    }

    Flickable {
        anchors.fill: parent
        anchors.margins: 6
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }

        Column {
            id: column
            width: parent.width
            Repeater {
                model: root.sections
                delegate: Column {
                    id: section
                    required property var modelData
                    width: column.width
                    PanelHeader { text: section.modelData }
                    Flow {
                        width: section.width
                        spacing: 4
                        Repeater {
                            model: bridge.insertItems.filter(item => item.section === section.modelData)
                            delegate: AbstractButton {
                                id: tile
                                required property var modelData
                                width: 84
                                height: 96
                                hoverEnabled: true
                                focusPolicy: Qt.TabFocus

                                Item {
                                    id: dragProxy
                                    Drag.dragType: Drag.Automatic
                                    Drag.supportedActions: Qt.CopyAction
                                    Drag.mimeData: ({ [bridge.insertMime]: tile.modelData.key })
                                    Drag.imageSource: tile.modelData.thumbnailUrl
                                    Drag.active: dragArea.drag.active
                                }
                                MouseArea {
                                    id: dragArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    drag.target: dragProxy
                                    onClicked: bridge.insert(tile.modelData.key)
                                    onReleased: { dragProxy.x = 0; dragProxy.y = 0 }
                                    cursorShape: Qt.PointingHandCursor
                                }

                                contentItem: Column {
                                    spacing: 2
                                    topPadding: 4
                                    Image {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 64
                                        height: 64
                                        sourceSize.width: 128
                                        sourceSize.height: 128
                                        source: tile.modelData.thumbnailUrl
                                        fillMode: Image.PreserveAspectFit
                                    }
                                    Text {
                                        width: tile.width - 6
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: tile.modelData.label
                                        color: Theme.text
                                        font.pixelSize: Theme.smallFont
                                        horizontalAlignment: Text.AlignHCenter
                                        elide: Text.ElideRight
                                    }
                                }
                                background: Rectangle {
                                    radius: Theme.radius
                                    color: dragArea.pressed ? Theme.pressed : dragArea.containsMouse ? Theme.hover : "transparent"
                                    border.color: dragArea.containsMouse || tile.visualFocus ? Theme.accent : "transparent"
                                }
                                Keys.onReturnPressed: bridge.insert(tile.modelData.key)
                                Tip {
                                    text: tile.modelData.command
                                          ? "Add " + tile.modelData.label.toLowerCase() + " (asks for its sizes first)"
                                          : "Click to add, or drag onto the 3D view"
                                    visible: dragArea.containsMouse && !dragArea.pressed
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

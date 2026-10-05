import QtQuick
import QtQuick.Controls.Basic

// Every step that can be undone or redone. Click a step to go back (or
// forward) to just after it.
Rectangle {
    color: Theme.panel

    Row {
        id: buttons
        x: 6
        y: 6
        spacing: 4
        SmallButton { key: "edit.undo" }
        SmallButton { key: "edit.redo" }
    }

    ListView {
        id: list
        anchors.top: buttons.bottom
        anchors.topMargin: 6
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 4
        clip: true
        model: bridge.history
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        onCountChanged: positionViewAtEnd()
        delegate: AbstractButton {
            id: step
            required property var modelData
            required property int index
            readonly property bool current: modelData.state === "current"
            width: list.width
            height: 26
            hoverEnabled: true
            contentItem: Text {
                leftPadding: 10
                text: (step.index > 0 ? step.index + ". " : "") + step.modelData.label
                color: step.current ? Theme.onAccent : step.modelData.state === "undone" ? Theme.muted : Theme.text
                font.pixelSize: Theme.fontSize
                font.italic: step.modelData.state === "undone"
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: Theme.radius - 1
                color: step.current ? Theme.accent : step.hovered ? Theme.hover : "transparent"
            }
            onClicked: bridge.undoTo(index)
            Tip {
                text: step.current ? "This is where you are now."
                     : step.modelData.state === "undone" ? "Redo up to this step." : "Undo back to just after this step."
                visible: step.hovered
            }
        }
    }
}

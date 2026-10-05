import QtQuick

// Above the 3D view: which mode it is in (selecting, or a tool waiting for a
// click), and the camera buttons.
Rectangle {
    color: Theme.background
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    Row {
        anchors.left: parent.left
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        Rectangle {
            width: modeText.implicitWidth + 18
            height: 22
            radius: 11
            color: bridge.toolActive ? Theme.accent : Theme.panel
            border.color: bridge.toolActive ? Theme.accent : Theme.border
            Text {
                id: modeText
                anchors.centerIn: parent
                text: "Mode: " + bridge.mode
                color: bridge.toolActive ? Theme.onAccent : Theme.text
                font.pixelSize: Theme.smallFont + 1
                font.bold: bridge.toolActive
            }
        }
        SmallButton {
            visible: bridge.toolActive
            key: "edit.stop_current_tool"
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        SmallButton { key: "view.home"; showLabel: false }
        SmallButton { key: "view.top"; showLabel: false }
        SmallButton { key: "view.front"; showLabel: false }
        SmallButton { key: "view.right"; showLabel: false }
        SmallButton { key: "view.zoom_to_selection"; showLabel: false }
    }
}

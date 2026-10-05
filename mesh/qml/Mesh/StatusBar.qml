import QtQuick

// The bottom line: what the active tool wants next (or how printable the
// model is), and the keys worth knowing right now.
Rectangle {
    color: Theme.panel
    Rectangle { width: parent.width; height: 1; color: Theme.border }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.right: hint.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: bridge.status
        color: bridge.statusWarning ? Theme.warning : Theme.text
        font.pixelSize: Theme.fontSize
        elide: Text.ElideRight
    }
    Text {
        id: hint
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        text: (bridge.toolActive ? "Esc: stop the tool    " : "") + "Ctrl+Z: undo    Ctrl+K: search commands"
        color: Theme.muted
        font.pixelSize: Theme.smallFont
    }
}

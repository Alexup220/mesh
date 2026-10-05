import QtQuick
import QtQuick.Controls.Basic

// Ctrl+K: type part of a command's name, then Enter (or click) to run it.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.accent
    border.width: 1
    radius: Theme.radius

    readonly property var matches: {
        var words = search.text.toLowerCase().split(/\s+/).filter(w => w.length > 0)
        var found = []
        var all = bridge.commands
        for (var key in all) {
            var cmd = all[key]
            if (!cmd.visible)
                continue
            var haystack = (cmd.label + " " + key.replace(/[._]/g, " ") + " " + cmd.tip).toLowerCase()
            if (words.every(w => haystack.indexOf(w) >= 0))
                found.push(cmd)
        }
        found.sort((a, b) => a.label.localeCompare(b.label))
        return found
    }

    function run(index) {
        if (index < 0 || index >= matches.length || !matches[index].enabled)
            return
        var key = matches[index].key
        Window.window.close()
        bridge.trigger(key)
    }

    Column {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        MeshTextField {
            id: search
            width: parent.width
            placeholderText: "Search commands…"
            focus: true
            Component.onCompleted: forceActiveFocus()
            onTextChanged: list.currentIndex = 0
            Keys.onDownPressed: list.incrementCurrentIndex()
            Keys.onUpPressed: list.decrementCurrentIndex()
            Keys.onReturnPressed: root.run(list.currentIndex)
            Keys.onEnterPressed: root.run(list.currentIndex)
            Keys.onEscapePressed: Window.window.close()
        }

        ListView {
            id: list
            width: parent.width
            height: parent.height - search.height - 8
            clip: true
            model: root.matches
            currentIndex: 0
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            delegate: AbstractButton {
                id: row
                required property var modelData
                required property int index
                readonly property bool current: ListView.isCurrentItem
                width: list.width
                height: 32
                hoverEnabled: true
                enabled: modelData.enabled
                contentItem: Item {
                    Icon {
                        x: 6
                        anchors.verticalCenter: parent.verticalCenter
                        name: row.modelData.icon
                        highlighted: row.current
                        size: 18
                        opacity: row.enabled ? 1 : 0.35
                    }
                    Text {
                        x: 34
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.label + (row.modelData.checked ? "  ✓" : "")
                        color: row.current ? Theme.onAccent : Theme.text
                        opacity: row.enabled ? 1 : 0.4
                        font.pixelSize: Theme.fontSize
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.shortcut
                        color: row.current ? Theme.onAccent : Theme.muted
                        font.pixelSize: Theme.smallFont
                    }
                }
                background: Rectangle {
                    radius: Theme.radius - 1
                    color: row.current ? Theme.accent : row.hovered ? Theme.hover : "transparent"
                }
                onHoveredChanged: if (hovered) list.currentIndex = index
                onClicked: root.run(index)
            }
        }
    }
}

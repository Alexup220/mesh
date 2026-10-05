import QtQuick
import QtQuick.Controls.Basic

// A menu built from the bridge's menu entries: commands (by key),
// separators and sub-menus. It opens in its own window, so it is never cut
// off by the panel it opens from.
Menu {
    id: menu
    property var entries: []
    popupType: Popup.Window
    width: 300

    // Items are made when the menu first opens after its entries changed,
    // not before: most menus are never opened, and the window's menus
    // change every time Expert mode is switched. They must exist before
    // open(): the menu's own window takes its size when it is first shown
    // and does not grow afterwards, so building them in onAboutToShow left
    // a window just tall enough for one item. Open with openBuilt().
    property bool stale: true
    onEntriesChanged: stale = true

    function openBuilt() {
        if (stale)
            rebuild()
        open()
    }

    // What rebuild() made, so the next rebuild can throw it away.
    property var made: []

    function rebuild() {
        while (menu.count > 0)
            menu.takeItem(0)
        for (var j = 0; j < made.length; ++j)
            made[j].destroy()
        var fresh = []
        var list = entries || []
        for (var i = 0; i < list.length; ++i) {
            var entry = list[i]
            var made_one
            if (entry.type === "separator") {
                made_one = separatorComponent.createObject(menu.contentItem)
                menu.addItem(made_one)
            } else if (entry.type === "menu") {
                made_one = Qt.createComponent(Qt.resolvedUrl("MeshMenu.qml"))
                                 .createObject(menu, { title: entry.title, entries: entry.entries })
                made_one.rebuild()
                menu.addMenu(made_one)
            } else {
                made_one = itemComponent.createObject(menu.contentItem, { key: entry.key })
                menu.addItem(made_one)
            }
            fresh.push(made_one)
        }
        made = fresh
        stale = false
    }


    background: Rectangle {
        implicitWidth: 300
        color: Theme.panel
        border.color: Theme.border
        radius: Theme.radius
    }

    delegate: MenuItem {
        id: subItem
        hoverEnabled: true
        implicitHeight: 28
        contentItem: Text {
            leftPadding: 30
            text: subItem.text
            color: subItem.highlighted ? Theme.onAccent : Theme.text
            font.pixelSize: Theme.fontSize
            verticalAlignment: Text.AlignVCenter
        }
        arrow: Text {
            x: subItem.width - width - 10
            y: (subItem.height - height) / 2
            text: "›"
            color: subItem.highlighted ? Theme.onAccent : Theme.muted
            font.pixelSize: Theme.fontSize + 2
        }
        background: Rectangle {
            color: subItem.highlighted ? Theme.accent : "transparent"
            radius: Theme.radius - 2
        }
    }

    Component {
        id: separatorComponent
        MenuSeparator {
            contentItem: Rectangle {
                implicitHeight: 1
                color: Theme.border
            }
        }
    }

    Component {
        id: itemComponent
        MenuItem {
            id: item
            property string key: ""
            readonly property var cmd: bridge.commands[key] || null
            text: cmd ? cmd.label : ""
            enabled: cmd !== null && cmd.enabled === true
            hoverEnabled: true
            implicitHeight: 28
            onTriggered: bridge.trigger(key)
            contentItem: Item {
                implicitWidth: 260
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 6
                    text: item.cmd && item.cmd.checked ? "✓" : ""
                    color: item.highlighted ? Theme.onAccent : Theme.accent
                    font.pixelSize: Theme.fontSize
                }
                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 6
                    visible: !(item.cmd && item.cmd.checked)
                    name: item.cmd ? item.cmd.icon : ""
                    highlighted: item.highlighted
                    size: 16
                    opacity: item.enabled ? 1 : 0.35
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 30
                    text: item.text
                    color: item.highlighted ? Theme.onAccent : Theme.text
                    opacity: item.enabled ? 1 : 0.4
                    font.pixelSize: Theme.fontSize
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    text: item.cmd ? item.cmd.shortcut : ""
                    color: item.highlighted ? Theme.onAccent : Theme.muted
                    font.pixelSize: Theme.smallFont
                }
            }
            background: Rectangle {
                color: item.highlighted ? Theme.accent : "transparent"
                radius: Theme.radius - 2
            }
        }
    }
}

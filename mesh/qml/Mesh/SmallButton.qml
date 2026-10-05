import QtQuick
import QtQuick.Controls.Basic

// A small button: icon beside its label (or the icon alone). Runs the
// command `key`, or opens `menuEntries` as a drop-down.
AbstractButton {
    id: button
    property string key: ""
    property bool showLabel: true
    property var menuEntries: null
    property string menuLabel: ""
    property string menuIcon: ""
    readonly property var cmd: key ? (bridge.commands[key] || null) : null
    readonly property bool active: cmd !== null && cmd.checked === true

    implicitWidth: row.implicitWidth + 12
    implicitHeight: 26
    hoverEnabled: true
    enabled: menuEntries ? true : (cmd !== null && cmd.enabled === true)
    focusPolicy: Qt.TabFocus

    contentItem: Item {
        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            x: 6
            spacing: 6
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: button.menuEntries ? button.menuIcon : (button.cmd ? button.cmd.icon : "")
                highlighted: button.active
                size: 18
                opacity: button.enabled ? 1 : 0.35
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: button.showLabel
                text: button.menuEntries ? button.menuLabel + " ▾" : (button.cmd ? button.cmd.label : "")
                color: button.active ? Theme.onAccent : Theme.text
                opacity: button.enabled ? 1 : 0.4
                font.pixelSize: Theme.smallFont + 1
            }
        }
    }

    background: Rectangle {
        radius: Theme.radius - 1
        color: button.active ? Theme.accent
             : button.down ? Theme.pressed
             : button.hovered && button.enabled ? Theme.hover : "transparent"
        border.color: button.visualFocus ? Theme.accent : "transparent"
    }

    Tip {
        text: button.menuEntries ? button.menuLabel
              : button.cmd ? button.cmd.label + (button.cmd.shortcut ? "  (" + button.cmd.shortcut + ")" : "")
                             + (button.cmd.tip ? "\n" + button.cmd.tip : "") : ""
        visible: button.hovered && text !== ""
        width: Math.min(implicitWidth, 380)
    }

    // Made only for a drop-down button.
    Loader {
        id: dropDown
        active: button.menuEntries !== null
        sourceComponent: Component {
            MeshMenu {
                parent: button
                y: button.height
                entries: button.menuEntries || []
            }
        }
    }

    onClicked: {
        if (menuEntries)
            dropDown.item.openBuilt()
        else
            bridge.trigger(key)
    }
}

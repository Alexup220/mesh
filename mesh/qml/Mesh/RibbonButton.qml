import QtQuick
import QtQuick.Controls.Basic

// A large ribbon button: icon over label. It runs the command `key`, or
// opens `menuEntries` as a drop-down when it has them.
AbstractButton {
    id: button
    property string key: ""
    property var menuEntries: null
    property string menuLabel: ""
    property string menuIcon: ""
    readonly property var cmd: key ? (bridge.commands[key] || null) : null
    readonly property bool active: cmd !== null && cmd.checked === true

    implicitWidth: Math.max(58, label.implicitWidth + 12)
    implicitHeight: 64
    hoverEnabled: true
    enabled: menuEntries ? true : (cmd !== null && cmd.enabled === true)
    focusPolicy: Qt.TabFocus

    contentItem: Column {
        spacing: 3
        topPadding: 6
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: button.menuEntries ? button.menuIcon : (button.cmd ? button.cmd.icon : "")
            highlighted: button.active
            size: 26
            opacity: button.enabled ? 1 : 0.35
        }
        Text {
            id: label
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, 96)
            text: (button.menuEntries ? button.menuLabel + " ▾" : (button.cmd ? button.cmd.label : ""))
            color: button.active ? Theme.onAccent : Theme.text
            opacity: button.enabled ? 1 : 0.4
            font.pixelSize: Theme.smallFont
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }

    background: Rectangle {
        radius: Theme.radius
        color: button.active ? Theme.accent
             : button.down ? Theme.pressed
             : button.hovered && button.enabled ? Theme.hover : "transparent"
        border.color: button.visualFocus ? Theme.accent : (button.hovered && button.enabled ? Theme.border : "transparent")
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
            dropDown.item.open()
        else
            bridge.trigger(key)
    }
}

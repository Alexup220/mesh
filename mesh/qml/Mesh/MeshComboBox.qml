import QtQuick
import QtQuick.Controls.Basic

// A drop-down whose list opens in its own window, so it is never cut off.
ComboBox {
    id: combo
    font.pixelSize: Theme.fontSize
    hoverEnabled: true
    popup.popupType: Popup.Window
    delegate: ItemDelegate {
        id: row
        required property var modelData
        required property int index
        width: combo.width
        hoverEnabled: true
        highlighted: combo.highlightedIndex === index
        contentItem: Text {
            text: combo.textRole ? row.modelData[combo.textRole] : row.modelData
            color: row.highlighted ? Theme.onAccent : Theme.text
            font.pixelSize: Theme.fontSize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle { color: row.highlighted ? Theme.accent : Theme.panel }
    }
    contentItem: Text {
        leftPadding: 8
        rightPadding: combo.indicator.width + 4
        text: combo.displayText
        color: Theme.text
        font.pixelSize: Theme.fontSize
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Text {
        x: combo.width - width - 8
        y: (combo.height - height) / 2
        text: "▾"
        color: Theme.muted
        font.pixelSize: Theme.fontSize
    }
    background: Rectangle {
        implicitHeight: 30
        radius: Theme.radius - 1
        color: combo.down ? Theme.pressed : combo.hovered ? Theme.hover : Theme.field
        border.color: combo.activeFocus || combo.hovered ? Theme.accent : Theme.border
    }
    popup.background: Rectangle {
        color: Theme.panel
        border.color: Theme.border
        radius: Theme.radius
    }
}

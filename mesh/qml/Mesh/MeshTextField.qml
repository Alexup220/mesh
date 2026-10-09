import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: field
    font.pixelSize: Theme.fontSize
    color: Theme.text
    selectionColor: Theme.accent
    selectedTextColor: Theme.onAccent
    placeholderTextColor: Theme.muted
    hoverEnabled: true
    padding: 6
    background: Rectangle {
        radius: Theme.radius - 1
        color: Theme.field
        border.color: field.activeFocus ? Theme.accent : field.hovered ? Theme.muted : Theme.border
        border.width: field.activeFocus ? 2 : 1
    }
}

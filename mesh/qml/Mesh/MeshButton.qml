import QtQuick
import QtQuick.Controls.Basic

// A plain text button (dialogs, the welcome screen).
Button {
    id: button
    property bool primary: false
    font.pixelSize: Theme.fontSize
    hoverEnabled: true
    padding: 8
    leftPadding: 16
    rightPadding: 16
    contentItem: Text {
        text: button.text
        font: button.font
        color: button.primary ? Theme.onAccent : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        opacity: button.enabled ? 1 : 0.4
    }
    background: Rectangle {
        radius: Theme.radius
        color: button.primary ? (button.down ? Qt.darker(Theme.accent, 1.2) : button.hovered ? Qt.lighter(Theme.accent, 1.12) : Theme.accent)
                              : (button.down ? Theme.pressed : button.hovered ? Theme.hover : Theme.panel)
        border.color: button.visualFocus || button.hovered ? Theme.accent : Theme.border
        border.width: 1
    }
}

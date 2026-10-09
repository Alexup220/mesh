import QtQuick
import QtQuick.Controls.Basic

// A tooltip in its own small window, so it is never cut off by the edge of
// the panel it belongs to.
ToolTip {
    id: tip
    popupType: Popup.Window
    delay: 600
    timeout: 8000
    contentItem: Text {
        text: tip.text
        color: Theme.text
        font.pixelSize: Theme.fontSize - 1
        wrapMode: Text.WordWrap
    }
    background: Rectangle {
        color: Theme.panel
        border.color: Theme.border
        radius: Theme.radius
    }
}

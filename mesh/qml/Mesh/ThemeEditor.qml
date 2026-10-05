import QtQuick
import QtQuick.Controls.Basic

// Make a theme of your own: start from any theme, change its colours (the
// window shows each change straight away), name it and save it. Saved
// themes appear under View > Theme and are kept for next time.
Rectangle {
    id: root
    required property string startTheme
    color: Theme.background
    property var colors: bridge.themeTokens(startTheme)
    property string problem: ""

    function setColor(token, value) {
        var copy = Object.assign({}, colors)
        copy[token] = value
        colors = copy
        bridge.previewTheme(colors)
    }
    function close() {
        bridge.endPreview()
        Window.window.close()
    }
    function save() {
        problem = bridge.saveTheme(name.text, colors)
        if (problem === "")
            Window.window.close()
    }

    Keys.onEscapePressed: close()

    Connections {
        target: root.Window.window
        function onClosing(close) { bridge.endPreview() }
    }

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        spacing: 6

        Text {
            text: "Start from"
            color: Theme.muted
            font.pixelSize: Theme.smallFont + 1
        }
        MeshComboBox {
            width: parent.width
            model: bridge.themeNames
            currentIndex: bridge.themeNames.indexOf(root.startTheme)
            onActivated: (index) => {
                root.colors = bridge.themeTokens(bridge.themeNames[index])
                bridge.previewTheme(root.colors)
            }
        }

        PanelHeader { text: "Colours" }

        // Each colour: its name, a swatch (click to choose), and its #code.
        Repeater {
            model: bridge.tokenNames
            delegate: Row {
                id: colorRow
                required property var modelData
                spacing: 10
                Text {
                    width: 170
                    anchors.verticalCenter: parent.verticalCenter
                    text: colorRow.modelData.label
                    color: Theme.text
                    font.pixelSize: Theme.fontSize
                }
                AbstractButton {
                    id: swatch
                    width: 44
                    height: 28
                    hoverEnabled: true
                    background: Rectangle {
                        radius: Theme.radius - 1
                        color: root.colors[colorRow.modelData.token] || "transparent"
                        border.color: swatch.hovered ? Theme.accent : Theme.border
                        border.width: swatch.hovered ? 2 : 1
                    }
                    onClicked: root.setColor(colorRow.modelData.token,
                                             bridge.chooseColor(root.colors[colorRow.modelData.token]))
                    Tip { text: "Choose a colour"; visible: swatch.hovered }
                }
                MeshTextField {
                    width: 110
                    text: root.colors[colorRow.modelData.token] || ""
                    onEditingFinished: {
                        var value = text.trim().toLowerCase()
                        if (/^#[0-9a-f]{6}$/.test(value))
                            root.setColor(colorRow.modelData.token, value)
                        else
                            text = root.colors[colorRow.modelData.token]
                    }
                }
            }
        }
    }

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: buttons.top
        anchors.margins: 16
        spacing: 6
        Text {
            text: "Name"
            color: Theme.muted
            font.pixelSize: Theme.smallFont + 1
        }
        MeshTextField {
            id: name
            width: parent.width
            placeholderText: "My theme"
            onAccepted: root.save()
        }
        Text {
            width: parent.width
            visible: root.problem !== ""
            text: root.problem
            color: Theme.warning
            font.pixelSize: Theme.fontSize
            wrapMode: Text.WordWrap
        }
    }

    Row {
        id: buttons
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 16
        spacing: 8
        MeshButton { text: "Cancel"; onClicked: root.close() }
        MeshButton { text: "Save theme"; primary: true; onClicked: root.save() }
    }
}

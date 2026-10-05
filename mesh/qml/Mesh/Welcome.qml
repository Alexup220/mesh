import QtQuick
import QtQuick.Controls.Basic

// Shown the first time mesh starts (and from View > Welcome Screen).
Rectangle {
    id: root
    color: Theme.background
    Keys.onEscapePressed: Window.window.close()

    Column {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14

        Text {
            text: "Welcome to mesh"
            color: Theme.text
            font.pixelSize: 24
            font.bold: true
        }
        Text {
            width: parent.width
            text: "Easy 3D modeling for 3D printing. Everything is in millimetres, and anything can be undone with Ctrl+Z."
            color: Theme.text
            font.pixelSize: Theme.fontSize + 1
            wrapMode: Text.WordWrap
        }

        Repeater {
            model: [
                { title: "Add shapes", text: "Click a thumbnail in the Insert panel on the left, or drag it onto the 3D view." },
                { title: "Change sizes", text: "Select a part and type its exact numbers in the Properties panel on the right." },
                { title: "Cut holes", text: "Make a part a hole, place it, then Group it with a solid to cut it out." },
                { title: "Find any tool", text: "Press Ctrl+K and type what you want to do." }
            ]
            delegate: Row {
                required property var modelData
                spacing: 12
                Rectangle {
                    width: 6
                    height: tipText.height
                    radius: 3
                    color: Theme.accent
                }
                Column {
                    id: tipText
                    width: root.width - 48 - 18
                    Text {
                        text: modelData.title
                        color: Theme.text
                        font.pixelSize: Theme.fontSize
                        font.bold: true
                    }
                    Text {
                        width: parent.width
                        text: modelData.text
                        color: Theme.muted
                        font.pixelSize: Theme.fontSize
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        Row {
            spacing: 10
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Theme"
                color: Theme.text
                font.pixelSize: Theme.fontSize
            }
            MeshComboBox {
                width: 220
                model: bridge.themeNames
                currentIndex: bridge.themeNames.indexOf(bridge.themeName)
                onActivated: (index) => bridge.setTheme(bridge.themeNames[index])
            }
        }
    }

    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 20
        spacing: 8
        MeshButton {
            text: "Open a project"
            onClicked: {
                Window.window.close()
                bridge.trigger("file.open_project")
            }
        }
        MeshButton {
            text: "Start modeling"
            primary: true
            focus: true
            onClicked: Window.window.close()
        }
    }
}

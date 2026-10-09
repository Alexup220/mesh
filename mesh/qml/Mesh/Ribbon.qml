import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The top of the window: the menu bar, then the ribbon's tabs (Create,
// Modify, Inspect, Export) of grouped tool buttons.
Rectangle {
    id: root
    color: Theme.panel

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // --- menu bar ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: Theme.background
            Row {
                anchors.fill: parent
                anchors.leftMargin: 4
                Repeater {
                    model: bridge.menus
                    delegate: AbstractButton {
                        id: menuButton
                        required property var modelData
                        height: 28
                        width: menuText.implicitWidth + 20
                        hoverEnabled: true
                        contentItem: Text {
                            id: menuText
                            text: menuButton.modelData.title
                            color: menuButton.down || dropDown.opened ? Theme.onAccent : Theme.text
                            font.pixelSize: Theme.fontSize
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            color: dropDown.opened ? Theme.accent : menuButton.hovered ? Theme.hover : "transparent"
                            radius: Theme.radius - 2
                        }
                        MeshMenu {
                            id: dropDown
                            y: menuButton.height
                            entries: menuButton.modelData.entries
                        }
                        onClicked: dropDown.openBuilt()
                    }
                }
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "Search commands: Ctrl+K"
                color: Theme.muted
                font.pixelSize: Theme.smallFont
            }
        }

        // --- tabs ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: Theme.background
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 6
                anchors.bottom: parent.bottom
                spacing: 2
                Repeater {
                    model: bridge.ribbon
                    delegate: AbstractButton {
                        id: tab
                        required property var modelData
                        required property int index
                        readonly property bool current: tabs.currentIndex === index
                        width: tabText.implicitWidth + 28
                        height: 28
                        hoverEnabled: true
                        contentItem: Text {
                            id: tabText
                            text: tab.modelData.title
                            color: tab.current ? Theme.text : Theme.muted
                            font.pixelSize: Theme.fontSize
                            font.bold: tab.current
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            color: tab.current ? Theme.panel : tab.hovered ? Theme.hover : "transparent"
                            radius: Theme.radius
                            Rectangle {
                                anchors.top: parent.top
                                width: parent.width
                                height: 3
                                radius: 1
                                color: Theme.accent
                                visible: tab.current
                            }
                        }
                        onClicked: tabs.currentIndex = index
                    }
                }
            }
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                visible: bridge.expertMode
                width: expertText.implicitWidth + 16
                height: 20
                radius: 10
                color: Theme.accent
                Text {
                    id: expertText
                    anchors.centerIn: parent
                    text: "Expert mode"
                    color: Theme.onAccent
                    font.pixelSize: Theme.smallFont
                    font.bold: true
                }
            }
        }

        // --- the current tab's groups ---
        Item {
            id: tabs
            property int currentIndex: 0
            readonly property var tab: bridge.ribbon.length > 0
                                       ? bridge.ribbon[Math.min(currentIndex, bridge.ribbon.length - 1)] : null
            Layout.fillWidth: true
            Layout.fillHeight: true

            Flickable {
                id: strip
                anchors.fill: parent
                contentWidth: groupRow.width + 12
                contentHeight: height
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                ScrollBar.horizontal: ScrollBar { height: 6; policy: strip.contentWidth > strip.width ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                WheelHandler {
                    onWheel: (event) => {
                        strip.flick(event.angleDelta.y * 6, 0)
                    }
                }

                Row {
                    id: groupRow
                    x: 6
                    height: strip.height
                    spacing: 0
                    Repeater {
                        model: tabs.tab ? tabs.tab.groups : []
                        delegate: Row {
                            id: group
                            required property var modelData
                            required property int index
                            height: groupRow.height
                            spacing: 0
                            Rectangle {
                                visible: group.index > 0
                                width: 1
                                height: parent.height - 12
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.border
                            }
                            Column {
                                id: body
                                height: parent.height
                                leftPadding: 6
                                rightPadding: 6
                                // Up to four tools as big buttons; more as
                                // small ones in columns of three.
                                readonly property bool compact: group.modelData.items.length > 4
                                Item {
                                    width: Math.max(big.visible ? big.width : small.width, title.implicitWidth)
                                    height: parent.height - title.height - 4
                                    Row {
                                        id: big
                                        visible: !body.compact
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 2
                                        Repeater {
                                            model: big.visible ? group.modelData.items : []
                                            delegate: RibbonButton {
                                                required property var modelData
                                                key: modelData.type === "action" ? modelData.key : ""
                                                menuEntries: modelData.type === "menu" ? modelData.entries : null
                                                menuLabel: modelData.type === "menu" ? modelData.label : ""
                                                menuIcon: modelData.type === "menu" ? modelData.icon : ""
                                            }
                                        }
                                    }
                                    Grid {
                                        id: small
                                        visible: body.compact
                                        anchors.verticalCenter: parent.verticalCenter
                                        rows: 3
                                        flow: Grid.TopToBottom
                                        columnSpacing: 2
                                        rowSpacing: 1
                                        Repeater {
                                            model: small.visible ? group.modelData.items : []
                                            delegate: SmallButton {
                                                required property var modelData
                                                key: modelData.type === "action" ? modelData.key : ""
                                                menuEntries: modelData.type === "menu" ? modelData.entries : null
                                                menuLabel: modelData.type === "menu" ? modelData.label : ""
                                                menuIcon: modelData.type === "menu" ? modelData.icon : ""
                                            }
                                        }
                                    }
                                }
                                Text {
                                    id: title
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: group.modelData.title
                                    color: Theme.muted
                                    font.pixelSize: Theme.smallFont - 1
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.border
        }
    }
}

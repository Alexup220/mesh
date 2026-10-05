import QtQuick
import QtQuick.Controls.Basic

// The selected part's exact numbers: where it is, its sizes, how it is
// turned, its colour, and whether it is a hole. Type a number and press
// Enter (or leave the field) to change it.
Rectangle {
    id: root
    color: Theme.panel

    Text {
        anchors.centerIn: parent
        width: parent.width - 32
        visible: bridge.properties.length === 0
        text: bridge.selectedCount > 1 ? "Several parts are selected. Select one to see its sizes."
                                       : "Select a part to see its sizes."
        color: Theme.muted
        font.pixelSize: Theme.fontSize
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }

    Flickable {
        anchors.fill: parent
        anchors.margins: 8
        visible: bridge.properties.length > 0
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }

        Column {
            id: column
            width: parent.width - 8
            spacing: 4

            Text {
                width: column.width
                text: bridge.selectedName
                color: Theme.text
                font.pixelSize: Theme.fontSize + 2
                font.bold: true
                elide: Text.ElideRight
            }

            // One row per field. The rows are kept while only values change,
            // so a field being typed in is not swept away by an update.
            Repeater {
                model: bridge.properties.length
                delegate: Column {
                    id: line
                    required property int index
                    readonly property var row: bridge.properties[index] || null
                    readonly property var before: index > 0 ? bridge.properties[index - 1] || null : null
                    width: column.width
                    spacing: 2

                    PanelHeader {
                        visible: line.row !== null && (line.before === null || line.before.section !== line.row.section)
                        text: line.row ? line.row.section : ""
                    }
                    Text {
                        visible: line.row !== null && line.row.kind !== "check"
                        text: line.row ? line.row.label : ""
                        color: Theme.muted
                        font.pixelSize: Theme.smallFont + 1
                        font.italic: line.row !== null && line.row.tip !== undefined && line.row.tip !== ""
                    }
                    Loader {
                        width: line.width
                        sourceComponent: !line.row ? null
                            : line.row.kind === "number" ? numberField
                            : line.row.kind === "choice" ? choiceField
                            : line.row.kind === "text" ? textField
                            : line.row.kind === "color" ? colorField
                            : checkField
                        property var row: line.row
                    }
                }
            }
        }
    }

    Component {
        id: numberField
        MeshTextField {
            id: box
            readonly property var row: parent ? parent.row : null
            readonly property real shown: row ? row.value : 0
            readonly property int decimals: row && row.decimals !== undefined ? row.decimals : 2
            function format(value) { return Number(value).toFixed(decimals) }
            function commit() {
                var value = Number(text.replace(",", "."))
                if (!row || isNaN(value)) { text = format(shown); return }
                value = Math.min(Math.max(value, row.min), row.max)
                if (Math.abs(value - shown) > Math.pow(10, -decimals) / 2)
                    bridge.setField(row.field, value)
                else
                    text = format(shown)
            }
            text: format(shown)
            onShownChanged: if (!activeFocus) text = format(shown)
            onActiveFocusChanged: if (!activeFocus) text = format(shown)
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            onEditingFinished: commit()
            Keys.onUpPressed: { text = format(Math.min(Number(text) + (row ? row.step : 1), row ? row.max : 1e9)); commit() }
            Keys.onDownPressed: { text = format(Math.max(Number(text) - (row ? row.step : 1), row ? row.min : -1e9)); commit() }
            Tip {
                text: box.row && box.row.tip ? box.row.tip : ""
                visible: box.hovered && text !== ""
            }
        }
    }

    Component {
        id: choiceField
        MeshComboBox {
            readonly property var row: parent ? parent.row : null
            model: row ? row.choices : []
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                if (!row) return -1
                for (var i = 0; i < row.choices.length; ++i)
                    if (row.choices[i].value === row.value) return i
                return -1
            }
            onActivated: (index) => bridge.setField(row.field, row.choices[index].value)
        }
    }

    Component {
        id: textField
        MeshTextField {
            readonly property var row: parent ? parent.row : null
            text: row ? row.value : ""
            onEditingFinished: if (row && text !== row.value) bridge.setField(row.field, text)
        }
    }

    Component {
        id: colorField
        Row {
            readonly property var row: parent ? parent.row : null
            spacing: 6
            AbstractButton {
                id: swatch
                width: 40
                height: 30
                hoverEnabled: true
                background: Rectangle {
                    radius: Theme.radius - 1
                    color: parent.parent.row ? parent.parent.row.value : "transparent"
                    border.color: swatch.hovered ? Theme.accent : Theme.border
                    border.width: swatch.hovered ? 2 : 1
                }
                onClicked: bridge.pickColor()
                Tip { text: "Choose a colour"; visible: swatch.hovered }
            }
            MeshTextField {
                width: 100
                text: parent.row ? parent.row.value : ""
                onEditingFinished: if (parent.row && text !== parent.row.value) bridge.setField("color", text)
            }
        }
    }

    Component {
        id: checkField
        CheckBox {
            id: check
            readonly property var row: parent ? parent.row : null
            text: row ? row.label : ""
            checked: row ? row.value === true : false
            hoverEnabled: true
            onToggled: bridge.setField(row.field, checked)
            indicator: Rectangle {
                x: check.leftPadding
                y: (check.height - height) / 2
                width: 18
                height: 18
                radius: 3
                color: check.checked ? Theme.accent : Theme.field
                border.color: check.hovered || check.visualFocus ? Theme.accent : Theme.border
                Text {
                    anchors.centerIn: parent
                    visible: check.checked
                    text: "✓"
                    color: Theme.onAccent
                    font.pixelSize: 13
                }
            }
            contentItem: Text {
                leftPadding: check.indicator.width + 8
                text: check.text
                color: Theme.text
                font.pixelSize: Theme.fontSize
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}

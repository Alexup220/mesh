import QtQuick
import QtQuick.Controls.Basic

// The numbers a tool asks for before it runs (Hollow out, Split part,
// Repeat in a row, ...): the same fields as the old dialogs, from
// bridge.FormSession. OK (or Enter) runs the tool; Cancel (or Esc) doesn't.
Rectangle {
    id: root
    required property var session
    color: Theme.background
    property var values: ({})

    function value(key, fallback) {
        return values[key] !== undefined ? values[key] : fallback
    }
    function set(key, v) {
        var copy = Object.assign({}, values)
        copy[key] = v
        values = copy
    }
    function accept() {
        // Leaving a text field commits it; make sure the typed text counts.
        root.forceActiveFocus()
        session.accept(values)
    }

    Keys.onEscapePressed: session.reject()
    Keys.onReturnPressed: accept()
    Keys.onEnterPressed: accept()

    Flickable {
        anchors.fill: parent
        anchors.margins: 16
        anchors.bottomMargin: 64
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: column
            width: parent.width
            spacing: 8

            Text {
                width: column.width
                visible: root.session.note !== ""
                text: root.session.note
                color: Theme.text
                font.pixelSize: Theme.fontSize
                wrapMode: Text.WordWrap
                bottomPadding: 4
            }

            Repeater {
                model: root.session.fields
                delegate: Column {
                    id: field
                    required property var modelData
                    width: column.width
                    spacing: 3
                    Text {
                        visible: field.modelData.kind !== "check"
                        text: field.modelData.label
                        color: Theme.muted
                        font.pixelSize: Theme.smallFont + 1
                    }
                    Loader {
                        width: field.width
                        property var spec: field.modelData
                        sourceComponent: field.modelData.kind === "check" ? checkInput
                                       : field.modelData.kind === "choice" ? choiceInput
                                       : field.modelData.kind === "text" ? textInput : numberInput
                    }
                }
            }
        }
    }

    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 16
        spacing: 8
        MeshButton { text: "Cancel"; onClicked: root.session.reject() }
        MeshButton { text: "OK"; primary: true; onClicked: root.accept() }
    }

    Component {
        id: numberInput
        MeshTextField {
            readonly property var spec: parent ? parent.spec : null
            readonly property int decimals: spec && spec.kind === "number" ? spec.decimals : 0
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            onTextEdited: if (spec) root.set(spec.key, Number(text.replace(",", ".")))
            Keys.onReturnPressed: root.accept()
            Keys.onEnterPressed: root.accept()
            Keys.onEscapePressed: root.session.reject()
            Component.onCompleted: {
                if (!spec)
                    return
                text = Number(root.value(spec.key, spec.value)).toFixed(decimals)
                if (spec.key === root.session.fields[0].key)
                    forceActiveFocus()
            }
        }
    }

    Component {
        id: textInput
        MeshTextField {
            readonly property var spec: parent ? parent.spec : null
            onTextEdited: if (spec) root.set(spec.key, text)
            Keys.onReturnPressed: root.accept()
            Keys.onEnterPressed: root.accept()
            Keys.onEscapePressed: root.session.reject()
            Component.onCompleted: {
                if (!spec)
                    return
                text = root.value(spec.key, spec.value)
                if (spec.key === root.session.fields[0].key)
                    forceActiveFocus()
            }
        }
    }

    Component {
        id: choiceInput
        MeshComboBox {
            readonly property var spec: parent ? parent.spec : null
            model: spec ? spec.choices : []
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                if (!spec) return -1
                var current = root.value(spec.key, spec.value)
                for (var i = 0; i < spec.choices.length; ++i)
                    if (spec.choices[i].value === current) return i
                return 0
            }
            onActivated: (index) => root.set(spec.key, spec.choices[index].value)
        }
    }

    Component {
        id: checkInput
        CheckBox {
            id: check
            readonly property var spec: parent ? parent.spec : null
            text: spec ? spec.label : ""
            checked: spec ? root.value(spec.key, spec.value) === true : false
            hoverEnabled: true
            onToggled: root.set(spec.key, checked)
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
                wrapMode: Text.WordWrap
            }
        }
    }
}

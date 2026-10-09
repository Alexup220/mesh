import QtQuick

// A command's icon, drawn in the theme's colours.
Image {
    property string name: ""
    property bool highlighted: false
    property int size: 24
    width: size
    height: size
    sourceSize.width: size
    sourceSize.height: size
    source: Theme.icon(name, highlighted)
    fillMode: Image.PreserveAspectFit
    smooth: true
}

pragma Singleton
import QtQuick

// The one place the window's colours come from. The window sets `tokens`
// (see mesh/themes.py) and every panel follows at once.
QtObject {
    property var tokens: ({
        background: "#23262b", panel: "#1b1e22", text: "#e6e8ea", accent: "#4a90d9",
        border: "#3d434b", viewport: "#292b33", grid: "#80878f", selection: "#ffd933"
    })

    readonly property color background: tokens.background
    readonly property color panel: tokens.panel
    readonly property color text: tokens.text
    readonly property color accent: tokens.accent
    readonly property color border: tokens.border
    readonly property color viewport: tokens.viewport
    readonly property color grid: tokens.grid
    readonly property color selection: tokens.selection

    // Shades worked out from the tokens, so a theme is only its tokens.
    readonly property color muted: Qt.tint(text, Qt.rgba(panel.r, panel.g, panel.b, 0.45))
    readonly property color hover: Qt.tint(panel, Qt.rgba(accent.r, accent.g, accent.b, 0.18))
    readonly property color pressed: Qt.tint(panel, Qt.rgba(accent.r, accent.g, accent.b, 0.4))
    readonly property color field: Qt.tint(panel, Qt.rgba(background.r, background.g, background.b, 0.5))
    readonly property color onAccent: (accent.r * 0.299 + accent.g * 0.587 + accent.b * 0.114) > 0.6
                                      ? "#000000" : "#ffffff"
    readonly property color warning: "#ff6b6b"

    readonly property int fontSize: 13
    readonly property int smallFont: 11
    readonly property int radius: 5

    // An icon from mesh/assets/icons in the theme's colours.
    function icon(name, highlighted) {
        if (!name)
            return ""
        var ink = String(highlighted ? onAccent : text).substring(1)
        var mark = String(highlighted ? onAccent : accent).substring(1)
        return "image://icon/" + name + "/" + ink + "/" + mark
    }
}

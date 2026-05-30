// R2-D2 dome (Master). Line-art, convex UP, with the iconic eye lens.
//
// Note on PathArc direction: QML uses y-down screen coords, so
// `Clockwise` traces from a left anchor up over the top to a right
// anchor (visually a dome bulging up).
import QtQuick
import QtQuick.Shapes

Shape {
    id: icon
    width: 36
    height: 36
    smooth: true
    antialiasing: true
    layer.enabled: true
    layer.samples: 4

    // Audit Medium #37: bind to the live theme accent so the dome stays
    // in the R2 family in both dark (#5e9bd6) and light (#1e5db8) modes.
    // Callers can still override by setting strokeColor explicitly.
    property color strokeColor: theme.colors.colorAccent
    property real  strokeWidth: 2.0

    // Half-circle dome with flat baseline (closed silhouette).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 5;  startY: 26
        PathArc {
            x: 31; y: 26
            radiusX: 13; radiusY: 13
            useLargeArc: false
            direction: PathArc.Clockwise
        }
        PathLine { x: 5; y: 26 }
    }

    // Eye lens — R2's prominent dark eye. Filled rounded rectangle so the
    // glyph reads as R2-D2 even at small sizes.
    Rectangle {
        x: 12; y: 19
        width: 12; height: 5
        radius: 2.5
        color: icon.strokeColor
    }

    // Tiny secondary processor port on the left of the eye.
    Rectangle {
        x: 10; y: 15
        width: 2.5; height: 2.5
        radius: 1.25
        color: icon.strokeColor
    }
}

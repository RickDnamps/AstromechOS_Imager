// R2-D2 head (dome) icon — line-art, convex UP.
// Used as the "Master" mode glyph: the master Pi drives the dome.
//
// Note on PathArc direction: QML's screen coordinates are y-down, so
// `Clockwise` traces from a left anchor up over the top to a right
// anchor (visually a dome bulging up). `Counterclockwise` would dip
// downward, giving an inverted U.
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

    property color strokeColor: "#3dd4c4"
    property real  strokeWidth: 2.0

    // Half-circle dome with flat baseline (closed silhouette).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 6;  startY: 28
        PathArc {
            x: 30; y: 28
            radiusX: 12; radiusY: 12
            useLargeArc: false
            direction: PathArc.Clockwise   // bulges up
        }
        PathLine { x: 6; y: 28 }           // baseline closes the dome
    }
}

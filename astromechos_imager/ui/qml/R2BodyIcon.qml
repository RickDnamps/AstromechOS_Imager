// R2-D2 body (cylinder) icon — line-art.
// Used as the "Slave" mode glyph: the slave Pi sits in the body.
// Vertical rectangle silhouette + 2 internal horizontal "data band" lines.
// All strokes share the same width (uniform line-art).
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

    // Outline (vertical box).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 4
        PathLine { x: 26; y: 4  }
        PathLine { x: 26; y: 32 }
        PathLine { x: 10; y: 32 }
        PathLine { x: 10; y: 4  }
    }

    // Internal horizontal line 1.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 14
        PathLine { x: 24; y: 14 }
    }
    // Internal horizontal line 2.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 22
        PathLine { x: 24; y: 22 }
    }
}

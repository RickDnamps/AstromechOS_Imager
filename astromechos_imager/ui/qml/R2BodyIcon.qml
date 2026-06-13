// R2-D2 body cylinder (Slave). Line-art with 2 data bands + 2 angled
// legs — the legs are what visually anchor it as R2-D2 rather than a
// generic rectangle. Uniform 2 px stroke.
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

    // Bind to the live theme accent so the body stays in the R2 family in
    // both dark and light modes.
    property color strokeColor: theme.colors.colorAccent
    property real  strokeWidth: 2.0

    // Body box.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 4
        PathLine { x: 26; y: 4  }
        PathLine { x: 26; y: 28 }
        PathLine { x: 10; y: 28 }
        PathLine { x: 10; y: 4  }
    }

    // Data band 1.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 13; startY: 12
        PathLine { x: 23; y: 12 }
    }
    // Data band 2.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 13; startY: 20
        PathLine { x: 23; y: 20 }
    }

    // Left leg — slight outward flare.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 13; startY: 28
        PathLine { x: 11; y: 33 }
    }
    // Right leg.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 23; startY: 28
        PathLine { x: 25; y: 33 }
    }
}

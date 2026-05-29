// R2-D2 full silhouette — dome above body. "Flash both" glyph.
// Geometry matches R2HeadIcon + R2BodyIcon scaled to share a viewport,
// joined at the dome's baseline so the silhouette reads as one droid.
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

    // Dome on top (bulges up).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 18
        PathArc {
            x: 26; y: 18
            radiusX: 8; radiusY: 8
            useLargeArc: false
            direction: PathArc.Clockwise
        }
    }

    // Body box just below the dome (shares the dome's baseline).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 18
        PathLine { x: 10; y: 32 }
        PathLine { x: 26; y: 32 }
        PathLine { x: 26; y: 18 }
        PathLine { x: 10; y: 18 }   // closes the top edge = dome baseline
    }

    // Internal horizontal line 1 (upper data band).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 23
        PathLine { x: 24; y: 23 }
    }
    // Internal horizontal line 2 (lower data band).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 28
        PathLine { x: 24; y: 28 }
    }
}

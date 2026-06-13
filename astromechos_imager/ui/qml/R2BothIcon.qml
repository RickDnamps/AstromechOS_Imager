// Full R2-D2 silhouette (dome + body + legs). "Flash both" glyph —
// shares the dome/baseline pattern of R2HeadIcon and the band/leg
// pattern of R2BodyIcon so the three glyphs feel like one family.
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

    // Bind to the live theme accent so the silhouette stays in the R2
    // family in both dark and light modes.
    property color strokeColor: theme.colors.colorAccent
    property real  strokeWidth: 2.0

    // Dome on top (bulges up).
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 14
        PathArc {
            x: 26; y: 14
            radiusX: 8; radiusY: 8
            useLargeArc: false
            direction: PathArc.Clockwise
        }
    }

    // Eye lens — filled rounded rectangle on the dome.
    Rectangle {
        x: 14; y: 9
        width: 8; height: 3
        radius: 1.5
        color: icon.strokeColor
    }

    // Body box.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        joinStyle:   ShapePath.RoundJoin

        startX: 10; startY: 14
        PathLine { x: 10; y: 28 }
        PathLine { x: 26; y: 28 }
        PathLine { x: 26; y: 14 }
        PathLine { x: 10; y: 14 }
    }

    // Data band 1.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 20
        PathLine { x: 24; y: 20 }
    }
    // Data band 2.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 12; startY: 25
        PathLine { x: 24; y: 25 }
    }

    // Legs.
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 13; startY: 28
        PathLine { x: 11; y: 33 }
    }
    ShapePath {
        strokeColor: icon.strokeColor
        strokeWidth: icon.strokeWidth
        fillColor:   "transparent"
        capStyle:    ShapePath.RoundCap
        startX: 23; startY: 28
        PathLine { x: 25; y: 33 }
    }
}

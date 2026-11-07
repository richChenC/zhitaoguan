import QtQuick
import QtQuick3D

Rectangle {
    color: "#0f2233"

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#0f2233"
        }
        PerspectiveCamera {
            id: camera
            position: Qt.vector3d(0, 4.8, 8.5)
            eulerRotation.x: -28
        }
        DirectionalLight {
            eulerRotation.x: -35
            eulerRotation.y: -25
            brightness: 1.8
        }
        Node {
            Repeater3D {
                model: 50
                delegate: Model {
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.12, 0.75, 0.12)
                    position: Qt.vector3d((index % 10 - 4.5) * 0.62,
                                          0,
                                          (Math.floor(index / 10) - 2) * 0.62)
                    materials: [
                        PrincipledMaterial {
                            baseColor: (index % 11 === 0) ? "#ef6a5b" : "#4ea4c8"
                            metalness: 0.15
                            roughness: 0.35
                        }
                    ]
                }
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 18
        color: "#d91f2d3d"
        radius: 5
        width: 250
        height: 72
        Column {
            anchors.fill: parent
            anchors.margins: 12
            Text { text: "原生 Qt Quick 3D"; color: "white"; font.pixelSize: 16; font.bold: true }
            Text { text: "50 根套管阵列 · 红色表示重点关注"; color: "#c7d8e5"; font.pixelSize: 12 }
        }
    }
}

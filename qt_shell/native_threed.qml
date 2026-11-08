import QtQuick
import QtQuick3D

Rectangle {
    id: root
    color: "#e8eef0"
    property var tubes: []
    property real yaw: 0
    property real pitch: -34
    property real zoomFactor: 1
    property bool showDefect: true
    property bool showReview: true
    property bool showNdd: true
    property bool showMissing: true
    signal tubeSelected(int tube)

    function pickTube(x, y) {
        const result = scene.pick(x, y)
        return result.objectHit ? result.objectHit.tubeNumber : 0
    }

    View3D {
        id: scene
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#e8eef0"
            antialiasingMode: SceneEnvironment.MSAA
        }
        Node {
            eulerRotation.y: root.yaw
            Node {
                eulerRotation.x: root.pitch + 34
                PerspectiveCamera {
                    id: camera
                    position: Qt.vector3d(0, 780 / root.zoomFactor, 1160 / root.zoomFactor)
                    eulerRotation.x: -34
                    clipFar: 5000
                }
            }
        }
        DirectionalLight {
            eulerRotation.x: -40
            eulerRotation.y: -25
            brightness: 1.4
            ambientColor: "#808080"
        }
        Node {
            Repeater3D {
                model: root.tubes
                delegate: Model {
                required property var modelData
                property int tubeNumber: modelData.tube
                property string category: modelData.category
                source: "#Cylinder"
                pickable: true
                visible: category === "defect" ? root.showDefect :
                         category === "incomplete" ? root.showReview :
                         category === "ndd" ? root.showNdd : root.showMissing
                scale: Qt.vector3d(0.18, 1.0, 0.18)
                position: Qt.vector3d(modelData.x, 0, modelData.z)
                materials: PrincipledMaterial {
                    baseColor: modelData.color
                    roughness: 0.6
                }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            property real lastX: 0
            property real lastY: 0
            property bool dragged: false
            onPressed: function(mouse) {
                lastX = mouse.x
                lastY = mouse.y
                dragged = false
            }
            onPositionChanged: function(mouse) {
                if (!pressed)
                    return
                var dx = mouse.x - lastX
                var dy = mouse.y - lastY
                if (Math.abs(dx) + Math.abs(dy) > 1)
                    dragged = true
                root.yaw += dx * 0.35
                root.pitch = Math.max(-80, Math.min(20, root.pitch - dy * 0.25))
                lastX = mouse.x
                lastY = mouse.y
            }
            onWheel: function(wheel) {
                root.zoomFactor = Math.max(0.55, Math.min(2.4, root.zoomFactor + wheel.angleDelta.y / 2400))
            }
            onClicked: function(mouse) {
                if (dragged)
                    return
                const tube = root.pickTube(mouse.x, mouse.y)
                if (tube)
                    root.tubeSelected(tube)
            }
        }
    }
    Text {
        anchors.centerIn: parent
        visible: root.tubes.length === 0
        text: "请选择有检测数据的范围"
        color: "#465d65"
        font.pixelSize: 18
    }
}

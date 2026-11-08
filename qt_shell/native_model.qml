import QtQuick
import QtQuick3D
import Thimble.Native 1.0

Rectangle {
    id: root
    color: "#edf2f4"
    property var tubes: []
    property var columns: []
    property var defects: []
    property int selectedTube: 0
    property string displayMode: "assembly"
    property bool showVessel: true
    property bool showSupports: true
    property bool showSockets: true
    property bool showDome: true
    property bool showPlates: true
    property bool enlargeTubes: true
    property real modelOpacity: 0.65
    property real yaw: 0
    property real pitch: -34
    property real zoomFactor: 1
    property real panX: 0
    property real panY: 0
    property bool showDefect: true
    property bool showReview: true
    property bool showNdd: true
    property bool showMissing: true
    property string tubeType: ""
    property bool showAxes: false
    property real explode: 0
    property bool clipEnabled: false
    property string clipAxis: "x"
    property real clipOffset: 0
    property bool measurementEnabled: false
    property int measurementCount: 0
    property vector3d measureA: Qt.vector3d(0,0,0)
    property vector3d measureB: Qt.vector3d(0,0,0)
    signal tubeSelected(int tube)
    signal measurementChanged(string value)
    component SectionMaterial: CustomMaterial {
        property color tint: "#a9bac6"
        property real alphaValue: root.modelOpacity
        property bool clipActive: root.clipEnabled
        property real clipDistance: root.clipOffset
        property vector3d clipNormal: Qt.vector3d(root.clipAxis === "x" ? 1 : 0,
                                                  root.clipAxis === "y" ? 1 : 0,
                                                  root.clipAxis === "z" ? 1 : 0)
        shadingMode: CustomMaterial.Shaded
        cullMode: Material.NoCulling
        sourceBlend: CustomMaterial.SrcAlpha
        destinationBlend: CustomMaterial.OneMinusSrcAlpha
        vertexShader: "shaders/section.vert"
        fragmentShader: "shaders/section.frag"
    }
    ReferenceGeometry { id: tubeGeometry; partId: "P01" }
    ReferenceGeometry { id: socketGeometry; partId: "P02" }
    ReferenceGeometry { id: boltGeometry; partId: "P03" }
    ReferenceGeometry { id: nutGeometry; partId: "P04" }
    ReferenceGeometry { id: penetrationGeometry; partId: "P05" }
    ReferenceGeometry { id: supportGeometry; partId: "P06" }

    function pickTube(x, y) {
        const hit = pickVisible(x, y)
        return hit ? hit.objectHit.tubeNumber : 0
    }
    function pickVisible(x, y) {
        const hits = scene.pickAll(x, y)
        for (const hit of hits) {
            if (!hit.objectHit || !hit.objectHit.tubeNumber) continue
            const p = hit.scenePosition
            if (clipEnabled && (clipAxis === "x" ? p.x : clipAxis === "y" ? p.y : p.z) > clipOffset) continue
            return hit
        }
        return null
    }
    function measureAt(x, y) {
        const hit = pickVisible(x, y)
        if (!hit) return
        if (measurementCount !== 1) {
            measureA = hit.scenePosition
            measurementCount = 1
            measurementChanged("已取第一点，请取第二点")
        } else {
            measureB = hit.scenePosition
            measurementCount = 2
            const d = measureB.minus(measureA)
            measurementLine.eulerRotation = Qt.vector3d(
                -Math.atan2(d.y, Math.sqrt(d.x*d.x+d.z*d.z))*180/Math.PI,
                Math.atan2(d.x,d.z)*180/Math.PI, 0)
            const distance = Math.sqrt(d.x*d.x+d.y*d.y+d.z*d.z)
            measurementChanged("模型距离 " + distance.toFixed(2) + " mm（参考几何，非实测）")
        }
    }
    function resetView() {
        yaw = 0; pitch = -34; zoomFactor = 1; panX = 0; panY = 0
    }
    View3D {
        id: scene
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#edf2f4"
            antialiasingMode: SceneEnvironment.MSAA
        }
        Node {
            eulerRotation.y: root.yaw
            Node {
                eulerRotation.x: root.pitch + 34
                PerspectiveCamera {
                    id: camera
                    position: Qt.vector3d(root.panX, 3800/root.zoomFactor+root.panY, 5800/root.zoomFactor)
                    eulerRotation.x: -34
                    clipNear: 1
                    clipFar: 50000
                }
            }
        }
        DirectionalLight {
            eulerRotation.x: -40
            eulerRotation.y: -25
            brightness: 0.8
            ambientColor: "#505050"
        }
        DirectionalLight { eulerRotation: Qt.vector3d(20,160,0); brightness: 0.35 }
        Model {
            visible: root.showDome && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: ReferenceGeometry { partId: "dome" }
            y: -root.explode * 800
            materials: SectionMaterial { tint: "#a9bac6"; alphaValue: 0.12 }
        }
        Model {
            visible: root.showVessel && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: ReferenceGeometry { partId: "vessel" }
            materials: SectionMaterial { tint: "#a9bac6"; alphaValue: 0.08 }
        }
        Repeater3D {
            model: ["ucsPlate", "secondaryGrid"]
            delegate: Model {
                required property string modelData
                visible: root.showPlates && root.displayMode === "assembly" && root.tubes.length > 0
                geometry: ReferenceGeometry { partId: modelData }
                y: root.explode * (modelData === "ucsPlate" ? 800 : 400)
                materials: SectionMaterial { tint: "#839cab"; alphaValue: root.modelOpacity * .65 }
            }
        }
        Repeater3D {
            model: root.columns
            delegate: Model {
                required property var modelData
                geometry: ReferenceGeometry { partId: modelData.meshId }
                visible: root.showSupports && root.displayMode === "assembly" && root.tubes.length > 0
                materials: SectionMaterial {
                    tint: modelData.type === "core-hollow" ? "#8299a7" :
                               modelData.type === "sec-hollow" ? "#94a488" : "#b1a88e"
                }
            }
        }
        Repeater3D {
            model: root.tubes
            delegate: Node {
                id: tubeNode
                required property var modelData
                property bool single: root.displayMode !== "assembly" && root.displayMode !== "plate"
                property bool selected: modelData.tube === root.selectedTube
                visible: (!single || selected) && (!root.tubeType || modelData.type === root.tubeType) &&
                    (modelData.category === "defect" ? root.showDefect :
                     modelData.category === "incomplete" ? root.showReview :
                     modelData.category === "ndd" ? root.showNdd : root.showMissing)
                position: single ? Qt.vector3d(0,root.displayMode === "socket" ? -760 : -modelData.length/2,0) :
                                   Qt.vector3d(modelData.x,modelData.yBase,modelData.z)
                scale: root.displayMode === "socket" ? Qt.vector3d(12,12,12) : Qt.vector3d(1,1,1)
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    geometry: tubeGeometry
                    pickable: true
                    visible: root.displayMode !== "socket" && root.displayMode !== "plate"
                    scale: Qt.vector3d(root.enlargeTubes ? 3 : 1,
                                       root.displayMode === "plate" ? .015 : tubeNode.modelData.length/3000,
                                       root.enlargeTubes ? 3 : 1)
                    materials: SectionMaterial {
                        tint: tubeNode.selected ? "#f4bd3c" : tubeNode.modelData.color
                        alphaValue: tubeNode.selected ? 1 : root.modelOpacity
                    }
                }
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    source: "#Cylinder"
                    visible: root.displayMode === "plate"
                    pickable: true
                    scale: Qt.vector3d(.55,.05,.55)
                    materials: SectionMaterial {
                        tint: tubeNode.selected ? "#f4bd3c" : tubeNode.modelData.color
                        alphaValue: 1
                    }
                }
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    visible: root.showSockets && root.displayMode !== "plate"
                    geometry: socketGeometry
                    pickable: true
                    y: root.explode * 150
                    materials: SectionMaterial { tint:"#aab6c0"; alphaValue: 1 }
                }
                Model {
                    visible: root.showSockets && tubeNode.single && root.displayMode !== "plate"
                    geometry: nutGeometry
                    y: root.explode * 230
                    materials: SectionMaterial { tint:"#b6aa83"; alphaValue: 1 }
                }
                Model {
                    visible: root.showSockets && tubeNode.single && root.displayMode === "full"
                    geometry: penetrationGeometry
                    materials: SectionMaterial { tint:"#7c9aa4"; alphaValue:.45 }
                }
                Model {
                    visible: root.showSupports && tubeNode.single && root.displayMode === "full"
                    geometry: supportGeometry
                    materials: SectionMaterial { tint:"#8b9b7b"; alphaValue:.3 }
                }
                Model {
                    visible: root.showSockets && tubeNode.single && root.displayMode === "socket"
                    geometry: boltGeometry
                    y: root.explode * 300
                    materials: SectionMaterial { tint: "#889aa7"; alphaValue: 1 }
                }
            }
        }
        Repeater3D {
            model: root.defects
            delegate: Model {
                required property var modelData
                property int tubeNumber: modelData.tube
                source: "#Sphere"
                pickable: true
                visible: root.showDefect && root.displayMode !== "plate" && root.displayMode !== "socket" &&
                         (root.displayMode === "assembly" || modelData.tube === root.selectedTube)
                position: root.displayMode === "assembly" ? Qt.vector3d(modelData.x,modelData.y,modelData.z) :
                          Qt.vector3d(0,modelData.y-modelData.yBase-modelData.length/2,0)
                scale: Qt.vector3d(.45,.45,.45)
                materials: SectionMaterial { tint:"#c8424a"; alphaValue: 1 }
            }
        }
        Node {
            visible: root.showAxes
            Model {
                source: "#Cube"; position: Qt.vector3d(500,0,0); scale: Qt.vector3d(10,.035,.035)
                materials: PrincipledMaterial { baseColor:"#c45b4e" }
            }
            Model {
                source: "#Cube"; position: Qt.vector3d(0,500,0); scale: Qt.vector3d(.035,10,.035)
                materials: PrincipledMaterial { baseColor:"#639247" }
            }
            Model {
                source: "#Cube"; position: Qt.vector3d(0,0,500); scale: Qt.vector3d(.035,.035,10)
                materials: PrincipledMaterial { baseColor:"#387fb1" }
            }
        }
        Model {
            visible: root.measurementEnabled && root.measurementCount > 0
            source: "#Sphere"; position: root.measureA; scale: Qt.vector3d(.45,.45,.45)
            materials: PrincipledMaterial { baseColor:"#333333" }
        }
        Model {
            visible: root.measurementEnabled && root.measurementCount > 1
            source: "#Sphere"; position: root.measureB; scale: Qt.vector3d(.45,.45,.45)
            materials: PrincipledMaterial { baseColor:"#333333" }
        }
        Model {
            id: measurementLine
            visible: root.measurementEnabled && root.measurementCount > 1
            source: "#Cube"
            position: root.measureA.plus(root.measureB).times(.5)
            scale: Qt.vector3d(.035,.035,root.measureB.minus(root.measureA).length()/100)
            materials: PrincipledMaterial { baseColor:"#333333" }
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
            property real lastX: 0
            property real lastY: 0
            property real moved: 0
            onPressed: function(mouse) { lastX=mouse.x; lastY=mouse.y; moved=0 }
            onPositionChanged: function(mouse) {
                if (!pressed) return
                const dx=mouse.x-lastX, dy=mouse.y-lastY
                moved += Math.abs(dx)+Math.abs(dy)
                if (pressedButtons & (Qt.MiddleButton | Qt.RightButton)) {
                    root.panX -= dx*4/root.zoomFactor
                    root.panY += dy*4/root.zoomFactor
                } else {
                    root.yaw += dx*.35
                    root.pitch=Math.max(-90,Math.min(50,root.pitch-dy*.25))
                }
                lastX=mouse.x; lastY=mouse.y
            }
            onWheel: function(wheel) { root.zoomFactor=Math.max(.35,Math.min(12,root.zoomFactor+wheel.angleDelta.y/1200)) }
            onClicked: function(mouse) {
                if (moved > 5) return
                if (root.measurementEnabled) { root.measureAt(mouse.x,mouse.y); return }
                const tube=root.pickTube(mouse.x,mouse.y)
                if (tube) { root.selectedTube=tube; root.tubeSelected(tube) }
            }
            onDoubleClicked: root.resetView()
        }
    }
    Text {
        anchors.centerIn: parent
        visible: root.tubes.length === 0
        text: "请选择有检测数据的范围"
        color:"#465d65"; font.pixelSize:18
    }
}

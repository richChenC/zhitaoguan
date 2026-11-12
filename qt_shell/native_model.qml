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
    readonly property vector3d isoDirection: displayMode === "joint" ? Qt.vector3d(.55, .38, .74) :
        displayMode === "full" ? Qt.vector3d(.45, .12, .45) :
        displayMode === "socket" ? Qt.vector3d(.6, .35, .7) : Qt.vector3d(.52, .40, .76)
    readonly property real defaultYaw: Math.atan2(isoDirection.x, isoDirection.z) * 180 / Math.PI
    readonly property real defaultPitch: -Math.atan2(isoDirection.y,
        Math.sqrt(isoDirection.x*isoDirection.x + isoDirection.z*isoDirection.z)) * 180 / Math.PI
    readonly property real cameraTangent: Math.tan(19 * Math.PI / 180)
    readonly property real detailDistance: displayMode === "socket" ? 3960 :
        displayMode === "joint" ? 12 * 430 * Math.sqrt(.55*.55 + .38*.38 + .74*.74) :
        displayMode === "full" ? 2 * ((tubes.find(t => t.tube === selectedTube) || {}).length || 3000) : 6934
    property real yaw: defaultYaw
    property real pitch: defaultPitch
    property real zoomFactor: 1
    property real panX: 0
    property real panY: 0
    property bool orthographicView: false
    readonly property bool orthographicActive: orthographicView && displayMode === "assembly"
    property bool mirrorTop: false
    readonly property bool mirroredActive: orthographicActive && mirrorTop
    property bool standardAligned: true
    readonly property real domeAlpha: orthographicActive && standardAligned ? .07 : .26
    readonly property real plateAlpha: orthographicActive && standardAligned ? .13 : .42
    property vector3d assemblyMinimum: Qt.vector3d(-2192.96, -2192.96, -2192.96)
    property vector3d assemblyMaximum: Qt.vector3d(2192.96, 1637.4, 2192.96)
    property real coveredRight: 0
    property real coveredBottom: 0
    property var geometryBounds: ({})
    property var framing: ({center: Qt.vector3d(0, 0, 0), distance: 6934, magnification: .1,
                            minimum: assemblyMinimum, maximum: assemblyMaximum})
    readonly property vector3d fittedMinimum: framing.minimum
    readonly property vector3d fittedMaximum: framing.maximum
    property bool showDefect: true
    property bool showReview: true
    property bool showNdd: true
    property bool showMissing: true
    property string tubeType: ""
    property bool showAxes: false
    property bool showPlateOverlay: false
    property int plateUnit: 0
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
    signal viewManipulated()
    signal viewReset()
    component SectionMaterial: CustomMaterial {
        property color tint: "#a9bac6"
        property real alphaValue: root.modelOpacity
        property bool clipActive: root.clipEnabled || root.displayMode === "socket"
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
            if ((clipEnabled || displayMode === "socket") &&
                (clipAxis === "x" ? p.x : clipAxis === "y" ? p.y : p.z) > clipOffset) continue
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
        orthographicView = false; mirrorTop = false; standardAligned = true
        yaw = defaultYaw; pitch = defaultPitch; zoomFactor = 1; panX = 0; panY = 0
        fitView()
        viewReset()
    }
    function fitView() {
        if (width <= 0 || height <= 0) return
        let low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity]
        const include = (bounds, position = [0,0,0], scale = [1,1,1]) => {
            if (!bounds) return
            for (let i = 0; i < 3; ++i) {
                low[i] = Math.min(low[i], bounds[0][i]*scale[i] + position[i])
                high[i] = Math.max(high[i], bounds[1][i]*scale[i] + position[i])
            }
        }
        if (showVessel) include(geometryBounds.vessel ||
            [[assemblyMinimum.x, assemblyMinimum.y, assemblyMinimum.z],
             [assemblyMaximum.x, assemblyMaximum.y, assemblyMaximum.z]])
        if (orthographicActive && showDome) include(geometryBounds.dome, [0,-explode*800,0])
        if (showPlates) {
            include(geometryBounds.ucsPlate, [0,explode*800,0])
            include(geometryBounds.secondaryGrid, [0,explode*400,0])
        }
        if (showSupports) for (const column of columns) include(column.bounds)
        for (const tube of tubes) {
            if ((tubeType && tube.type !== tubeType) ||
                !(tube.category === "defect" ? showDefect : tube.category === "incomplete" ? showReview :
                  tube.category === "ndd" ? showNdd : showMissing)) continue
            const position = [tube.x, tube.yBase, tube.z]
            include(geometryBounds.P01, position, [enlargeTubes ? 3 : 1, tube.length/3000, enlargeTubes ? 3 : 1])
            if (showSockets) include(geometryBounds.P02, [tube.x, tube.yBase+explode*150, tube.z])
        }
        if (!isFinite(low[0])) {
            low = [assemblyMinimum.x, assemblyMinimum.y, assemblyMinimum.z]
            high = [assemblyMaximum.x, assemblyMaximum.y, assemblyMaximum.z]
        }
        if (clipEnabled) {
            const axis = clipAxis === "x" ? 0 : clipAxis === "y" ? 1 : 2
            high[axis] = Math.max(low[axis], Math.min(high[axis], clipOffset))
        }
        const center = low.map((v, i) => (v + high[i]) / 2)
        const ry = yaw * Math.PI / 180, rx = pitch * Math.PI / 180
        const right = [Math.cos(ry), 0, -Math.sin(ry)]
        const up = [Math.sin(ry)*Math.sin(rx), Math.cos(rx), Math.cos(ry)*Math.sin(rx)]
        const toward = [Math.sin(ry)*Math.cos(rx), -Math.sin(rx), Math.cos(ry)*Math.cos(rx)]
        const availableW = Math.max(120, width - coveredRight)
        const availableH = Math.max(120, height - coveredBottom)
        const tanV = cameraTangent
        let maxU = 1, maxV = 1, distance = 1
        for (let mask = 0; mask < 8; ++mask) {
            const p = low.map((v, i) => ((mask & (1 << i)) ? high[i] : v) - center[i])
            const dot = vector => p.reduce((sum, value, i) => sum + value * vector[i], 0)
            const u = dot(right), v = dot(up), depth = dot(toward)
            maxU = Math.max(maxU, Math.abs(u)); maxV = Math.max(maxV, Math.abs(v))
            // Account for parallax from shifting the camera around the overlay panels.
            const fitU = Math.abs(u - coveredRight * tanV * depth / height)
            const fitV = Math.abs(v + coveredBottom * tanV * depth / height)
            distance = Math.max(distance, Math.max(fitU * height / (tanV * availableW),
                                                   fitV * height / (tanV * availableH)) + depth)
        }
        framing = {center: Qt.vector3d(center[0], center[1], center[2]),
                   distance: Math.max(100, distance * 1.06),
                   magnification: Math.min(availableW / (2 * maxU * 1.06),
                                           availableH / (2 * maxV * 1.06)),
                   minimum: Qt.vector3d(low[0], low[1], low[2]),
                   maximum: Qt.vector3d(high[0], high[1], high[2])}
    }
    onWidthChanged: fitView()
    onHeightChanged: fitView()
    onAssemblyMinimumChanged: fitView()
    onAssemblyMaximumChanged: fitView()
    onCoveredRightChanged: fitView()
    onCoveredBottomChanged: fitView()
    onClipEnabledChanged: fitView()
    onClipAxisChanged: fitView()
    onClipOffsetChanged: fitView()
    onGeometryBoundsChanged: fitView()
    onOrthographicActiveChanged: fitView()
    onColumnsChanged: fitView()
    onTubesChanged: fitView()
    onShowVesselChanged: fitView()
    onShowDomeChanged: fitView()
    onShowPlatesChanged: fitView()
    onShowSupportsChanged: fitView()
    onShowSocketsChanged: fitView()
    onEnlargeTubesChanged: fitView()
    onExplodeChanged: fitView()
    onTubeTypeChanged: fitView()
    onShowDefectChanged: fitView()
    onShowReviewChanged: fitView()
    onShowNddChanged: fitView()
    onShowMissingChanged: fitView()
    Component.onCompleted: fitView()
    function projectPoint(point) { return scene.mapFrom3DScene(point) }
    View3D {
        id: scene
        anchors.fill: parent
        camera: root.orthographicActive ? orthographicCamera : perspectiveCamera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#edf2f4"
            antialiasingMode: SceneEnvironment.MSAA
            tonemapMode: SceneEnvironment.TonemapModeAces
        }
        Node {
            position: root.displayMode === "assembly" ? root.framing.center : Qt.vector3d(0,0,0)
            eulerRotation.y: root.yaw
            Node {
                eulerRotation.x: root.pitch
                readonly property real distance: (root.displayMode === "assembly" ? root.framing.distance : root.detailDistance) /
                    (root.orthographicActive ? 1 : root.zoomFactor)
                readonly property real unitsPerPixel: root.orthographicActive ?
                    1 / (root.framing.magnification * root.zoomFactor) : 2 * root.cameraTangent * distance / Math.max(1, scene.height)
                readonly property real shiftX: root.displayMode === "assembly" ? root.coveredRight * unitsPerPixel / 2 : 0
                readonly property real shiftY: root.displayMode === "assembly" ? -root.coveredBottom * unitsPerPixel / 2 : 0
                PerspectiveCamera {
                    id: perspectiveCamera
                    objectName: "perspectiveCamera"
                    fieldOfView: 38
                    position: Qt.vector3d(root.panX + parent.shiftX, root.panY + parent.shiftY, parent.distance)
                    clipNear: 1
                    clipFar: 50000
                }
                OrthographicCamera {
                    id: orthographicCamera
                    objectName: "orthographicCamera"
                    // Mirror only the top projection, preserving world geometry and native ray picking.
                    position: Qt.vector3d(root.panX + parent.shiftX * (root.mirroredActive ? -1 : 1),
                                          root.panY + parent.shiftY, parent.distance)
                    scale: Qt.vector3d(root.mirroredActive ? -1 : 1, 1, 1)
                    horizontalMagnification: root.framing.magnification * root.zoomFactor
                    verticalMagnification: horizontalMagnification
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
            objectName: "plateOverlayModel"
            visible: root.showPlateOverlay && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: ReferenceGeometry { partId: "plateOverlay" }
            pickable: false
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                cullMode: Material.NoCulling
                diffuseMap: Texture {
                    textureData: PlateTextureData {
                        active: root.showPlateOverlay && root.displayMode === "assembly"
                        unitNumber: root.plateUnit
                        selectedTube: root.selectedTube
                        projectionMirror: root.mirroredActive
                    }
                }
            }
        }
        Model {
            visible: root.showDome && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: ReferenceGeometry { partId: "dome" }
            y: -root.explode * 800
            materials: SectionMaterial { tint: "#a9bac6"; alphaValue: root.domeAlpha }
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
                materials: SectionMaterial { tint: "#839cab"; alphaValue: root.plateAlpha }
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
                position: single ? Qt.vector3d(0,root.displayMode === "socket" || root.displayMode === "joint" ? -760 : -modelData.length/2,0) :
                                   Qt.vector3d(modelData.x,modelData.yBase,modelData.z)
                scale: root.displayMode === "socket" || root.displayMode === "joint" ? Qt.vector3d(12,12,12) : Qt.vector3d(1,1,1)
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    geometry: tubeGeometry
                    pickable: true
                    visible: root.displayMode !== "socket" && root.displayMode !== "plate"
                    scale: Qt.vector3d(root.enlargeTubes ? 3 : 1,
                                       root.displayMode === "joint" ? .08 : tubeNode.modelData.length/3000,
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
                    visible: root.showSockets && tubeNode.single && (root.displayMode === "full" || root.displayMode === "joint")
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
                visible: root.showDefect && root.displayMode !== "plate" && root.displayMode !== "socket" && root.displayMode !== "joint" &&
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
                if (root.standardAligned && (dx || dy)) {
                    root.standardAligned = false
                    root.viewManipulated()
                }
                if (pressedButtons & (Qt.MiddleButton | Qt.RightButton)) {
                    const units = root.orthographicActive ? 1/(root.framing.magnification*root.zoomFactor) :
                        2*root.cameraTangent*(root.displayMode === "assembly" ? root.framing.distance : root.detailDistance) /
                        (Math.max(1, scene.height)*root.zoomFactor)
                    root.panX -= dx*units*(root.mirroredActive ? -1 : 1)
                    root.panY += dy*units
                } else {
                    root.yaw += dx*.35
                    root.pitch=Math.max(-90,Math.min(90,root.pitch-dy*.25))
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

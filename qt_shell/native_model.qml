import QtQuick
import QtQuick3D
import Thimble.Native 1.0

Rectangle {
    id: root
    property bool darkTheme: false
    color: darkTheme ? "#101617" : "#f2f5f7"
    property var tubes: []
    property var tubeColors: ({})
    property var columns: []
    property var columnVisibility: ({})
    property var defects: []
    property int selectedTube: 0
    property string displayMode: "assembly"
    property bool showVessel: true
    property bool showSupports: true
    property bool showSockets: true
    property bool showPenetrations: true
    property bool showDome: true
    property bool showPlates: true
    property bool enlargeTubes: true
    property real modelOpacity: 1
    property real renderExposure: 1.05
    property real detailLength: 3000
    property var partVisibility: ({P01: true, P02: true, P03: false, P04: false, P05: true, P06: true})
    property var partColors: ({P01: "#667c8c", P02: "#9fa9b5", P03: "#d9d2c4",
                              P04: "#c8b89a", P05: "#8f9aa6", P06: "#9aa4b0"})
    property var partMetalness: ({P01:.72, P02:.85, P03:.8, P04:.78, P05:.55, P06:.5})
    property bool ghostContext: true
    property var stations: []
    property bool showStations: true
    property var dimensionLabels: []
    property var projectedAnnotations: []
    property bool suppressScale: true
    readonly property bool scaleVisible: displayMode === "full" && !suppressScale &&
        width-coveredRight > 240 && height-coveredBottom >= 330
    readonly property real scaleHeight: Math.min(330, Math.max(240, height-coveredBottom-88))
    readonly property real scaleX: width-coveredRight-210
    readonly property var annotationState: [yaw,pitch,zoomFactor,panX,panY,width,height,detailLength,displayMode,
        coveredLeft,coveredRight,coveredBottom,dimensionLabels,stations,showStations,scaleVisible]
    onAnnotationStateChanged: annotationTimer.restart()
    readonly property bool singleMode: displayMode === "joint" || displayMode === "full" || displayMode === "socket"
    readonly property real detailTarget: displayMode === "full" ? detailLength/2 : displayMode === "socket" ? 66 : 52
    readonly property vector3d isoDirection: displayMode === "joint" ? Qt.vector3d(.55, .38, .74) :
        displayMode === "full" ? Qt.vector3d(.45, .12, .45) :
        displayMode === "socket" ? Qt.vector3d(.6, .35, .7) : Qt.vector3d(.52, .40, .76)
    readonly property real defaultYaw: Math.atan2(isoDirection.x, isoDirection.z) * 180 / Math.PI
    readonly property real defaultPitch: -Math.atan2(isoDirection.y,
        Math.sqrt(isoDirection.x*isoDirection.x + isoDirection.z*isoDirection.z)) * 180 / Math.PI
    readonly property real cameraTangent: Math.tan(19 * Math.PI / 180)
    readonly property real detailBaseDistance: displayMode === "socket" ? 330 :
        displayMode === "joint" ? 430 * Math.sqrt(.55*.55 + .38*.38 + .74*.74) :
        displayMode === "full" ? 2 * detailLength : 6934
    readonly property real detailDistance: detailBaseDistance * Math.max(
        1, width / Math.max(120, width-coveredLeft-coveredRight),
        height / Math.max(120, height-coveredBottom))
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
    property real coveredLeft: 0
    property real coveredBottom: 0
    property var footerBounds: [0,0,0,0]
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
    property bool showAxes: true
    property bool showDetailAxis: false
    readonly property var axisProjection: {
        const rotation = perspectiveCamera.sceneRotation
        const definitions = [
            {direction: Qt.vector3d(1,0,0), color:"#d0453e", text:"X"},
            {direction: Qt.vector3d(0,1,0), color:"#2e9c62", text:"Y"},
            {direction: Qt.vector3d(0,0,1), color:"#2b6fb8", text:"Z"}
        ]
        return definitions.map(axis => {
            const vector = perspectiveCamera.mapDirectionFromScene(axis.direction)
            return {text:axis.text, color:axis.color,
                    x:69+vector.x*42*(mirroredActive ? -1 : 1), y:69-vector.y*42, z:vector.z}
        }).sort((a,b) => a.z-b.z)
    }
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
    signal partSelected(string partId)
    signal stationSelected(string stationId)
    signal measurementChanged(string value)
    signal viewManipulated()
    signal viewReset()
    component SectionMaterial: CustomMaterial {
        property color tint: "#a9bac6"
        property real alphaValue: root.modelOpacity
        property real roughnessValue: .34
        property real metalnessValue: .8
        property color emissiveTint: "#000000"
        property real emissiveIntensity: 0
        property real exposureValue: root.renderExposure
        property bool clipActive: root.clipEnabled || root.displayMode === "socket"
        property real clipDistance: root.clipOffset
        property vector3d clipNormal: Qt.vector3d(root.clipAxis === "x" ? 1 : 0,
                                                  root.clipAxis === "y" ? 1 : 0,
                                                  root.clipAxis === "z" ? 1 : 0)
        shadingMode: CustomMaterial.Shaded
        cullMode: Material.NoCulling
        sourceBlend: alphaValue < 1 ? CustomMaterial.SrcAlpha : CustomMaterial.NoBlend
        destinationBlend: alphaValue < 1 ? CustomMaterial.OneMinusSrcAlpha : CustomMaterial.NoBlend
        sourceAlphaBlend: CustomMaterial.One
        destinationAlphaBlend: CustomMaterial.OneMinusSrcAlpha
        vertexShader: "shaders/section.vert"
        fragmentShader: "shaders/section.frag"
    }
    function pickTube(x, y) {
        const hit = pickVisible(x, y)
        return hit ? hit.objectHit.tubeNumber : 0
    }
    function pickPart(x, y) {
        const hit = pickVisible(x, y)
        return hit && hit.objectHit.partId ? hit.objectHit.partId : ""
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
        if (showSupports) for (const column of columns) {
            if (columnVisibility[column.type] !== false) include(column.bounds)
        }
        for (const tube of tubes) {
            if (!(tube.category === "defect" ? showDefect : tube.category === "incomplete" ? showReview :
                  tube.category === "ndd" ? showNdd : showMissing)) continue
            const position = [tube.x, tube.yBase, tube.z]
            include(geometryBounds.P01, position, [enlargeTubes ? 3 : 1, tube.length/3000, enlargeTubes ? 3 : 1])
            if (showSockets) include(geometryBounds.P02, [tube.x, tube.yBase+explode*150, tube.z])
            if (showPenetrations) include(geometryBounds.P05, position)
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
        const availableW = Math.max(120, width - coveredLeft - coveredRight)
        const availableH = Math.max(120, height - coveredBottom)
        const tanV = cameraTangent
        let maxU = 1, maxV = 1, distance = 1
        for (let mask = 0; mask < 8; ++mask) {
            const p = low.map((v, i) => ((mask & (1 << i)) ? high[i] : v) - center[i])
            const dot = vector => p.reduce((sum, value, i) => sum + value * vector[i], 0)
            const u = dot(right), v = dot(up), depth = dot(toward)
            maxU = Math.max(maxU, Math.abs(u)); maxV = Math.max(maxV, Math.abs(v))
            // Account for parallax from shifting the camera around the overlay panels.
            const fitU = Math.abs(u - (coveredRight-coveredLeft) * tanV * depth / height)
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
    onCoveredLeftChanged: fitView()
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
    onShowPenetrationsChanged: fitView()
    onEnlargeTubesChanged: fitView()
    onExplodeChanged: fitView()
    onTubeTypeChanged: fitView()
    onShowDefectChanged: fitView()
    onShowReviewChanged: fitView()
    onShowNddChanged: fitView()
    onShowMissingChanged: fitView()
    Component.onCompleted: fitView()
    function projectPoint(point) { return scene.mapFrom3DScene(point) }
    function updateAnnotations() {
        if (!singleMode || width <= 0 || height <= 0) {
            projectedAnnotations = []
            return
        }
        const labels = []
        const left = coveredLeft + 6, right = width-coveredRight-6
        const bottom = height-coveredBottom-6
        const overlaps = (a,b) => a.x < b.x+b.w+3 && a.x+a.w+3 > b.x &&
                                   a.y < b.y+b.h+3 && a.y+a.h+3 > b.y
        const place = (id, text, point, station, estimated) => {
            const p = projectPoint(point)
            if (!(p.z > 0 && p.z < 50000) || p.x < left || p.x > right || p.y < 0 || p.y > bottom) return
            annotationMetrics.text = text
            const w = annotationMetrics.width + 12, h = 22
            if (w > right-left) return
            const positions = [Math.max(left,Math.min(right-w,p.x+(station ? 44 : 54))),
                               Math.max(left,Math.min(right-w,p.x-w-14))]
            for (const x of positions) for (let attempt=0; attempt<17; ++attempt) {
                const step = attempt ? Math.ceil(attempt/2)*25*(attempt%2 ? 1 : -1) : 0
                const rect = {x:x, y:Math.max(2,Math.min(bottom-h,p.y-16+step)), w:w, h:h}
                if (labels.some(label => overlaps(rect,label))) continue
                if (scaleVisible && overlaps(rect,{x:scaleX,y:12,w:196,h:scaleHeight+76})) continue
                labels.push({id:id,text:text,x:rect.x,y:rect.y,w:w,h:h,anchorX:p.x,anchorY:p.y,
                             station:station,estimated:estimated})
                return
            }
        }
        for (const label of dimensionLabels)
            place(label.id,label.text,Qt.vector3d(label.anchor[0],label.anchor[1]-detailTarget,label.anchor[2]),false,false)
        if (showStations && displayMode !== "full")
            for (const station of stations)
                place(station.id,station.label,Qt.vector3d(0,station.y-detailTarget,0),true,station.status === "推定")
        projectedAnnotations = labels
    }
    TextMetrics { id: annotationMetrics; font.pixelSize: 11 }
    Timer { id: annotationTimer; interval: 16; onTriggered: root.updateAnnotations() }
    View3D {
        id: scene
        anchors.fill: parent
        camera: root.orthographicActive ? orthographicCamera : perspectiveCamera
        // Keep shared geometry in the scene when Repeater3D replaces its delegates.
        Node {
            ReferenceGeometry { id: tubeGeometry; partId: "P01" }
            ReferenceGeometry { id: socketGeometry; partId: "P02" }
            ReferenceGeometry { id: boltGeometry; partId: "P03" }
            ReferenceGeometry { id: nutGeometry; partId: "P04" }
            ReferenceGeometry { id: penetrationGeometry; partId: "P05" }
            ReferenceGeometry { id: supportGeometry; partId: "P06" }
            ReferenceGeometry { id: stationGeometry; partId: "station-ring" }
            ReferenceGeometry { id: enlargedStationGeometry; partId: "station-ring-enlarged" }
        }
        environment: SceneEnvironment {
            objectName: "referenceEnvironment"
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            tonemapMode: SceneEnvironment.TonemapModeAces
            lightProbe: Texture {
                objectName: "referenceProbeTexture"
                source: "assets/reference-neutral-environment.png"
            }
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
                readonly property real shiftX: (root.coveredRight-root.coveredLeft) * unitsPerPixel / 2
                readonly property real shiftY: -root.coveredBottom * unitsPerPixel / 2
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
            objectName: "referenceKeyLight"
            eulerRotation: Qt.vector3d(-Math.atan2(2.2,Math.hypot(1.4,1.6))*180/Math.PI,
                                       Math.atan2(1.4,1.6)*180/Math.PI,0)
            brightness: 2.1
        }
        DirectionalLight {
            objectName: "referenceFillLight"
            color: "#dce9f7"
            eulerRotation: Qt.vector3d(-Math.atan2(.6,Math.hypot(-1.8,-1.2))*180/Math.PI,
                                       Math.atan2(-1.8,-1.2)*180/Math.PI,0)
            brightness: 1.1
        }
        DirectionalLight {
            objectName: "referenceRimLight"
            eulerRotation: Qt.vector3d(-Math.atan2(-1.5,Math.hypot(.2,.8))*180/Math.PI,
                                       Math.atan2(.2,.8)*180/Math.PI,0)
            brightness: .7
        }
        DirectionalLight {
            objectName: "referenceAmbientLight"
            color: "#000000"
            brightness: 1
            ambientColor: Qt.rgba(.6262096812,.6262096812,.6262096812,1)
        }
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
            materials: SectionMaterial {
                tint: "#8aa0bd"; alphaValue: root.domeAlpha
                metalnessValue: .25; roughnessValue: .72
                objectName: "domeMaterial"
            }
        }
        Model {
            visible: root.showVessel && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: ReferenceGeometry { partId: "vessel" }
            materials: SectionMaterial {
                tint: "#9db4c9"; alphaValue: .085
                metalnessValue: .45; roughnessValue: .5
                objectName: "vesselMaterial"
            }
        }
        Model {
            objectName: "vesselWire"
            visible: root.showVessel && root.displayMode === "assembly" && root.tubes.length > 0
            geometry: VesselWireGeometry {
                objectName: "vesselWireGeometry"
                clipActive: root.clipEnabled; clipAxis: root.clipAxis; clipOffset: root.clipOffset
            }
            materials: DefaultMaterial {
                objectName: "vesselWireMaterial"
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#9fb8cf"
                opacity: .18
                depthDrawMode: Material.NeverDepthDraw
            }
        }
        Repeater3D {
            model: ["ucsPlate", "secondaryGrid"]
            delegate: Model {
                required property string modelData
                visible: root.showPlates && root.displayMode === "assembly" && root.tubes.length > 0
                geometry: ReferenceGeometry { partId: modelData }
                y: root.explode * (modelData === "ucsPlate" ? 800 : 400)
                materials: SectionMaterial {
                    tint: "#8fa3b8"; alphaValue: root.plateAlpha
                    metalnessValue: .5; roughnessValue: .6
                    objectName: "plateMaterial-" + modelData
                }
            }
        }
        Repeater3D {
            model: root.columns
            delegate: Model {
                required property var modelData
                objectName: "support-" + modelData.meshId
                geometry: ReferenceGeometry { partId: modelData.meshId }
                visible: root.showSupports && root.columnVisibility[modelData.type] !== false &&
                         root.displayMode === "assembly" && root.tubes.length > 0
                materials: SectionMaterial {
                    tint: modelData.type === "core-hollow" ? "#5f87a8" :
                          modelData.type === "core-solid" ? "#4f9d9d" :
                          modelData.type === "sec-hollow" ? "#8a7fb8" :
                          modelData.type === "sec-solid" ? "#9fb4c9" : "#8fa6bb"
                    metalnessValue: .58; roughnessValue: .44; alphaValue: .92
                    objectName: "columnMaterial-" + modelData.meshId
                }
            }
        }
        Repeater3D {
            model: root.tubes
            delegate: Node {
                id: tubeNode
                required property var modelData
                objectName: "tubeNode-" + modelData.tube
                property bool selected: modelData.tube === root.selectedTube
                readonly property color tubeColor: root.tubeColors[modelData.tube] || modelData.color || "#667c8c"
                visible: !root.singleMode &&
                    (modelData.category === "defect" ? root.showDefect :
                     modelData.category === "incomplete" ? root.showReview :
                     modelData.category === "ndd" ? root.showNdd : root.showMissing)
                position: Qt.vector3d(modelData.x,modelData.yBase,modelData.z)
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    geometry: tubeGeometry
                    pickable: true
                    visible: root.displayMode !== "socket" && root.displayMode !== "plate"
                    scale: Qt.vector3d(root.enlargeTubes ? 3 : 1,
                                       tubeNode.modelData.length/3000,
                                       root.enlargeTubes ? 3 : 1)
                    materials: SectionMaterial {
                        tint: tubeNode.selected ? "#f4bd3c" : tubeNode.tubeColor
                        alphaValue: tubeNode.selected ? 1 : root.modelOpacity
                        metalnessValue: .32; roughnessValue: .42
                        emissiveTint: "#16232f"; emissiveIntensity: .42
                        objectName: "tubeMaterial-" + tubeNode.modelData.tube
                    }
                }
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    source: "#Cylinder"
                    visible: root.displayMode === "plate"
                    pickable: true
                    scale: Qt.vector3d(.55,.05,.55)
                    materials: SectionMaterial {
                        tint: tubeNode.selected ? "#f4bd3c" : tubeNode.tubeColor
                        alphaValue: 1
                    }
                }
                Model {
                    property int tubeNumber: tubeNode.modelData.tube
                    visible: root.showSockets && root.displayMode !== "plate"
                    geometry: socketGeometry
                    pickable: true
                    y: root.explode * 150
                    materials: SectionMaterial {
                        tint:"#9dafc2"; alphaValue: 1
                        objectName: "socketMaterial-" + tubeNode.modelData.tube
                    }
                }
                Model {
                    objectName: "penetration-" + tubeNode.modelData.tube
                    property int tubeNumber: tubeNode.modelData.tube
                    property string partId: "P05"
                    visible: root.showPenetrations && root.displayMode === "assembly"
                    geometry: penetrationGeometry
                    pickable: true
                    materials: SectionMaterial {
                        tint:"#b9c7d4"; alphaValue: 1; metalnessValue: .5
                        objectName: "penetrationMaterial-" + tubeNode.modelData.tube
                    }
                }
            }
        }
        Node {
            id: singleAssembly
            objectName: "singleAssembly"
            visible: root.singleMode
            y: -root.detailTarget
            Repeater3D {
                model: ["P01", "P02", "P03", "P04", "P05", "P06"]
                delegate: Model {
                    required property string modelData
                    objectName: "detailPart-" + modelData
                    property string partId: modelData
                    property int tubeNumber: root.selectedTube
                    readonly property bool contextPart: modelData === "P05" || modelData === "P06"
                    visible: root.partVisibility[modelData] !== false
                    pickable: true
                    geometry: modelData === "P01" ? tubeGeometry : modelData === "P02" ? socketGeometry :
                              modelData === "P03" ? boltGeometry : modelData === "P04" ? nutGeometry :
                              modelData === "P05" ? penetrationGeometry : supportGeometry
                    position: modelData === "P01" ? Qt.vector3d(0,root.explode*root.detailLength*.055,0) :
                              modelData === "P02" ? Qt.vector3d(0,0,root.explode*78) :
                              modelData === "P03" ? Qt.vector3d(0,root.explode*130,0) :
                              modelData === "P04" ? Qt.vector3d(96+root.explode*60,root.explode*26,0) :
                              modelData === "P05" ? Qt.vector3d(0,-root.explode*120,0) :
                                                   Qt.vector3d(0,-root.explode*220,0)
                    scale: modelData === "P01" ?
                        Qt.vector3d(root.enlargeTubes ? 4 : 1,
                                    root.detailLength/3000,
                                    root.enlargeTubes ? 4 : 1) : Qt.vector3d(1,1,1)
                    materials: SectionMaterial {
                        tint: modelData === "P01" ? "#667c8c" : root.partColors[modelData]
                        alphaValue: contextPart && root.ghostContext ? .22 : 1
                        metalnessValue: root.partMetalness[modelData] ?? .8
                        objectName: "detailMaterial-" + modelData
                    }
                }
            }
            Repeater3D {
                model: root.stations
                delegate: Model {
                    required property var modelData
                    objectName: "stationRing-" + modelData.id
                    visible: root.showStations
                    y: modelData.y
                    geometry: root.enlargeTubes ? enlargedStationGeometry : stationGeometry
                    materials: DefaultMaterial {
                        lighting: DefaultMaterial.NoLighting
                        diffuseColor: modelData.status === "推定" ? "#d98b2b" : "#0b6bcb"
                        opacity: .95
                        cullMode: Material.NoCulling
                    }
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
                          Qt.vector3d(0,modelData.y-modelData.yBase-root.detailTarget,0)
                scale: Qt.vector3d(.45,.45,.45)
                materials: SectionMaterial { tint:"#c8424a"; alphaValue: 1 }
            }
        }
        Node {
            objectName: "detailAxisHelper"
            visible: root.singleMode && root.showDetailAxis
            y: -root.detailTarget
            Model {
                geometry: ReferenceGeometry { partId: "detail-grid" }
                materials: DefaultMaterial {
                    lighting: DefaultMaterial.NoLighting
                    diffuseColor: "#ffffff"
                    vertexColorsEnabled: true
                }
            }
            Model {
                geometry: ReferenceGeometry { partId: "detail-axes" }
                materials: DefaultMaterial {
                    lighting: DefaultMaterial.NoLighting
                    diffuseColor: "#ffffff"
                    vertexColorsEnabled: true
                }
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
                if (root.singleMode) {
                    const part = root.pickPart(mouse.x,mouse.y)
                    if (part) root.partSelected(part)
                    return
                }
                const tube=root.pickTube(mouse.x,mouse.y)
                if (tube) { root.selectedTube=tube; root.tubeSelected(tube) }
            }
            onDoubleClicked: root.resetView()
        }
    }
    Rectangle {
        id: axisGizmo
        objectName: "axisGizmo"
        Accessible.role: Accessible.StaticText
        Accessible.name: "XYZ 坐标轴"
        Accessible.description: "X 红 / Y 绿 / Z 蓝，随视角旋转"
        visible: root.showAxes && root.displayMode === "assembly" && width <= root.width-root.coveredLeft-root.coveredRight-24
        width: root.width <= 600 ? 58 : root.width <= 900 ? 68 : 76
        height: width
        x: root.coveredLeft+12
        readonly property real preferredY: root.height-height-(root.width <= 600 ? 132 : 12)
        y: x < root.footerBounds[2]+8 && x+width+8 > root.footerBounds[0] &&
            preferredY+height+8 > root.footerBounds[1] && preferredY < root.footerBounds[3] ?
                root.footerBounds[1]-height-8 : preferredY
        radius: 7
        color: root.darkTheme ? "#f71c2527" : "#d6ffffff"
        border.color: root.darkTheme ? "#3b4c4d" : "#cfdcea"
        Canvas {
            id: axisCanvas
            objectName: "axisGizmoCanvas"
            anchors.fill: parent
            onVisibleChanged: if (visible) requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            Connections {
                target: root
                function onAxisProjectionChanged() { if (axisGizmo.visible) axisCanvas.requestPaint() }
            }
            onPaint: {
                const context = getContext("2d")
                context.reset()
                const round = value => Math.round(value*10)/10
                const axes = root.axisProjection.map(axis => ({
                    text:axis.text, color:axis.color, x:round(axis.x), y:round(axis.y),
                    stubX:round(69-(axis.x-69)*.42), stubY:round(69-(axis.y-69)*.42)
                }))
                let minX=66.4, minY=66.4, maxX=71.6, maxY=71.6
                for (const axis of axes) {
                    minX=Math.min(minX,axis.x-8,axis.stubX); maxX=Math.max(maxX,axis.x+8,axis.stubX)
                    minY=Math.min(minY,axis.y-8,axis.stubY); maxY=Math.max(maxY,axis.y+8,axis.stubY)
                }
                const size=Math.max(maxX-minX,maxY-minY)+32
                context.scale(width/size,height/size)
                context.translate(size/2-(minX+maxX)/2,size/2-(minY+maxY)/2)
                context.fillStyle="#7b8ea6"
                context.beginPath(); context.arc(69,69,2.6,0,Math.PI*2); context.fill()
                context.lineCap="round"
                for (const axis of axes) {
                    context.strokeStyle=axis.color
                    context.lineWidth=1.3; context.globalAlpha=.38; context.setLineDash([2,3])
                    context.beginPath(); context.moveTo(69,69); context.lineTo(axis.stubX,axis.stubY); context.stroke()
                    context.lineWidth=2.6; context.globalAlpha=1; context.setLineDash([])
                    context.beginPath(); context.moveTo(69,69); context.lineTo(axis.x,axis.y); context.stroke()
                    context.fillStyle=axis.color; context.strokeStyle="#ffffff"; context.lineWidth=1.6
                    context.beginPath(); context.arc(axis.x,axis.y,8,0,Math.PI*2); context.fill(); context.stroke()
                    context.font='bold 10.5px "Segoe UI"'
                    context.textAlign="center"; context.textBaseline="middle"; context.fillStyle="#ffffff"
                    context.fillText(axis.text,axis.x,axis.y+.5)
                }
            }
        }
    }
    Canvas {
        id: leaders
        anchors.fill: parent
        onPaint: {
            const context = getContext("2d")
            context.reset()
            context.lineWidth = .8
            for (const label of root.projectedAnnotations) {
                context.strokeStyle = label.estimated ? "#d98b2b" : label.station ? "#0b6bcb" : "#9db8d4"
                context.beginPath()
                context.moveTo(label.anchorX,label.anchorY)
                context.lineTo(label.x > label.anchorX ? label.x : label.x+label.w,label.y+label.h/2)
                context.stroke()
            }
        }
        Connections { target: root; function onProjectedAnnotationsChanged() { leaders.requestPaint() } }
    }
    Repeater {
        model: root.projectedAnnotations
        delegate: Rectangle {
            required property var modelData
            objectName: "annotation-" + modelData.id
            Accessible.role: modelData.station ? Accessible.Button : Accessible.StaticText
            Accessible.name: modelData.text
            Accessible.onPressAction: { if (modelData.station) root.stationSelected(modelData.id) }
            x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
            radius: 4
            color: root.darkTheme ? (modelData.estimated ? "#342b1c" : "#f5232f31") :
                modelData.station && !modelData.estimated ? "#0b6bcb" : "#faffffff"
            border.color: root.darkTheme ? (modelData.estimated ? "#8a6731" : "#526766") :
                modelData.estimated ? "#f0cfa8" : modelData.station ? "#0b6bcb" : "#cfdcea"
            Text {
                anchors.centerIn: parent
                text: modelData.text
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: root.darkTheme ? (modelData.estimated ? "#ffd087" : "#d8e6e3") :
                    modelData.estimated ? "#b16c18" : modelData.station ? "#ffffff" : "#33506e"
            }
            MouseArea {
                anchors.fill: parent
                enabled: modelData.station
                onClicked: root.stationSelected(modelData.id)
            }
        }
    }
    Rectangle {
        id: stationScale
        objectName: "stationScale"
        Accessible.role: Accessible.StaticText
        Accessible.name: "P1–P6 轴向标尺"
        visible: root.scaleVisible
        x: root.scaleX; y: 12; width: 196; height: root.scaleHeight+76
        color: root.darkTheme ? "#f71c2527" : "#faffffff"
        border.color: root.darkTheme ? "#3b4c4d" : "#cfdcea"; radius: 6
        Text {
            x: 10; y: 9; text: "P1–P6 轴向标尺"
            Accessible.ignored: true
            font.pixelSize: 11; font.bold: true; color: root.darkTheme ? "#9eafac" : "#61758c"
        }
        Rectangle { x: 30; y: 36; width: 2; height: root.scaleHeight; color: "#6b9fd2" }
        Repeater {
            model: root.stations
            delegate: Item {
                required property var modelData
                objectName: "scaleTick-" + modelData.id
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label+" · "+modelData.distance.toFixed(1)+" mm · "+modelData.status
                Accessible.description: modelData.basis
                Accessible.onPressAction: root.stationSelected(modelData.id)
                x: 8; y: 36+Math.max(0,Math.min(1,modelData.distance/root.detailLength))*root.scaleHeight
                width: 180; height: 1
                Rectangle { anchors.fill: parent; color: root.darkTheme ? "#334244" : "#cfdcea" }
                Text {
                    x: 2; y: -7; text: modelData.label
                    font.pixelSize: 11; font.bold: true
                    color: root.darkTheme ? (modelData.status === "推定" ? "#ffd087" : "#e5eeec") :
                        modelData.status === "推定" ? "#b16c18" : "#0b6bcb"
                }
                Text {
                    x: 36; y: -7
                    text: modelData.distance.toFixed(1)+" mm ("+(modelData.distance/root.detailLength*100).toFixed(0)+"%)"
                    font.pixelSize: 10; color: root.darkTheme ? "#e5eeec" : "#465d65"
                }
                MouseArea { width: parent.width; height: 18; y: -8; onClicked: root.stationSelected(modelData.id) }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.scaleHeight+52
            text: "P1 在管顶 · P6 在管底"
            font.pixelSize: 10
            color: root.darkTheme ? "#9eafac" : "#61758c"
        }
    }
    Text {
        anchors.centerIn: parent
        visible: root.tubes.length === 0 && !root.singleMode
        text: "请选择有检测数据的范围"
        color:"#465d65"; font.pixelSize:18
    }
}

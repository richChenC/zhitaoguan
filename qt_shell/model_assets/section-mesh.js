// The source-reference slice/loop rules and Earcut run in Qt's JavaScript engine.
function sectionMesh(part, axis, offset, scale) {
    const axes = axis === "x" ? [0, 1, 2] : axis === "y" ? [1, 2, 0] : [2, 0, 1];
    const points = new Float64Array(part.positions.length);
    for (let i = 0; i < points.length; i += 3) {
        for (let k = 0; k < 3; k++) points[i+k] = part.positions[i+axes[k]] * scale[axes[k]];
    }
    const loops = sliceLoops(points, part.indices, offset);
    const items = [];
    for (const loop of loops) {
        const clean = cleanLoop(loop), area = area2(clean);
        if (clean.length >= 3 && Math.abs(area) >= .01) {
            items.push({loop:clean, sign:Math.sign(area), area:Math.abs(area)});
        }
    }
    items.sort((a, b) => b.area-a.area);
    const positions = [], indices = [], normal = [0, 0, 0];
    normal[axes[0]] = 1;
    let holeCount = 0;
    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.used) continue;
        item.used = true;
        const rings = [item.loop];
        for (let j = i+1; j < items.length; j++) {
            const hole = items[j];
            if (!hole.used && hole.area < item.area && pointInLoop(hole.loop[0], item.loop)) {
                hole.used = true;
                rings.push(hole.loop);
            }
        }
        const flat = [], holes = [], vertexOffset = positions.length/3;
        for (let k = 0; k < rings.length; k++) {
            // ShapeGeometry makes the outer (u=z,v=y) ring clockwise, holes counterclockwise.
            const ring = rings[k].slice();
            if ((area2(ring) > 0) !== (k === 0)) ring.reverse();
            if (k) holes.push(flat.length/2);
            for (const point of ring) flat.push(point[1], point[0]);
        }
        const faces = earcut(flat, holes, 2);
        if (!faces.length) continue;
        for (let k = 0; k < flat.length; k += 2) {
            const vertex = [0, 0, 0];
            vertex[axes[0]] = offset/scale[axes[0]];
            vertex[axes[1]] = flat[k+1]/scale[axes[1]];
            vertex[axes[2]] = flat[k]/scale[axes[2]];
            positions.push(...vertex);
        }
        // (u=z,v=y) maps to a -axis normal; reverse faces for the retained-side outward normal.
        for (let k = 0; k < faces.length; k += 3) {
            indices.push(vertexOffset+faces[k], vertexOffset+faces[k+2], vertexOffset+faces[k+1]);
        }
        holeCount += holes.length;
    }
    return {positions, indices, normal, loops:items.length, holes:holeCount};
}

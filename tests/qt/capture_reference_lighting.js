// Run with playwright-cli run-code against the read-only reference model page.
async (page) => {
  const reference = await page.evaluate(async () => {
    if (!window.__scene || !window.__renderer) throw new Error('Reference model is not ready');
    const source = await (await fetch('./app.js')).text();
    const start = source.indexOf('function makeNeutralEnv(pmrem)');
    const end = source.indexOf('function makeMat(', start);
    if (start < 0 || end < 0) throw new Error('Neutral environment function boundaries changed');
    const environmentSource = source.slice(start, end);
    const texture = new Function('THREE', 'document', environmentSource +
      '\nreturn makeNeutralEnv({fromEquirectangular:texture=>({texture})});')(window.__THREE, document);
    const image = texture.image;
    const geometryMaterials = [];
    let vesselWire = null;
    window.__scene.traverse(object => {
      if (!object.material || Array.isArray(object.material)) return;
      const material = object.material;
      const id = object.userData?.id || object.name || '';
      geometryMaterials.push({
        id, name:object.name, kind:object.userData?.kind, columnType:object.userData?.col?.type, type:object.type,
        color:material.color?.getHexString(), metalness:material.metalness, roughness:material.roughness,
        emissive:material.emissive?.getHexString(), emissiveIntensity:material.emissiveIntensity,
        opacity:material.opacity, depthWrite:material.depthWrite, visible:object.visible,
      });
      if (object.isLineSegments && material.color?.getHexString() === '9fb8cf') {
        vesselWire = {positions:Array.from(object.geometry.attributes.position.array),
          source:'TRAE reference buildVesselScene / WireframeGeometry', color:'#9fb8cf', opacity:.18};
      }
    });
    return {
      environmentSource, environmentImage:image.toDataURL('image/png'),
      environmentSize:[image.width,image.height], revision:window.__THREE.REVISION,
      lights:window.__scene.children.filter(object=>object.isLight).map(light=>({
        type:light.type, color:light.color.getHexString(), intensity:light.intensity,
        position:light.position.toArray(),
      })),
      materials:geometryMaterials, vesselWire, exposure:window.__renderer.toneMappingExposure,
    };
  });
  return reference;
}

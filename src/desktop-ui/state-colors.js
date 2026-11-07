/* Shared maintenance-state palette and composite renderer.
 * This is a classic script because the state workspace loads before the
 * analytics ES module.
 */
(() => {
  const colors = Object.freeze({
    normal:   Object.freeze({fill:'#d8f0e2', edge:'#218a67', ink:'#14553d'}),
    plugged:  Object.freeze({fill:'#f8d7dc', edge:'#c23b52', ink:'#7c2538'}),
    shifted:  Object.freeze({fill:'#ffe3b0', edge:'#c47700', ink:'#713f00'}),
    replaced: Object.freeze({fill:'#d7e6fb', edge:'#2e6fb8', ink:'#1b4d91'}),
    review:   Object.freeze({fill:'#fff7e8', edge:'#b8862d', ink:'#7b5b1a'}),
    missing:  Object.freeze({fill:'#edf1f3', edge:'#9baab3', ink:'#44545e'})
  });
  const labels = Object.freeze({normal:'正常', plugged:'堵管', shifted:'移位', replaced:'换管'});
  const order = Object.freeze(['plugged', 'shifted', 'replaced']);
  const composites = Object.freeze({
    'plugged+shifted': Object.freeze({edge:'#a34552', ink:'#5b2632'}),
    'plugged+replaced': Object.freeze({edge:'#875078', ink:'#4a2847'}),
    'shifted+replaced': Object.freeze({edge:'#92702c', ink:'#4c3b12'}),
    'plugged+shifted+replaced': Object.freeze({edge:'#6f5878', ink:'#3d3048'})
  });
  const uniqueEvents = events => order.filter(event => Array.isArray(events) && events.includes(event));
  const background = events => {
    const active = uniqueEvents(events);
    if (!active.length && Array.isArray(events) && events.includes('normal')) return colors.normal.fill;
    if (!active.length) return colors.missing.fill;
    if (active.length === 1) return colors[active[0]].fill;
    const step = 100 / active.length;
    return `linear-gradient(90deg,${active.map((event, index) => {
      const start = (index * step).toFixed(3);
      const end = ((index + 1) * step).toFixed(3);
      return `${colors[event].fill} ${start}% ${end}%`;
    }).join(',')})`;
  };
  const edge = events => {
    const active = uniqueEvents(events);
    if (!active.length && Array.isArray(events) && events.includes('normal')) return colors.normal.edge;
    if (active.length === 1) return colors[active[0]].edge;
    if (active.length > 1) return composites[active.join('+')]?.edge || colors.review.edge;
    return colors.missing.edge;
  };
  const ink = events => {
    const active = uniqueEvents(events);
    if (!active.length && Array.isArray(events) && events.includes('normal')) return colors.normal.ink;
    if (active.length === 1) return colors[active[0]].ink;
    if (active.length > 1) return composites[active.join('+')]?.ink || colors.review.ink;
    return colors.missing.ink;
  };
  const label = events => {
    const active = uniqueEvents(events);
    if (!active.length && Array.isArray(events) && events.includes('normal')) return labels.normal;
    return active.length ? active.map(event => labels[event]).join(' · ') : '未维护';
  };
  window.thimbleStateColors = Object.freeze({colors, labels, order, composites, uniqueEvents, background, edge, ink, label});
})();

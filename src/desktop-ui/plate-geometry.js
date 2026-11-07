(() => {
  'use strict';
  const columns = Object.freeze('RPNMLKJHGFEDCBA'.split(''));
  const rowWidths = Object.freeze([3,7,9,11,13,13,15,15,15,13,13,11,9,7,3]);
  function cell(position) {
    const match = /^([A-Z])0?(\d{1,2})$/.exec(String(position || '').trim().toUpperCase());
    if (!match) return null;
    const col = columns.indexOf(match[1]), row = Number(match[2])-1;
    if (col < 0 || row < 0 || row >= rowWidths.length) return null;
    const start = (columns.length-rowWidths[row])/2;
    return col >= start && col < start+rowWidths[row] ? {col, row} : null;
  }
  window.plateGeometry = Object.freeze({columns, rowWidths, cell});
})();

// 合规中国地图基础模块：基地坐标 + 投影 + 主题（离线、零依赖）
// 省界 GeoJSON 由 interactive-map.js 从 data/china-provinces.json 拉取（含台湾/港澳/南海诸岛九段线）。
//
// ===== 基地坐标来源 =====
// 红沿河：生态环境部公示《辽宁红沿河核电厂机组运行方式优化项目环境影响报告表》
//         厂址坐标 东经 121°28′19″ / 北纬 39°48′09″ → 121.472, 39.803
//         （旧代码误填 123.50°E，偏东约 175km，落在鸭绿江口一带，已修正）
// 其余运行基地：公开核电厂址坐标（阳江 21.710/112.261、大亚湾 22.598/114.544、
//         岭澳 22.605/114.552、台山 21.909/112.979、防城港 21.671/108.558、宁德 27.045/120.280）
// 在建/规划基地（苍南三澳、陆丰、惠州太平岭）坐标为厂址所在乡镇近似值。
//
// ===== 站点代号 =====
// code 为全局唯一显示代号。陆丰取 LF、惠州取 HZ，避免与岭澳 L、红沿河 H 撞码。
// apiCode 对应台账 site_code；为 null 表示该基地尚未接入检测数据。
// group = 所属核电基地。岭澳与大亚湾同址，同属「大亚湾核电基地」，
// 因此 10 个站点对应 9 个核电基地（与群厂口径一致）。
export const SITE_GEO = {
  '红沿河': { lng: 121.472, lat: 39.803, code: 'H', apiCode: 'H', group: '红沿河基地' },
  '宁德':   { lng: 120.280, lat: 27.045, code: 'N', apiCode: 'N', group: '宁德基地' },
  '苍南':   { lng: 120.480, lat: 27.200, code: 'CN', apiCode: 'C', group: '苍南基地' },
  '陆丰':   { lng: 115.620, lat: 22.920, code: 'LF', apiCode: 'LF', group: '陆丰基地' },
  '惠州':   { lng: 114.980, lat: 22.700, code: 'HZ', apiCode: 'P', group: '惠州基地' },
  // 大亚湾与岭澳属于同一核电基地、同一厂址。使用同一地理点，
  // 通过标签引线和不同代号区分两套机组数据，避免地图产生两个
  // 看起来相距很远的“基地”。
  '大亚湾': { lng: 114.548, lat: 22.602, code: 'D', apiCode: 'D', group: '大亚湾核电基地' },
  '岭澳':   { lng: 114.548, lat: 22.602, code: 'L', apiCode: 'L', group: '大亚湾核电基地' },
  '台山':   { lng: 112.979, lat: 21.909, code: 'T', apiCode: 'T', group: '台山基地' },
  '阳江':   { lng: 112.261, lat: 21.710, code: 'Y', apiCode: 'Y', group: '阳江基地' },
  '防城港': { lng: 108.558, lat: 21.671, code: 'F', apiCode: 'F', group: '防城港基地' }
};

// 去重后的基地数（群厂口径）
export const BASE_COUNT = new Set(Object.values(SITE_GEO).map(g => g.group)).size;

// 标签防重叠偏移（viewBox 单位，text-anchor=middle）
// 珠三角基地非常密集：阳江/台山/陆丰/惠州/大亚湾/岭澳 6 个点挤在一起，
// 把标签分别引向上下左右并用细引线；字号同时缩小到 9px。
export const LABEL_OFFSETS = {
  '红沿河': [34, 4],
  '宁德':   [40, 2],
  '苍南':   [16, -24],
  '陆丰':   [65, -52],
  '惠州':   [88, -10],
  '大亚湾': [0, -66],
  '岭澳':   [50, 26],
  '台山':   [-65, -20],
  '阳江':   [-20, 30],
  '防城港': [-30, -10]
};

// 南海诸岛插图框（右下角）
export const W = 960, H = 760;
export const IN_X = 720, IN_Y = 505, IN_W = 215, IN_H = 215;

const X0 = 73, X1 = 135.5, Y0 = 17.5, Y1 = 54;
const IX0 = 104, IX1 = 123, IY0 = 3, IY1 = 21;
// 等距矩形投影 + 纬度余弦修正（cos35°≈0.82）：低纬度东西向拉伸被压缩，轮廓比例接近标准中国地图
const COS_LAT = Math.cos(35 * Math.PI / 180);

export function proj(lng, lat) {
  const xr = (lng - X0) / (X1 - X0), yr = (Y1 - lat) / (Y1 - Y0);
  return [((xr * COS_LAT + (1 - COS_LAT) / 2) * W).toFixed(1), (yr * H).toFixed(1)];
}
export function projIn(lng, lat) {
  const xr = (lng - IX0) / (IX1 - IX0), yr = (IY1 - lat) / (IY1 - IY0);
  return [(IN_X + (xr * COS_LAT + (1 - COS_LAT) / 2) * IN_W).toFixed(1), (IN_Y + yr * IN_H).toFixed(1)];
}

// 主题配色：light = 统计分析页（CGN 浅蓝）；dark 保留备用
export const MAP_THEMES = {
  light: {
    bg: '#f4f8fb', land: '#dce9ee', landBd: '#91acba', landHover: '#a6ccd4',
    // 已接入数据的基地
    mark: '#0066cc', markFill: '#ffffff', markLabel: '#003c8f', markCount: '#4a6b91',
    // 待接入基地：与已接入同一尺寸，仅用灰蓝区分（保证「圆圈一样大」）
    dim: '#7c8fa3', dimFill: '#ffffff', dimLabel: '#5c6b7a',
    insetBg: '#f2f7fc', insetBd: '#a8c8e8', insetTitle: '#5c6b7a',
    dash: '#0066cc', dotIn: '#0066cc',
    leader: '#9db2c8',
    tipBg: 'rgba(255,255,255,0.97)', tipFg: '#123a5e', tipBd: '#a8c8e8'
  },
  dark: {
    bg: '#08182f', land: '#123a5e', landBd: '#2f6da8', landHover: '#2f6da8',
    mark: '#ff5a5a', markFill: '#0d2340', markLabel: '#eaf4ff', markCount: '#ffd0d0',
    dim: '#3aa0ff', dimFill: '#0d2340', dimLabel: '#7fa8d6',
    insetBg: '#0c2138', insetBd: '#2f6da8', insetTitle: '#6f9fd0',
    dash: '#3aa0ff', dotIn: '#3aa0ff',
    leader: '#3aa0ff',
    tipBg: 'rgba(8,24,47,0.96)', tipFg: '#eaf4ff', tipBd: '#2f6da8'
  }
};

// 所有基点统一尺寸（viewBox 单位）：外圈半径 / 内点半径
// 用户要求「圆圈再小很多，挡住都看不见了」——紧凑模式
export const MARKER = { r: 3.5, dot: 1.5, dimDot: 1, pulse: 7 };

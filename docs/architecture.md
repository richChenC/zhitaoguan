# 工程结构

## 运行边界

这是一个 Windows 本地桌面应用。Electron 负责窗口和本地目录选择，Python HTTP 服务负责 SQLite 数据访问、文件解析、历史演变和 Excel 导出，浏览器渲染层负责工作台、二维管板和 Three.js 三维视图。

```text
desktop/main.cjs              Electron 窗口、Python 服务生命周期
desktop/preload.cjs           桌面文件选择 IPC 白名单
server.py                     本地 API、解析、数据库和报表
static/app.js                 工作台状态、筛选、分页和业务事件
static/visualizations/thimble Three.js 独立三维模型页面
static/modules/three-d        三维 iframe 与工作台桥接
static/*.css                  页面主题和响应式布局
tests/                        Python、浏览器和桌面回归测试
docs/                         领域规则、建模依据和开发文档
data/                         本地 SQLite 数据库，不进入版本库
output/                       导出文件，不进入版本库
```

## 数据流

导入文件夹/Excel -> `server.py` 解析与去重 -> `data/thimble.db` -> `/api/findings`、`/api/overview` -> 工作台筛选 -> 二维管板和三维 iframe。

历史演变状态保存在 `tube_states`，原始检测记录保持不变；位移量只用于历史匹配，不改写原始位置。

## 目录约束

- 运行数据、导出结果、缓存和虚拟环境只存在本地，不提交 Git。
- 新增 API 先写清楚输入、输出和基地/机组隔离规则，再补回归测试。
- 三维模型页面只能通过 `postMessage` 接收工作台筛选和定位事件。

# 工程结构

## 运行边界

这是一个 Windows 本地桌面应用。`08_Qt移植版/` 是唯一主版本，PySide6 和 Qt WebEngine 负责窗口、托盘、文件选择及页面显示；Python HTTP 服务负责 SQLite 数据访问、文件解析、历史演变和 Excel 导出，浏览器渲染层负责工作台、二维管板和 Three.js 三维视图。

日常入口是项目根目录 `启动Qt主版本.cmd`，依次调用本目录的 `启动正式版.cmd`、`启动Qt版.cmd`，最终运行 `pythonw.exe -m qt_shell.main`。开发模式优先运行源码后端，冻结发布模式优先运行打包后端。`src/desktop/*.cjs` 保留为 Electron 兼容和构建、测试内容，不是 Qt 日常启动链。

```text
qt_shell/main.py              Qt 主入口、单实例与启动流程
qt_shell/windows.py           Qt WebEngine 窗口
qt_shell/desktop_api.py        本地桌面操作桥接
qt_shell/backend_service.py    本地 Python 服务生命周期
src/backend/server.py         本地 API、解析、数据库和报表
src/desktop-ui/app.js                 工作台状态、筛选、分页和业务事件
src/desktop-ui/lazy-modules.js        首次进入分析、报告视图时加载模块和样式
src/desktop-ui/visualizations/reference-thimble 原工程查看器、离线模型与独立缺陷业务层
src/desktop-ui/visualizations/thimble 旧地址兼容跳转，不再包含旧模型
src/desktop-ui/modules/three-d        三维 iframe 与工作台桥接
src/desktop-ui/*.css                  桌面窗口主题和响应式布局
tests/                        Python、浏览器和桌面回归测试
docs/                         领域规则、建模依据和开发文档
user-data/data/               开发模式 Qt 业务数据库
user-data/output/             Qt 导出文件
user-data/qtwebengine/         Qt WebEngine 本地缓存
```

## 数据流

导入文件夹/Excel -> `src/backend/server.py` 解析与去重 -> `user-data/data/thimble.db` -> `/api/findings`、`/api/overview` -> 工作台筛选 -> 二维管板和三维 iframe。三维 iframe 在首次进入三维视图时加载。

上述路径是源码开发模式的 Qt 路径，与旧 Electron 运行数据独立。启动时不自动合并、迁移或覆盖旧数据库。冻结发布模式通过 `data-location.json` 或本机 AppData 选择用户数据根目录，具体规则见 `qt_shell/constants.py`。

隔离测试必须显式设置 `THIMBLE_QT_TEST_DATA_ROOT` 和 `THIMBLE_ALLOW_MULTI_INSTANCE=1`，数据库、导出和缓存都放在项目根目录 `05_测试与验证/03_自动化临时产物/` 下；仅设置数据库环境变量不能重定向正常启动的数据位置。

历史演变状态保存在 `tube_states`，原始检测记录保持不变；位移量只用于历史匹配，不改写原始位置。

## 本地数据源边界

`src/backend/data_source.py` 集中维护 SQLite 连接行为与配置校验，
`server.connect()` 仍使用同一数据库及既有查询视图。当前仅支持 SQLite，
没有启用远程数据库或服务器同步，也不声称现有 SQLite SQL 已适配其他引擎。

`GET/POST /api/settings/data-source` 区分实际活动存储 `active` 和未来接入配置
`profile`。配置写入实际数据库同目录的 `data-source.json`，采用原子替换；
损坏配置保留原件并拒绝覆盖。仅保存 HTTP/HTTPS 服务地址、超时、资料来源目录，
不保存密码，不连接、不上传、不切换数据库。资料来源文件夹不等于业务数据库位置。

`POST /api/settings/data-source/validate` 的本地检查只读打开数据库并核查完整性及
必要表；不存在时不创建空库。服务器目标只校验格式，明确返回
`connected:false` 和 `network_requested:false`。未来接入须另行实现接口鉴权、
字段/分页协议、错误重试及迁移验收，不能只切换界面选项。

## 目录约束

- 运行数据、导出结果、缓存和虚拟环境只存在本地，不提交 Git。
- 新增 API 先写清楚输入、输出和基地/机组隔离规则，再补回归测试。
- 三维模型页面只能通过 `postMessage` 接收工作台筛选和定位事件。

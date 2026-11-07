# 开发与发布

## 本地启动

桌面模式：双击 `启动指套管软件.cmd`。

服务模式：

```powershell
python src/backend/server.py
```

默认地址为 `http://127.0.0.1:18767`，与旧版源码窗口隔离。桌面壳自动启动同一个 Python 服务。

## 验证

```powershell
python -m unittest discover -s tests
node --check src/desktop-ui/app.js
node --check src/desktop-ui/workspace-actions.js
npm run check
npm run test:three
```

## 提交前检查

1. 确认 `data/`、`output/`、`.venv/` 和 `node_modules/` 没有进入 Git。
2. 运行 Python 测试和 JavaScript 语法检查。
3. 手动确认导入、基地/机组/大修筛选、二维管板点击、三维定位和报告导出。
4. 使用独立的版本查询参数更新静态资源缓存版本。

## Git 与需求验证约定

- 每批按“需求编号 → 改动 → 验证命令 → 实际结果 → 证据 → 未完成项”记录，不把未验证项写成完成。
- 本目录拥有独立的本地 Git 仓库，与上层历史工作区隔离；不自动推送。提交源码、测试、文档、模板及离线运行必需的 `.vendor/`，不提交数据库、原始资料、生成结果或运行缓存。
- 不提交原始检测资料、业务数据库、生成报告、完整聊天原文、运行配置缓存、虚拟环境、安装产物与临时证据目录。整理后的资料副本位于 `项目资料/`，按 `.gitignore` 排除。
- 真实数据验证使用隔离数据库或只读副本，原始资料、业务库前后校验；报告逐字段对快照，参考文档的格式/物理约束单独验收。不能把构造样本通过当成真实业务样本验收。
- 提交前至少执行 Python 回归、脚本检查、相关 Electron 桌面专项；变更导入/统计/报告时运行 `scripts/verify_real_data.py`。通过后在实施记录中写明证据目录及限制。
- 复核验证证据是否仍存在、原始文件及导出物 SHA-256 是否匹配。Git 提交号在提交后查询，不能预填；本地原始证据留在 `tmp/`，不为提交而复制业务资料。

常用验证命令（在软件目录中运行）：

```powershell
npm run test:import
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
npm run check
npm run test:desktop
npm run test:interaction
npm run test:window
npm run test:settings
node tests/cross_group_desktop_verify.mjs
.\.venv\Scripts\python.exe -X utf8 scripts/verify_real_data.py
node tests/real_data_desktop_verify.mjs tmp/<本次真实数据证据目录>
```

`npm run test:import` 自动通过隔离测试登录，串行验证实时进度、成功/重复/失败/混合批次与失败重试、Excel 字段映射，以及 RPT 转换和缺失值处理。每项测试使用独立临时数据库；结果日志集中在 `tmp/release-check/<时间戳>/`。无需手工输入测试账户，不影响桌面软件的正式登录。

`test:interaction` 启动实际 Electron，复制真实数据验证库后执行删除/撤销、筛选恢复、图表联动、报告导出、状态维护及目录选择向导。默认使用 `tmp/real-data-20261018-223443/thimble.db`；可先运行 `verify_real_data.py`，再将 `THIMBLE_TEST_SOURCE_DB` 指向新生成的验证库。专项依赖 H209 等真实范围及其记录数量，不适用于任意业务库。截图、导出和结果写入独立的 `tmp/interaction-*`，校验源库与业务库哈希不变。依赖本机已安装 Electron、虚拟环境及 Codex Playwright 运行时；多个桌面测试须顺序执行，避免窗口焦点互相干扰。

2026.10.18.6 起该专项包含 13 组检查，新增状态列表单请求/乱序/失败恢复、特殊字符持久化、导出忙碌锁/迟到响应，以及最小桌面窗口 1100×720 的布局和基础键盘操作。测试应等待保存后的实际重新加载和对应预览请求，不以仍显示的旧节点作为完成信号。结果与边界见 `专业功能测试与界面优化_2026-10-18.md`。

2026-10-19 的界面与交互批次扩展为 17 组，增加删除预览失败拦截、删除和撤销失败重试、危险操作取消、弹窗内通知可点击、回收站分页与来源文本安全、真实审计入口、滚动位置恢复、键盘选行、三维手动同步以及 390 至 1600 像素宽度的布局检查。三维同时验证画布非空和窄窗口详情不覆盖场景。完整范围及限制见 `界面与交互优化_2026-10-19.md`。

`test:window` 使用实际 Electron 原生窗口测 9 组尺寸/renderer 缩放组合、6 个主界面，包含导入/Report 向导边界、三维控件遮挡、画布非空、统计卡片可读宽度以及最大化/最小化恢复。默认真实数据源和 `THIMBLE_TEST_SOURCE_DB` 与交互专项一致，SQLite 只读备份后操作隔离副本，源库及业务库哈希前后校验。证据及原生截图写入 `tmp/window-size-*`。125%/150% renderer zoom 不等于真实 Windows DPI，跨屏高 DPI 必须另测。所有 Electron 专项顺序执行，不能同时运行以免焦点干扰；结果与限制见 `窗口尺寸影响检查_2026-10-19.md`。

`test:settings` 从当前业务库只读备份到独立目录，运行真实 Electron 验证设置分类、
键盘切换、配置保存/重启恢复、只读数据库校验、备份恢复确认门槛以及
800×600/1100×720/1480×960 在 100%/125%/150% renderer zoom 下的边界。
检查业务库原件 SHA-256 不变且没有外部 HTTP 请求；证据在
`tmp/settings-workspace-*/evidence.json`。服务器预留配置的测试不代表远程服务已实现。

2026-10-20 的布局批次将最小原生窗口调整为 800×600，`test:window` 扩展为 13 组 / 78 项主界面检查，新增恢复与审计弹窗；交互专项扩展为 18 组，新增规则校验、重复提交锁、备份失败恢复及恢复确认边界。后续追加服务器扫描忙碌锁、防重复提交和失败重试，当前交互专项为 19 组；该轮 `npm run check` 和 Electron 交互专项通过。定向 Python 用例未能运行，因 `.venv` 缺少 `openpyxl`。设置脚本纳入 `npm run check`。本批通过的尺寸、操作和验收限制见 `窗口布局与操作优化_2026-10-20.md`；旧记录中的最小窗口尺寸和测试组数为对应历史批次结果。

## 发布

```powershell
npm install
npm run build:win
```

发布包不包含本地检测数据库；用户数据随本机 `data/thimble.db` 保留。

# 指套管检测数据管理系统

面向核电机组指套管涡流检测的单机应用。支持读取 CITEC `.rpt/.SUM` 文件、检测记录查询、二维堆芯分布、三维缺陷演化、管状态维护、历次大修对比和 CSV 导出。

三维视图采用随软件打包的本地 Three.js 运行库，不访问外部 CDN。奇数机组与偶数机组使用各自独立的 50 根指套管坐标映射；压力容器底部保持固定，P1-P6 分层显示，支持筛选、点击缺陷和单管局部放大。

“处理检测文件夹”提供两条独立流程：

- `解析并生成 Excel`：扫描 TH 数据组中的 `Report*.rpt`，生成带中文表头、筛选和冻结表头的 `.xlsx`，保存到 `output/excel/`。
- `确认写入数据库`：将解析结果去重后写入本机 SQLite 数据库。

## Windows 桌面软件启动

双击 `启动指套管软件.cmd`。软件在独立桌面窗口中运行，无浏览器地址栏；所有数据库、Three.js 和检测文件均保存在本机。

## 开发服务启动

```powershell
python server.py
```

浏览器访问 `http://127.0.0.1:8765`。首次启动会自动创建 `data/thimble.db`。

## 测试

```powershell
python -m unittest discover -s tests
```

## 运行诊断与数据位置

服务提供 `GET /api/health` 自检接口。桌面壳只接受 `service=thimble-local` 且版本匹配的本地服务，避免误连接其他程序占用的端口。打包版会把数据库、Excel 和日志写入当前用户的 Electron `userData` 目录；开发版仍使用项目下的 `data/` 和 `output/`。也可以通过 `THIMBLE_DATA_DIR`、`THIMBLE_OUTPUT_DIR`、`THIMBLE_LOG_PATH` 覆盖位置。

桌面服务启动失败时查看用户目录下的 `logs/desktop-service.log` 和 `logs/server.log`，其中会记录 Python 启动错误、API 异常和 Excel 导出异常。

Excel 读写运行时随项目内置在 `.vendor/`，包含 `openpyxl` 和 `et_xmlfile` 及其 MIT/兼容许可证文件，保证离线安装不依赖外网下载。

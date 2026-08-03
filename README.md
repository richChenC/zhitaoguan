# 指套管检测数据管理系统

面向核电机组指套管涡流检测的单机应用。支持读取 CITEC `.rpt/.SUM` 文件、检测记录查询、二维堆芯分布、三维缺陷演化、管状态维护、历次大修对比和 CSV 导出。

三维视图采用随软件打包的本地 Three.js 运行库，不访问外部 CDN。奇数机组与偶数机组使用各自独立的 50 根指套管坐标映射；P1-P6 按堆芯下部构件位置显示，支持筛选、点击缺陷、单管视角和 50 路分配架联动。

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

独立三维演示页面：`http://127.0.0.1:8765/visualizations/thimble/index.html`。

## 代码目录

```text
static/
  modules/three-d/              主软件三维模块
    main-view.js
    main-view.css
    labels.css
  visualizations/thimble/       独立指套管三维网页
    index.html
    app.js
    styles.css
  vendor/                       Three.js 与 OrbitControls
docs/
  3d-visualization/             三维建模依据
```

旧地址 `/thimble-visualization.html` 保留为兼容入口，会自动跳转到新的独立页面。

## 测试

```powershell
python -m unittest discover -s tests
```

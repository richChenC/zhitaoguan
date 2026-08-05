# 开发与发布

## 本地启动

桌面模式：双击 `启动指套管软件.cmd`。

服务模式：

```powershell
python server.py
```

默认地址为 `http://127.0.0.1:8765`。桌面壳使用独立端口并自动启动同一个 Python 服务。

## 验证

```powershell
python -m unittest discover -s tests
node --check static/app.js
node --check static/workspace-actions.js
node --check static/visualizations/thimble/app.js
```

## 提交前检查

1. 确认 `data/`、`output/`、`.venv/` 和 `node_modules/` 没有进入 Git。
2. 运行 Python 测试和 JavaScript 语法检查。
3. 手动确认导入、基地/机组/大修筛选、二维管板点击、三维定位和报告导出。
4. 使用独立的版本查询参数更新静态资源缓存版本。

## 发布

```powershell
npm install
npm run build:win
```

发布包不包含本地检测数据库；用户数据随本机 `data/thimble.db` 保留。

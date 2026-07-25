# 指套管检测专业依据与配置边界

## 已采用的资料

1. 项目资料《指套管无损检测专项简报》：用于 Point1-Point6 结构定义、全检要求、磨损位置和堵管/更换背景。
2. 项目 WPS《初识指套管》：用于50条物理路径、15行阶梯管板、奇偶机组左右半圆及编号坐标映射。
3. Park et al., *Development of Eddy Current Technique for Reactor In-Core Flux Thimble Wear* (1990)：支持采用涡流检测管理指套管磨损。
4. Chen et al., *Effect of R Angle of the Outer Extension Tube against the in-Core Flux Thimble in Nuclear Power Plant on Its Wear Behavior*, Scanning, 2021, DOI: `10.1155/2021/1469642`：表明外导向/延伸管几何会影响磨损行为。
5. Wang et al., *Analysis of Thimble Tube Wear Morphology in Nuclear Power Plants Using Eddy Current Testing Technology*, IEEE ICEPG 2025, DOI: `10.1109/ICEPG67373.2025.11466675`：支持在涡流数据中保留磨损形貌与显示分类。

## 软件实现边界

- 磨损深度颜色仅用于可视化排序，不等同于核电厂验收或更换判据。
- 堵管、更换和移位量来自电厂文件，必须人工确认后录入。
- R/NI 判断需考虑更换历史和位置偏移；跨大修比较结果必须由检验人员复核。
- 编号坐标映射中 `N5/M5` 为左右半圆的特殊配对，历史资料提示映射仍需现场图纸最终确认。
- 探头、设备、标定、分析版本和数据完整性属于报告可追溯性信息，不应只保存缺陷结果。

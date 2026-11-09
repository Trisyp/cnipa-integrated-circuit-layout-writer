# 发明专利 skill vs 集成电路布图登记 skill

| 项 | cnipa-patent-writer | cnipa-integrated-circuit-layout-writer |
|----|---------------------|----------------------------------------|
| 目标 | 发明专利申请 .docx | 布图设计登记材料包 |
| 主文件 | 摘要、权利要求书、说明书、附图 | 简要说明、设计图样 TIFF、图样目录 |
| 图 | PNG 嵌入说明书附图节 | 分层 TIFF + ZIP |
| 核心法律叙事 | 新颖性/创造性/权利要求 | 布图独创表达（三维配置/拓扑） |
| 禁止 | 背景写本发明、权1堆小数等 | 规划冒充掩膜、抄参考几何、ZIP 违规 |
| 主脚本 | build_patent*.py | pack_layout_zips.py / check_layout_package.py / make_planning_tiffs.py |
| 废弃 | — | scripts/deprecated/ 下原专利装配器 |

公式与 docx 工具可继续用于**简要说明**，但不再维护「权利要求三处同源」主线。

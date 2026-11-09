---
name: cnipa-integrated-circuit-layout-writer
description: >-
  撰写中国集成电路布图设计登记申请材料：简要说明（.docx/.txt）、设计图样（各层 TIFF/TIF）、
  图样目录，以及按类别分别打包的 ZIP（包内连续命名 1.tiff、2.tiff…，无子文件夹）。
  只借参考示例的格式/版式，绝不抄参考示例的工艺层几何与技术内容。未提供真实 GDS/OASIS/层映射时，
  图样必须标注「规划/示意」，禁止冒充正式掩膜。
  Use whenever the user asks for 布图设计、集成电路布图、布图登记、图样、简要说明、分层 TIFF、
  图样目录、layout registration、IC layout design registration，或要把芯片/加速单元版图整理成
  CNIPA 布图设计登记电子材料——即使只说「按参考示例做图样」或「把这套层图画成登记包」。
---

# 中国集成电路布图设计登记撰写

帮助整理一套**可递交习惯对齐**的布图设计登记材料：简要说明 + 设计图样（总图与分层 TIFF）+ 图样目录，
并按电子申请常见规则打成多类 ZIP。电子申请站点（公开信息）：http://vlsi.cnipa.gov.cn

> **本 skill 不保证登记获准。** 独创性对象是「布图的三维配置/拓扑的可辨认表达」，禁止从算法最优、
> 数学下界或「性能更好」直接推导法律独创性。

## 何时用 / 输入
- 用户要做**集成电路布图设计登记**（不是发明专利三件套）。
- 输入通常包括：设计名称与创作说明、层表/层名、参考示例文件夹（**只借格式**）、可选真实掩膜源
  （GDS/OASIS + 层映射）、是否主张保密信息、申请表待填字段。
- 目标产物（项目目录内）：
  1. 简要说明（结构/技术/功能等）
  2. 设计图样：总图 + 分层图，A4 每页一幅、顺序编号的 TIFF/TIF
  3. 图样目录：写明每页图层名称
  4. 按类别分别 ZIP（图样一包、目录一包、简要说明一包、委托书等各自一类一包）
  5. 交付哈希清单 + HANDOFF / 验收报告（本地）

## 与发明专利 skill 的差异（必读）

| 维度 | 发明专利 skill | 本布图登记 skill |
|------|----------------|------------------|
| 主线文件 | 摘要 / 权利要求书 / 说明书 / 附图 | **简要说明** / **设计图样 TIFF** / **图样目录** |
| 保护对象叙事 | 技术方案 + 权利要求保护范围 | **布图三维配置/拓扑的可辨认表达** |
| 图样 | 说明书附图（PNG 嵌入 docx） | **分层 TIFF**，电子包连续编号 |
| 公式/实施例 | 权要+说明书核心 | 若出现在简要说明中仍要可追溯；无「权1 三处同源」 |
| 独创性表述 | 创造性/新颖性论证习惯 | **禁止**用算法最优/数学下界代替布图独创性；**不保证**登记结果 |
| 门禁重心 | 背景禁写本发明、权要数字等 | **规划图冒充掩膜 FAIL**；目录与 TIFF 页数不一致 FAIL；ZIP 规则等 |

详见 `references/patent-vs-layout.md`。

## 依赖
- 先体检：`python scripts/doctor.py`（只检查、不安装、不联网；`--quick` / `--json`）。
- 必装：`Pillow`（TIFF）；简要说明用 docx 时再装 `python-docx`。
- 可选：`matplotlib`（规划示意页）、`math2docx`（简要说明公式）、soffice/poppler（简要说明渲染）。

## 核心原则
1. **只借格式、绝不抄参考示例技术内容（红线）**：参考示例文件夹只提供纸张、边距、编号方式、TIFF 命名、
   目录栏目、ZIP 分包习惯等**版式**；其工艺层几何、多边形、布线拓扑、层叠关系、标注文字中的技术细节
   **一律不得搬进新设计**。一切图样与说明据用户本设计重新生成。
2. **规划图 vs 正式掩膜**：未提供真实 GDS/OASIS（或等价）与层映射时，产出必须明确标注「规划/示意」，
   文件名、简要说明、目录、HANDOFF 四处一致；**禁止**把规划图说成正式掩膜或「已流片版图」。取得真实源图后，
   按「重建流程」替换为正式导出页并去掉规划标记，重跑门禁与哈希清单。
3. **独创性对象正确**：可主张的是布图配置的独创表达，不是算法复杂度、信道估计公式或性能曲线本身。
   简要说明可概述结构/技术/功能，但勿写成发明专利「权利要求式」保护范围宣言，也勿保证登记结果。
4. **电子材料分包习惯（公开帮助页核对摘要，非全文法规）**：
   - 除登记申请表外，其他文件按类别分别打成 ZIP；
   - **ZIP 内不得有文件夹**；内含连续命名 `1.tiff`、`2.tiff`…（或 `.tif`）；
   - 单包 ≤ 150M；
   - 图样、图样目录、委托书、简要说明等**各自一类一包**；
   - 图样含总图与分层图；纸件 A4 每页一幅并顺序编号；目录写明每页图层名称；
   - 未商业利用可有保密信息，不超过总面积 50%；页码须与申请表一致；
   - 站点：http://vlsi.cnipa.gov.cn  
   详见 `references/cnipa-layout-filing-format.md`。门禁见 `scripts/layout_gates.py` / `check_layout_package.py`。
5. **一致性同源**：图号、层名、目录行、简要说明中的层/模块称谓、正文数字必须同一张层表/术语表生成；
   改一层名要同步目录、图样页题、简要说明与申请表待填项草稿。
6. **保密**：严禁把未公开布图几何、GDS、核心参数、未公开技术方案上传公网或消费级 AI。公网检索只用脱敏框架词；
   本地回填。聊天/日志只报结构结论与 PASS/FAIL。见 `references/confidentiality-and-review.md`。
7. **构建链与终检**：内容源 → 生成/导出 TIFF → 写目录 → 写简要说明 → 分类 ZIP → `check_layout_package` →
   `final_check`（适配布图）→ 哈希交付清单。禁止只手改终包当真源而不更新源表。
8. **禁止泄露拟保密却声称已保密**：若简要说明或公开图样页仍可读出声称「已作保密处理」的区域细节，门禁 **WARN/FAIL**。

## 推荐工作流
### 0. 开工 intake
- 运行/填写 `scripts/session_intake.py` 声明：保密词表路径、是否有真实掩膜源、是否规划模式、输出根目录。
- `python scripts/doctor.py --intake <json>`。

### 1. 锁定层表与术语表（单一源）
- 建立 `layer_table`（层序、层名、总图/分层、是否保密遮盖、对应 TIFF 页号）。
- 建立术语表（模块名、总线名）；简要说明与目录只引用表中名称。

### 2. 图样
- **有真实源**：按层映射导出/渲染 A4 每页一幅 TIFF，顺序编号；总图 + 分层图齐全。
- **无真实源**：生成规划示意页，页内与目录均标注「规划/示意」；几何用虚构示意，不模仿参考示例多边形。
- 像素与格式：按项目约定（常见为可检索的 TIFF）；保持与参考示例**容器习惯**一致，不抄其内容。

### 3. 图样目录
- 每行：页码（或文件序号）+ 图层名称（+ 可选说明：总图/分层/规划）。
- 页数与 TIFF 文件个数、编号连续一致（`1..N` 无跳号）。

### 4. 简要说明
- 写该布图的结构、技术、功能等（登记说明习惯，非专利说明书五大章硬套）。
- 若含公式/数值：可追溯；OMML 规则可参考 `references/omml-equations.md`（可选）。
- 勿粘贴大段未公开网表/坐标。

### 5. 打包
- `python scripts/pack_layout_zips.py --manifest <manifest.json> --out <outdir>`
- 一类一包；包内无文件夹；连续 `1.tiff`…；检查单包大小。

### 6. 门禁与交付
- `python scripts/check_layout_package.py <outdir>`
- `python scripts/layout_gates.py --selftest`；项目侧调用规划冒充/目录不一致/保密声明等门禁。
- `python scripts/final_check.py`（布图模式）写出 reports/ 验收快照与哈希清单。
- 更新项目 HANDOFF：规划 vs 掩膜状态、未决项、下次勿踩坑。

### 7. 真实源到达后的重建
1. 接入 GDS/OASIS + 层映射；2. 重新导出正式 TIFF；3. 去掉所有「规划/示意」标记；
4. 同步目录与简要说明；5. 重打包；6. 全部门禁 + 新哈希清单；7. HANDOFF 记录切换日期与旧规划包归档路径。

## 工程化门禁（布图）
| 代号 | 条件 | 级别 |
|------|------|------|
| PLAN_AS_MASK | 无真实源标记却声称「正式掩膜/流片版图」 | FAIL |
| CATALOG_TIFF_MISMATCH | 目录页数 ≠ TIFF 个数或编号不连续 | FAIL |
| ZIP_HAS_FOLDER | ZIP 内含目录项 | FAIL |
| ZIP_NAME_GAP | 非 `1..N` 连续 tiff/tif | FAIL |
| ZIP_TOO_BIG | 单包 > 150MB | FAIL |
| MIXED_CATEGORY | 异类文件打进同一业务包 | FAIL |
| SECRET_CLAIM_LEAK | 声称保密但公开页未遮盖或说明仍泄露 | WARN/FAIL |
| TERM_DRIFT | 层名在目录/说明/页题不一致 | FAIL |
| HASH_DRIFT | 交付清单哈希与当前文件不符 | FAIL |

通用脚本思想保留：`doctor`、`render_check`（简要说明）、`query_guard`、`evidence_ledger`（数值可追溯）、
`final_check`、`selftest_all`。原发明专利专用脚本见 `scripts/deprecated/`，**不要再假装能写发明专利**。

## 资源索引
- `references/cnipa-layout-filing-format.md` — 电子申请材料格式摘要（含站点与 ZIP 规则）
- `references/patent-vs-layout.md` — 与发明专利 skill 差异
- `references/confidentiality-and-review.md` — 保密与检索
- `references/layout-drawings.md` — 图样/TIFF/规划页
- `references/brief-description.md` — 简要说明行文
- `references/docx-format.md` — 简要说明 docx 版式（可选）
- `references/omml-equations.md` — 公式（可选）
- `scripts/doctor.py` / `layout_gates.py` / `pack_layout_zips.py` / `check_layout_package.py` / …

## 易踩坑
- 把参考示例层几何「描」进新图 → 侵权与错设计双风险。
- 规划 TIFF 当正式掩膜递交话术 → FAIL。
- ZIP 里套文件夹或 `fig1.tiff` 非数字连续名 → 电子申请习惯不符。
- 目录写「金属1」图页写「M1」说明写「第一金属层」且未建别名表 → 一致性失败。
- 公网上传 GDS/未公开布图 → 保密事故。
- 用「算法更优」代替布图独创性叙述 → 对象错误。
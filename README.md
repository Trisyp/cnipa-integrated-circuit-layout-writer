# cnipa-integrated-circuit-layout-writer

> **Cursor / Claude Code Agent Skill**：整理中国**集成电路布图设计登记**申请材料。  
> **判断标准以 CNIPA/vlsi 电子申请硬规格及《集成电路布图设计保护条例》（2026 年修订）公开说明为准。**  
> **参考示例只学打包方式，不是规格上限；禁止抄示例工艺几何。**

覆盖：**简要说明**、**设计图样（总图 + 分层 TIFF）**、**图样目录**、**独创性声明**（技术正文可起草，签章/法定事实栏留空），以及按类别分别打包的 **ZIP**（包内连续 `1.tiff`…，无子文件夹，单包 ≤150M）。电子申请站点（公开信息）：http://vlsi.cnipa.gov.cn

本 skill **不保证登记获准**；独创性对象是布图三维配置/拓扑的可辨认表达，禁止用算法最优/数学下界直接推导法律独创性。摘要已核、细则全文 PDF 仍可能待核，递交前再对官网。

## 亮点

- **官方规格优先于示例**：一类一包、ZIP 无文件夹、连续编号、单包 ≤150M、目录与 TIFF 页数一致；不必与参考示例逐页或逐分辨率对齐。
- **默认四分包**：设计图样 / 图样目录 / 简要说明 / 独创性声明（委托书等视情况另包）。申请表在 vlsi 在线填写。
- **图样来源分层**：真实 GDS/OASIS 按层导出；无可外部 GDS 但有可复现几何时，生成「本布图设计之原创分层图样」（真实线宽多边形与过孔阵列），不必强制标注「规划/示意」。
- **签核门禁**：无签核证据却声称已完成第三方 PDK DRC/LVS/流片 → FAIL。Foundry 源图 ≠ 签核证据。不代填创作人、创作完成日等法定事实（修订日/构建日 ≠ 创作完成日）。
- **一致性同源**：层表驱动目录 / 页题 / 简要说明 / 独创性声明称谓。
- **保密**：公网检索脱敏；不上传未公开布图；本地回填。
- **工程化**：`doctor` / `layout_gates` / `pack_layout_zips` / `check_layout_package` / `final_check` / 哈希清单。
- **与发明专利 skill 分离**：原 `build_patent*` 等已移入 `scripts/deprecated/`，不再作为主路径。

## 仓库结构

```
cnipa-integrated-circuit-layout-writer/
├── SKILL.md
├── requirements.txt
├── references/
│   ├── cnipa-layout-filing-format.md   电子申请材料格式摘要（条例、声明、示例定位）
│   ├── patent-vs-layout.md             与发明专利 skill 差异
│   ├── confidentiality-and-review.md   保密与检索
│   ├── layout-drawings.md              图样 / TIFF / 来源分层
│   ├── brief-description.md            简要说明
│   ├── docx-format.md                  简要说明 docx（可选）
│   └── omml-equations.md               公式（可选）
├── scripts/
│   ├── doctor.py
│   ├── layout_gates.py
│   ├── pack_layout_zips.py
│   ├── check_layout_package.py
│   ├── make_planning_tiffs.py          仅用于中心线/示意占位页（非已签核掩膜）
│   ├── final_check.py
│   ├── query_guard.py
│   ├── evidence_ledger.py
│   ├── session_intake.py
│   ├── selftest_all.py
│   └── deprecated/                     原发明专利装配脚本（不维护主路径）
└── tests/fixtures/                     纯虚构夹具
```

## 快速开始

```bash
pip install -r requirements.txt
python scripts/doctor.py --quick
python scripts/layout_gates.py --selftest
python scripts/selftest_all.py
```

项目侧准备 `layer_table` 与图样页后：

```bash
python scripts/pack_layout_zips.py --manifest manifest.json --out dist/
python scripts/check_layout_package.py dist/
```

## 安装（可选 npx）

```bash
npx cnipa-integrated-circuit-layout-writer           # → ~/.claude/skills/...
npx cnipa-integrated-circuit-layout-writer --check
```

## 许可

MIT. 由发明专利 skill 分支改造而来；本仓库专用于布图设计登记材料流程。

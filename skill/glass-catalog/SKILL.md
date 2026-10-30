---
name: glass-catalog
description: Zemax AGF 与 CODE V XML 双向转换、厂家表 MA/A/B/C/D 匹配、状态与透过率筛选建库、两个软件的库安装备份卸载、CODE V 两张目录同步与 Glass Expert DAT 导出。用于材料库文件管理，材料理论问答用 optic-expert。
---

# Glass Catalog

共用转换核心，支持 AI 命令和人工窗口。有 `config.json` 时先读它确认路径；`tool_root` 指向源码，分享版的 `executable` / `gui_executable` 是相对本技能目录的独立程序路径。公开源码中的 `skill/glass-catalog` 默认调用上两级项目根目录，无需个人配置；技能单独移动时添加 `config.json` 并设置 `tool_root`。独立程序直接执行，无需 Python。程序参数以入口的 `--help` 为准。

| 方向 | 输入 | 输出与后续 |
|---|---|---|
| Zemax → CODE V | `.AGF` | 默认交付 `.xml` 及材料、热光目录完整包；安装时同步两个总表 |
| CODE V → Zemax | CODE V Catalog `.xml` | Zemax `.AGF`；按 [反向转换流程](references/codev-to-zemax.md) 核对系数、单位与透过率 |
| Glass Expert 候选清单 | 目标 CODE V `glass/` 中已安装的 `.xml` | 筛选后导出 TAB 分隔的 `.dat`；按 [玻璃专家导出](references/glass-expert.md) 核对安装目录与材料引用 |

入口（下称 `<入口>`）：

```text
<本技能目录>/scripts/glass_catalog.py
```

## 检查、筛选和转换

1. 先对用户输入运行 `python -X utf8 <入口> inspect <文件...> --json`，核对来源、数量、公式、有效波段和 `issues`。AGF 与 XML 是完整材料输入；任意 DAT 宏表不能作为完整玻璃库反向还原。
2. 将用户条件传给 `inspect` / `convert`。`--names` 精确名单，`--name` 名称包含；nd / Vd / 密度含边界。原生供应状态用 `--supply-status agf:0 agf:1`（Zemax 标准/优选）或 `codev:10 codev:11`（CODE V 最高/较高熔炼频率），多选为 OR；查看 `supply_label`、`supply_status`，不用近似 AGF status 解释 XML。AGF 独立熔炼频率用 `--melt-frequency 1 2 3`；厂家 MA/A/B/C/D 与软件数值不保证可逆，按 [状态与数据边界](references/usage.md) 核对。内透过率用 `--it-at-nm 550 --it-thickness-mm 10 --it-min 95`（百分数）；无覆盖数据则不入选。波长范围内线性插值，厚度按 Beer–Lambert 换算，不含表面反射、不外推；多个实测厚度选最接近目标比例且覆盖波长的曲线。`inspect` 返回计算值与方法，转换报告保存条件。跨库同名用来源区分或用户接受的前缀，不自行丢记录。
3. 用 `convert <文件...> --output <新库.AGF或.xml> --json` 导出。未指定名字时按“来源库_筛选标记_日期”取英文名，例如 `CDGM_MA_A_B_20261030`；多来源可用 `MIXED`，其他筛选可用 `FILTERED`，DAT 加 `EXPERT`。优先沿用用户指定的名称，文件名与库内名称保持一致；省略 `--catalog-name` 时核心直接采用文件名。CODE V 默认加 `--codev-root <config中的安装目录>`，一次生成 XML、单库 DAT、`CatalogFull.dat`、`dndt_constants.dat` 及报告；用户明确只要 XML 时可省略。复读输出，核对材料数量、目录包 `table_changes` 与名称映射，交付完整包和报告。导出不会安装到软件目录。

跨格式当前覆盖公式 1 / 2 / 3 及等价六系数模型。暂不支持的模型和异常光学记录会明确失败；`--convertible-only` 仅在用户接受排除这些材料时使用，并报告排除数量。原生格式筛选保留原始记录。

AGF 内透过率 `1 < IT ≤ 1.001` 默认自动按 100% 导出 XML，并逐点记录原值；这是用户已确认的常规处理，无需逐次询问。此类材料仍属于默认可转换集合。更大超限或其他无效数据按 [数据边界](references/usage.md) 处理。

CODE V → Zemax 时读 [references/codev-to-zemax.md](references/codev-to-zemax.md)。多厚度透过率需明确 `--transmission-thickness <mm>`，可用 inspect 的 `transmission_thicknesses_mm` 查看选项。色散、热学和附加字段转换的实际边界在工具根目录 `README.md`，改变转换规则或遇到相关提示时读取该处。报告里的损失项应随结果说明。

常用参数见 [references/usage.md](references/usage.md)。人工版用 `gui`、工具的 `打开玻璃库管理.bat`，或分享包的 `GlassCatalog.exe`。侧栏“玻璃库管理”下 CODE V、Zemax 相邻同级，均在顶部选安装位置、中间列出库、底部操作选中库；导出设置显示目标并提供跳转。CODE V 可浏览、载入、安装完整包与卸载；Zemax 另提供独立备份与恢复。窗口自动建议库名，手工修改后不随筛选覆盖，保存窗口改文件名会同步库内名称。DAT 与 AGF/XML 各自保留名称和材料来源；DAT 点击“选择已安装库”后筛选导出。操作结果为无声页内提示，路径与报告可展开。人工版与 AI 同一核心；更新后重开旧窗口。

用户要求按厂家 MA/A/B/C/D 选材时，加载其提供的 CSV/TSV/XLSX：`--supplier-table <表> --supplier <厂家> --supplier-grade MA A B`。已知厂家如 CDGM 可从表文件名识别；按厂家库名前缀及牌号匹配，仅忽略空格、连字符和大小写，不做近似猜测。先 inspect 核对 `supplier_table` 的版本、匹配数和 `supplier_grade`，再转换；未匹配材料不进入字母筛选结果。结果报告 `supplier_data` 保留来源、SHA256、版本及牌号分级，不改原库软件状态或光学数据。库名无法识别厂家或需跨版本对应时，按 [厂家表规则](references/usage.md) 处理。

分享软件时交付完整 ZIP，保留 `_internal`、两个 EXE 和 `skill/glass-catalog` 的相对位置；不要只发送主 EXE。完整包不带用户材料库或本机绝对路径。用源码维护后按工具 `build_release.py` 重建，独立运行检查见工具 README。

## Zemax 库管理

用户要求安装、更新、查看、备份、卸载或恢复 Zemax 库时，读 [references/zemax-management.md](references/zemax-management.md)。统一入口为 `zemax list/install/backup/uninstall/restore --glasscat <实际目录> --json`。AGF 安装与 GUI 的转换安装共用文件管理逻辑，先备份旧 AGF / BGF，再让 Zemax 自动重建缓存；不手工生成 BGF。不把文件安装等同于镜头已启用材料库。

## 安装、更新或卸载 CODE V 库

用户要求导入、安装、更新或卸载 CODE V 库时，必须读 [references/codev-install.md](references/codev-install.md) 并完成文件处理和软件查询验证。已获授权的同一范围直接执行；只有转换文件、开发功能或编写 skill 的请求，不等于实际安装或卸载某个库。

**XML 对应的两个总表都要同步：`macro/CatalogFull.dat` 和 `macro/dndt_constants.dat`。** `convert --codev-root` 或已有 XML 的 `codev prepare` 生成保留其他厂家的合并包；`codev apply` 备份后写入 XML、单库 DAT 和两张合并总表；`codev verify` 核对文件。

查看已安装库用 `codev list --codev-root <目标目录> --json`，返回每个 XML 的位置、材料数量与提示；个别坏文件单独返回 error，不隐藏其他库。列表只读。

用户要求直接安装新转换结果时，`convert ... --codev-root <目标目录> --install-codev --json` 一次完成，核对 `codev_installation` 的文件状态及备份。卸载使用 `codev uninstall <库名> --codev-root <目标目录> --json`，备份后删除库文件和两张当前总表中的该库行；保留其他库，不用安装前的旧整表覆盖当前总表。

文件同步成功与 CODE V 内识别分别记录。最终以 GLD / GLI / GPR 查询到新库、材料和数量为软件验收证据；如未完成，只报告“文件已同步，软件识别待验证”。用户说的目录更新是维护目录文件，不假设存在刷新菜单或命令。

## 维护与续接

维护转换代码时，在工具根目录运行 `python -X utf8 -m unittest discover -s tests -v`。已有项目恢复记录时沿用，不将任务进度累积到 skill。技能只保留一个调用入口，转换实现仍在项目源码中，迁移时核对 config 或相对项目位置。

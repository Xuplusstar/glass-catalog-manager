# Zemax / CODE V 玻璃库管理 1.3.0

同一个转换核心供人工窗口、AI skill 和独立命令行使用。支持 AGF ↔ CODE V XML、筛选组合建库、两边的材料库管理和 CODE V Glass Expert DAT 候选清单。无需 MATLAB。

当前是功能开发版，提供 Windows 免安装 ZIP。正式安装程序、桌面/开始菜单入口及软件升级卸载，待功能定版后交付。

## 人工使用与分享

从 [GitHub Releases](https://github.com/Xuplusstar/glass-catalog-manager/releases) 下载 GlassCatalog-1.3.0-Windows-x64.zip，或使用本机构建的 release/ 中同名 ZIP。解压完整文件夹后双击 GlassCatalog.exe，不需要另装 Python。适用 Windows 10 / 11 x64。开发期间本机仍可双击“打开玻璃库管理.bat”，优先打开最新版打包程序，否则使用源码环境。

完整包保留 _internal、GlassCatalog.exe、GlassCatalogCLI.exe 和 skill/glass-catalog 的相对位置。不要只发主 EXE。包不包含用户的玻璃库、软件总表、镜头或个人设置。详细操作见[使用说明.txt](使用说明.txt)。

侧栏分“工作区”和“玻璃库管理”两组，CODE V 与 Zemax 管理页相邻同级：

| 页面 | 用途 |
|---|---|
| 玻璃库与筛选 | 导入一个或多个 AGF / XML，查看参数、筛选与多选 |
| 导出设置 | XML / AGF / DAT、命名前缀、透过率厚度、目标位置、DAT 已安装库选择 |
| CODE V 库管理 | 已安装库查看、双击载入工作区、安装完整包、卸载并同步两张总表 |
| Zemax 库管理 | 已安装库查看、双击载入工作区、安装已有 AGF、备份、卸载及恢复 |

两个管理页均按“安装位置 → 安装操作 → 已安装库列表 → 选中库操作”排列，转换输出栏只在工作区出现。安装位置在各管理页修改，“导出设置”显示当前目标并提供跳转。

新库自动按“来源库＋筛选标记＋日期”命名，例如 `CDGM_MA_A_B_20261030`；多来源用 `MIXED`，其他筛选加 `FILTERED`，DAT 加 `EXPERT`。来源名中的空格和连字符改为下划线。可手动修改，后续筛选不会覆盖手工名称；“自动命名”重新采用当前建议。DAT 与 AGF/XML 各自记住名称。

保存窗口中最终选定的文件名会同步为库内名称和安装包中的库名；无扩展名时补齐当前格式，扩展名与所选格式不符时提示纠正。默认保存在 exports，并记住上次保存位置。完整包目录带有“CODEV安装包”字样，一键安装输出目录同时标注库名、目标软件和时间。CLI 仍可用 `--catalog-name` 显式指定库内名称。

底部随格式联动：XML 为“转换并安装到 CODE V”，AGF 为“转换并安装到 Zemax”，DAT 为“导出 DAT 清单”。“导出筛选结果”保存当前列表全部材料，“仅导出选中”保存 Ctrl / Shift 选择的材料。一键安装默认用筛选结果；只装选中行需在导出设置勾选对应选项。DAT 独立保存已安装库选择，与原 AGF/XML 转换来源分开；切回原格式仍可继续转换。

成功、失败、空结果均使用无声页内通知，详情可展开并复制；没有 QMessageBox 提醒或提示音。材料详情使用普通数据窗口，两个管理页均在列表中选库后卸载。

## 筛选规则

供应状态按来源软件原生定义显示和多选，同组为 OR，与名称、nd / Vd、密度、透过率等条件为 AND。不选则不限。Zemax status：0 标准、1 优选、2 停产、3 特殊、4 熔批。CODE V 保留 Availability 原码与含义：例如 8 请询厂家、10 最高熔炼频率、11 较高、12 低、14 很低；不再把这些状态都显示为“特殊”。鼠标悬停状态可看原码。混合来源时，菜单分别标注 Zemax 和 CODE V。

命令行原生筛选用 --supply-status agf:0 agf:1 或 --supply-status codev:10 codev:11，可组合多个来源。旧 --status 参数仍按旧的 AGF/近似映射工作，保留脚本兼容；XML 精确选材应改用原生参数。

熔炼频率是独立字段：AGF 读取 NM 最后一项 melt freq，按 1～5 多选筛选（1 很频繁、5 很少），与供应状态分开；XML 仅在 Availability 明确含频率时显示相应原生描述，不凭“优选/标准”推断频率。CLI 为 --melt-frequency 1 2 3，设定时只选择具有对应 AGF 等级的材料。JSON 同时返回 supply_status、supply_label、melt_frequency 和 melt_frequency_label。

成都光明的 MA/A/B/C/D 属于厂家生产频率。厂家 2025-09 参数表定义 MA 常年在库、A 每年两次以上、B 每年一次、C 每 1～2 年一次、D 两年以上一次。软件库的数值不保证逐字母对应；本机同版 AGF 中已有多处 C/D 共用等级 4，因此界面不把数字强制还原为厂家字母。需要精确字母时应核对同版厂家表。

现在可在“导出设置 → 厂家生产频率表”选择厂家 CSV、TSV 或 XLSX。表头应含 Glass/牌号 和 Melt Frequency/生产频率/熔炼频率两列；CSV 支持 UTF-8/GB18030。CDGM 等已知厂家可从文件名自动识别，其他表手工填写厂家缩写后点“读取表”。回到筛选页，在“厂家分级”多选 MA/A/B/C/D；列表和详情显示匹配结果，未匹配材料显示“—”，选择分级时排除未匹配材料。

匹配仅用于厂家前缀明确的库，如 CDGM、CDGM202509、CDGM-ZEMAX202509。牌号忽略空格、连字符和大小写，其余差异不猜测；自定义库名不自动推断厂家，应先在原厂家库上匹配再组合。厂家表只补充筛选与报告，不改原库软件状态、熔炼频率或光学记录。报告 supplier_data 保留表路径、SHA256、文件名中的年月版本及匹配分级。原库与表版本不同也会显示各自来源，分级只代表所载入的表。关闭窗口后记住表位置，下次重新读取；表不随软件分发。

透过率填写波长 nm、厚度 mm、百分数上下限，例如 550 nm、10 mm、下限 95。筛的是内透过率，不包括表面反射。实测曲线内按波长线性插值，再按 Beer–Lambert 指数规律换算厚度；不外推。有多个实测厚度时，在覆盖波长的曲线中选与目标厚度比例最接近者。设置阈值时排除无数据材料，未设阈值时不因此排除。此换算是筛选估计，不改变原始曲线。数值范围含边界。

AGF 内透过率轻微超限（100%～100.1%）按用户确认的默认政策以 100% 导出到 XML，逐点记录原值。原始 AGF 和同格式 AGF 导出不变。更大超限、负值、无效厚度仍明确提示。严格模式可关闭自动处理。

## CODE V 完整包、安装和卸载

选择 XML，默认同时生成 XML、单库 DAT、CatalogFull.dat 与 dndt_constants.dat，两张总表保留其他库。仅导出不会修改 CODE V。完整包在输出 XML 旁的带时间目录中，包含 glass/、macro/、catalog_tables/、manifest.json 与转换报告。

“转换并安装到 CODE V”自动转换、建包、备份、同步四个文件并核对。进入侧栏“CODE V 库管理”可浏览已安装库、双击载入筛选工作区、安装已有完整包，或选中库后卸载。卸载先备份，再从当前总表清除该库行，保留其他库；不会用安装前的旧整表覆盖后来改动。CLI 只读列表使用 `codev list --codev-root <安装目录> --json`。

完整包是所选 CODE V 的合并快照。人工安装时会核对包的目标与管理页所选目录一致；目标总表自准备后发生变化会要求重新准备。分享程序或 XML 后应按接收方的实际目录重新建包，不能把别人的旧整表直接覆盖过来。

文件安装成功与软件识别分开记录。实际 CODE V 中用 GLD / GLI / GPR 查询库名、材料和数量；未做软件内查询就只说明文件已同步。用户禁止操控桌面时不启动交互。

## Zemax 管理

Zemax 安装目录指实际使用的 Glasscat 文件夹。在管理页可查看文件和材料数量、载入工作区、安装已有 AGF、独立备份、卸载与从备份恢复。选 AGF 后的主按钮也可直接转换并安装。

安装或更新前备份同名 AGF 和旧 BGF，写入新 AGF 后移除旧缓存；BGF 由 Zemax 自动生成。卸载只移除选定库的 AGF / BGF，恢复前再次备份当前版本。默认备份在 Glasscat/catalog_backups/。

安装后仍需在目标镜头 System Explorer → Material Catalogs 中加入库名，并查询材料与折射率。文件操作不自动更改当前镜头。

## Glass Expert DAT

导出 TAB 分隔、CRLF 换行、Catalog / Glass 两列的用户候选清单，格式依据 CODE V 本机手册 Opt_9_ExpertTools.10.03.html、.10.06.html 和用户原有 Glass Expert/*.dat。手册明确仅要求前两列，特殊材料使用 SPECIAL、私有材料使用 PRV。

1. 底部选择 Glass Expert DAT；首次使用在“导出设置”核对 CODE V 安装位置。
2. 点击“选择已安装库”，从该 CODE V 的 glass 文件夹中勾选一个或多个 XML 库，点击“载入所选库”。支持按库文件名搜索。
3. 在列表筛选材料，或用 Ctrl / Shift 选中行。DAT 不要求材料能跨格式转换，支持原库红外材料。
4. 填写“清单名称”，点击“导出 DAT 清单”保存筛选后的全部材料；“仅导出选中 · DAT”只保存选中行。
5. 在 CODE V Glass Expert 选择 USER，再指定导出的 DAT 为 User Catalog。

DAT 保留已安装 XML 的原库名和牌号，不新建材料库。共用核心要求 --codev-root，来源必须是该目录 glass 中的实际 XML；写出前重新核对库名和牌号，已卸载或已改名的引用会停止导出。AGF 或外部 XML 先按常规 XML 流程转换安装，再从已安装库选择。修改 CODE V 位置会清空旧的 DAT 库选择，避免混用两个安装目录。

DAT 只保存候选引用，不含完整色散 / 热光数据，也不是带 Surfaces、AUTO 等参数的 USER.dat 优化配置。导出不修改已安装 XML 或两张宏总表；以后移除材料库时，已有 DAT 需重新核对。文件引用核对不等于已完成软件内优化验证。

## AI 与命令行

源码运行示例（在工具目录）：

~~~powershell
# 多状态与透过率筛选
python -X utf8 glass_catalog.py inspect source.AGF --supply-status agf:0 agf:1 --melt-frequency 1 2 3 --it-at-nm 550 --it-thickness-mm 10 --it-min 95 --json

# 按厂家表的 MA/A/B 分级筛选；不从软件数字反推字母
python -X utf8 glass_catalog.py inspect CDGM.AGF --supplier-table CDGM202509.xlsx --supplier-grade MA A B --json

# AGF → CODE V，完整包；加 --install-codev 即备份后安装
python -X utf8 glass_catalog.py convert source.AGF --output exports/CUSTOM.xml --codev-root C:\CODEV202503 --json

# CODE V → Zemax；多厚度曲线明确选择厚度
python -X utf8 glass_catalog.py convert C:\CODEV202503\glass\SCHOTT.xml --names NBK7 --transmission-thickness 25 --output exports/CUSTOM.AGF --json

# 只从已安装库生成 Glass Expert 清单，可同时传入多个已安装 XML
python -X utf8 glass_catalog.py convert C:\CODEV202503\glass\CDGM.xml --output exports/CANDIDATES.dat --codev-root C:\CODEV202503 --supply-status codev:10 codev:11 codev:12 --json

# Zemax 管理
python -X utf8 glass_catalog.py zemax list --glasscat D:\Zemax\Glasscat --json
python -X utf8 glass_catalog.py zemax install exports/CUSTOM.AGF --glasscat D:\Zemax\Glasscat --json
python -X utf8 glass_catalog.py zemax backup CUSTOM --glasscat D:\Zemax\Glasscat --json
python -X utf8 glass_catalog.py zemax uninstall CUSTOM --glasscat D:\Zemax\Glasscat --json
python -X utf8 glass_catalog.py zemax restore <备份目录> --glasscat D:\Zemax\Glasscat --json

# CODE V 包与卸载
python -X utf8 glass_catalog.py codev prepare exports/CUSTOM.xml --codev-root C:\CODEV202503 --bundle exports/CUSTOM_install --json
python -X utf8 glass_catalog.py codev apply exports/CUSTOM_install --json
python -X utf8 glass_catalog.py codev verify exports/CUSTOM_install --json
python -X utf8 glass_catalog.py codev uninstall CUSTOM --codev-root C:\CODEV202503 --json
~~~

分享版将 python -X utf8 glass_catalog.py 替换为 GlassCatalogCLI.exe，参数相同。核心命令行只用 Python 标准库；独立 CLI 自带运行环境。--json 成功返回 ok: true，失败返回 ok: false，退出码 2。

源码项目的 [glass-catalog skill](skill/glass-catalog/SKILL.md) 默认通过相对路径调用项目根目录，无需个人配置：`python -X utf8 skill/glass-catalog/scripts/glass_catalog.py inspect source.AGF --json`。本机安装的 skill 通过 config.json 指向同一份源码。分享包的 skill 配置相对指向独立 EXE，AI 可直接调用 EXE 而不安装 Python；也可用 scripts/glass_catalog.py 包装入口。技能单独移动时在其目录添加 config.json，设置 tool_root 为项目路径，或 executable/gui_executable 为程序路径。

常用筛选参数：--name、--names、--source-catalog、--nd-min/max、--vd-min/max、--density-min/max、--supply-status、--melt-frequency、--supplier-table、--supplier、--supplier-grade、--convertible-only、--it-at-nm、--it-thickness-mm、--it-min/max。convert --help、zemax --help、codev --help 给出对应子命令。每次转换生成 .report.json，记录筛选、数量、名称、损失项、透过率修正及哈希。

## 位置与构建

分享版自动安装导出目录是当前用户文档/玻璃库管理/exports；手动导出位置可选。源码版沿用项目 exports/。目录设置保存在当前用户 AppData/Local/GlassCatalog/settings.json；新机器按实际位置设置，不携带开发机的个人配置。

源码图形窗口使用 requirements-gui.txt 中的 PySide6-Essentials，标准库转换核心无第三方依赖。构建用 Python 3.13 x64：

~~~powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe -X utf8 glass_catalog_gui.py
.\.build-venv\Scripts\python.exe -X utf8 build_release.py
~~~

构建日志在 build/build-release.log。公开项目自带可迁移 skill 和合成测试，不依赖开发机材料库或个人配置。GitHub Actions 在 Windows 上执行回归、构建和异地解压验收，并保存 ZIP 构建产物。分享包保留动态 Qt 库、第三方许可、共用源码及完整合成测试。

## 示例与目录

使用自己已安装软件中的材料文件作为实际示例：Zemax 的实际 Glasscat/*.AGF，以及 CODE V 安装目录 glass/*.xml。详见 [examples/README.md](examples/README.md)。本地 examples/Zemax 和 examples/CODEV 可保留各一份原文件副本；公开仓库、分享包不包含厂家材料库、厂家表、软件原总表或个人设置。自动测试使用合成数据，所有安装卸载都在临时目录中执行。

| 位置 | 内容 |
|---|---|
| 项目根目录 | 共用核心、人工窗口入口、构建脚本与使用说明 |
| assets/ | 界面图标 |
| tests/ | 合成数据与回归测试 |
| skill/glass-catalog/ | AI 技能；开发机为指向技能正本的 Junction，GitHub 保存可分发内容 |
| examples/ | 实库示例说明及本地原文件副本 |
| release/ | 最新免安装版，构建后生成 |
| exports/ | 本地导出结果与当前验收，不进入 Git |

旧 MATLAB 与初期样例在本地 _archive/ 中压缩留存；旧发行版、构建缓存和重复试验输出可清理。`.build-venv/` 是重建程序使用的开发环境，人工用户不需要它。

## 支持范围与验证

跨格式覆盖 Zemax 1 Schott、2 Sellmeier 1、3 Herzberger，对应 CODE V Laurent、Glass Manufacturer Sellmeier、Herzberger，另支持没有额外非零项的六系数 Glass Manufacturer Laurent。系数直接映射，不做拟合。其他模型可原格式筛选导出，跨格式会列出材料并停止；只有用户接受排除时用 --convertible-only。

- AGF 支持 UTF-16 / UTF-8 / 传统西文 ANSI；原格式筛选保留未知记录、注释、厂家扩展与原始数据。
- 不能跨格式表达的价格、日期、厂家属性、MD / OD / BD 等见报告；保留原始库。
- XML → AGF 有多厚度曲线必须选择厚度；超过 AGF 100 点不自行删点。
- 只有 dn/dT 温区表而无常数、不同类别常数冲突时不能直接等价写 TD。
- AGF → XML 的色散温度沿用原程序 20°C，TD 参考温度另存；CTE 原始测量温区可能不等价。温度与热学属性仍需软件内核验。
- 当前 CODE V 两张宏总表的辅助生成覆盖六系数可见光材料，DPF 暂为 0。原库 Glass Expert 两列引用清单不受这一可见光限制。
- 任意 DAT 不是完整玻璃库输入。新功能使用共用 Python 核心。

2026-10-30：69 项自动测试通过，覆盖三种支持公式的往返、参考折射率和 CTE、旧字段保留、默认超限处理、CODE V 两总表同步备份及其他库保留、原生供应状态及独立熔炼频率、厂家 CSV/TSV/XLSX 匹配与来源报告、透过率筛选、DAT 已安装库引用复核、Zemax 管理及实际 Qt 回调、小窗口和格式联动。

~~~powershell
$env:QT_QPA_PLATFORM='offscreen'
python -X utf8 -m unittest discover -s tests -v
GlassCatalog.exe --self-check <验证报告.json>
python -X utf8 verify_release.py release/GlassCatalog-1.3.0-Windows-x64.zip --report build/verification.json
~~~

独立程序自检使用合成材料和临时软件目录，核对打包后模块、样式资源、筛选与各文件流程，不打开或操控桌面。真实 Zemax / CODE V 中的导入识别及热学语义验收尚未完成；不将本版称为全公式 / 全属性无损转换器。

## 许可证

本项目自有源码、文档及配套 AI skill 采用 [MIT 许可证](LICENSE)，允许使用、修改、商业使用和再分发；再分发时保留版权声明与许可证。软件按许可证中的“按现状”条款提供。

Python、Qt/PySide6、Shiboken6、PyInstaller 等依赖保留各自许可证，分享包的 licenses/ 中附相关文本。MIT 许可不授予第三方玻璃库、厂家表或 Zemax/CODE V 软件的权利。

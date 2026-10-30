# CODE V 材料库安装与目录更新

用户在本任务确认：新库不仅要有 XML，还要同步维护 `CatalogFull.dat` 和 `dndt_constants.dat` 两个总表。此流程覆盖文件安装与后续识别验证，不另假设有“刷新材料库”命令。

## 读取本机目标再生成合并结果

从 config 确认目标安装目录，本机为 `C:\CODEV202503`。输入应是已经转换、复读并核对的最终 CODE V XML；库名以 XML 的 `<Catalog><Name>` 为准，XML、单库 DAT、总表 Catalog 列一致。

新转换默认直接用 `convert ... --output CUSTOM.xml --codev-root C:\CODEV202503 --json` 生成完整包，结果字段 `codev_bundle` 给出位置，可用 `--bundle` 指定新目录。人工窗口默认启用“同时生成材料目录和热光目录”，读取所选安装目录中的两张原表；它与 AI 调用同一入口。下面的 `codev prepare` 用于已有 XML，二者生成内容相同。

```powershell
$glassTool = '<本技能目录>\scripts\glass_catalog.py'
python -X utf8 $glassTool codev prepare 'D:\glass\CUSTOM.xml' --codev-root 'C:\CODEV202503' --bundle 'D:\glass\CUSTOM_install' --json
```

`prepare` 只在独立目录生成：

| 相对路径 | 用途 |
|---|---|
| `glass/CUSTOM.xml` | CODE V 原生材料库 |
| `macro/custom.dat` | 本库的玻璃专家输入表 |
| `macro/CatalogFull.dat` | 原总目录与新库材料合并后的完整总表 |
| `macro/dndt_constants.dat` | 原热光目录与新库材料合并后的完整总表 |
| `catalog_tables/*_CUSTOM.dat` | 本库材料的增量表，仅供核查 |
| `manifest.json` | 材料数量、文件哈希、被替换的本库行数及目标位置 |

通过 `convert --codev-root` 生成的包另附 `conversion-report.json`，包含筛选、名称映射和透过率自动处理记录。仅生成文件不改写 CODE V；人工窗口“一键转换并安装到 CODE V”或转换参数 `--install-codev` 自动执行备份安装。“安装已有导出包”则用于已有的文件包。

人工管理页安装已有包时，包内的目标目录必须与当前选定的 CODE V 位置一致；不同电脑或安装位置应重新准备完整包。

合并规则：保留其他 Catalog 的记录和原表头；用最终 XML 的完整材料集合替换同名 Catalog 的旧行。再次更新缩小后的库时，旧库中不再存在的材料行也会移除，避免 XML 与总表不一致。核对 `table_changes` 的新行数和被替换行数。

本机 `dndt_constants.dat` 第一行为 `Version#3`。`dndtcalc.seq` 会检查版本（原文件第 172–198 行）；辅助脚本保留版本头、列顺序和换行格式。`catalog_tables/` 的单库增量不能直接覆盖软件的完整总表。

两个总表的公式标记不同，辅助脚本按本机原表与 `dndtcalc.seq` 第 380–406 行对应：

| 模型 | CatalogFull 的 Equation_type | 热光表 Formula |
|---|---|---|
| Laurent | SCHT | lau |
| Glass Manufacturer Laurent | SCH2 | gml |
| Glass Manufacturer Sellmeier | SSHT | gms |
| Herzberger | HRZG | hrz |

旧 MATLAB 输出的 GMS / HERZ 不能直接当作两张总表的通用公式代码。

辅助脚本当前为六系数的可见光材料生成目录：nd / Vd 用系数计算，DPF 暂为 0。仅红外有效的材料能交付 XML，但当前不能用这份辅助脚本伪造可见光 nd / Vd 来写玻璃专家目录。不同热学类别无法等价成单组 TD 时先明确解决，不静默抛弃。

## 安装与备份

用户明确要求安装 / 更新时执行下面步骤；若当前仅要求生成文件，交付准备目录并说明尚未安装。查看 manifest 的四个目标路径和被替换行数后，在已授权范围内继续。若用户正运行会占用相关文件的分析，先保存工作并择空闲时执行；不会强制关闭现有 CODE V 或改动当前镜头。

新转换直接安装可使用 `convert ... --output CUSTOM.xml --codev-root <目标目录> --install-codev --json`，它复用同一 prepare / apply / verify 流程，返回 `codev_installation` 和备份位置。人工窗口默认安装筛选后的全部材料，可勾选“仅安装选中材料”，无需选择输出位置或包目录。仅导出仍使用原按钮。

```powershell
python -X utf8 $glassTool codev apply 'D:\glass\CUSTOM_install' --json
python -X utf8 $glassTool codev verify 'D:\glass\CUSTOM_install' --json
```

`apply` 先把将覆盖的现有文件复制到准备目录下 `backup-时间戳/`，再安装四个文件，写出 `install-report.json`。若准备后本机任一目标文件发生变化，脚本要求重新 prepare，避免使用旧的整表快照覆盖后来合入的其他库。备份位置随结果返回。

如果安装因权限、占用或其他错误中止，先用 verify 查清已同步和未同步项；使用本次备份还原已覆盖项或解决原因后重新 prepare。错误发生时不声称所有文件已更新。

## 卸载指定库

查看库用 `codev list --codev-root <目标目录> --json`。人工在侧栏“玻璃库管理 → CODE V 库管理”中选安装位置，列表显示 `glass/` 中的 XML、材料数量与数据提示，双击可载入筛选工作区；管理页上方可安装已有完整导出包。

用户明确要求移除某个库时，核对库名和目标 CODE V 目录后执行；人工在同一管理页选中一行，点底部“卸载选中的库”，无需安装清单。CODE V 与 Zemax 管理页的目录、列表和选中库操作位置一致。

```powershell
python -X utf8 $glassTool codev uninstall CUSTOM --codev-root 'C:\CODEV202503' --json
```

工具读取当前两张总表，先备份将修改的文件，再移除 `glass/CUSTOM.xml`、存在的 `macro/custom.dat` 和两张总表中 Catalog 为 CUSTOM 的行。其他库、表头与 `Version#3` 保留；原始 AGF、导出包和安装备份保留。卸载整个指定库，不是回退到某次安装前的版本。

默认备份及 `uninstall-report.json` 位于目标目录的 `catalog_backups/uninstall_<库名>_<时间>/`，也可加 `--backup <新目录>`。核对返回的 `files_removed`、两张表的 `removed_catalog_rows` 和备份位置。卸载按当前表移除该库，不能直接还原安装前的整张总表，否则会抹掉后来安装的其他库。完成后在 CODE V 中查询确认移除；`application_verified` 仍需软件查询证据。

## 验证新库在软件内可查询

`files_synced` 仅证明文件匹配，`application_verified` 仍为 false。软件查询另存验证证据。

在目标 CODE V 实例中做只读目录查询（先确认空闲；有现有镜头时不通过 GLA 改其材料）：

```text
GLD
GLI CUSTOM
GPR CUSTOM <本库一个实际材料名>
GO
```

核对查询结果无错误、库名正确、材料数量与 manifest 一致，并至少核对一种材料的折射率和有效波段。需要的热光 / 透过率数据也按实际用途抽查。若软件仍使用旧目录，保存工作后重开 CODE V 再查；失败时定位实际文件与加载行为，不编造刷新命令。

查询来源：本机 `help/lens_system/HIDD_GLASS_CATALOGS.html` 说明 GLI / GPR 的 catalog 与 glass 参数。

要让输入裸材料名也能搜索到新库，还需核对搜索顺序：`?CSO` 或 Tools → Preferences → General 的 Glass Catalog Search Order。保留原列表，按用户需要加入新库；`CSO CUSTOM` 会把搜索范围缩成仅 CUSTOM，不能把它当成“追加目录”。显式指定 `<材料名>_<库名>` 是另一种定位方式。依据本机 `help/setup/imm.10.09.html` 与 `imm.10.21.html`。

完成报告包含：新库路径、两个总表同步情况、备份路径、文件核对结果、软件查询证据；未完成软件查询就明确标为待验证。

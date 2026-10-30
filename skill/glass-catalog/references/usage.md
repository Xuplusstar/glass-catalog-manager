# 调用示例与数据边界

以下 PowerShell 示例只创建输出文件。`$glassTool` 是 skill 入口路径。

```powershell
$glassTool = '<本技能目录>\scripts\glass_catalog.py'
python -X utf8 $glassTool inspect 'D:\glass\vendor.AGF' --json
python -X utf8 $glassTool inspect 'D:\glass\vendor.AGF' --nd-min 1.6 --nd-max 1.8 --vd-min 30 --vd-max 65 --json
python -X utf8 $glassTool convert 'D:\glass\vendor.AGF' --nd-min 1.6 --output 'D:\glass\CUSTOM.xml' --codev-root 'C:\CODEV202503' --json
python -X utf8 $glassTool convert 'C:\CODEV202503\glass\SCHOTT.xml' --names NBK7 --transmission-thickness 25 --output 'D:\glass\CUSTOM.AGF' --json
python -X utf8 $glassTool convert 'D:\glass\a.AGF' 'D:\glass\b.xml' --prefix-source --output 'D:\glass\MERGED.xml' --codev-root 'C:\CODEV202503' --json
python -X utf8 $glassTool convert --help
```

- 原生供应状态用 `--supply-status agf:0 agf:1`（Zemax 标准/优选）或 `--supply-status codev:10 codev:11 codev:12`（CODE V 最高/较高/低熔炼频率）。多个来源可组合，同组 OR，与其他条件 AND。JSON 的 `supply_status` 和 `supply_label` 保留来源含义；CODE V 8 为请询厂家，不能称为特殊材料。旧 `--status` / JSON status 仅为 AGF 近似映射兼容，不用于 XML 精确选材。
- Zemax NM 的 status 与最后一项 melt freq 是两个独立字段。`--melt-frequency 1 2 3` 选择 AGF 频率等级，1 很频繁、5 很少；设置后排除无此 AGF 等级的材料。CODE V 频率分类直接用对应的原生供应码选择，不按 AGF status 推断。
- 厂家的 MA/A/B/C/D 按厂家表核对，不能自动从 AGF 1～5 或 CODE V 原码还原。`inspect/convert --supplier-table <CSV/TSV/XLSX> --supplier CDGM --supplier-grade MA A B` 按表分级多选；已知厂家可从表文件名识别，旧 XLS 需另存为 XLSX/CSV。表头包含 Glass/牌号 和 Melt Frequency/生产频率/熔炼频率 两列；CSV 支持 UTF-8 和 GB18030，TSV 用制表符。
- 厂家表只匹配该厂家前缀的原库，例如 CDGM、CDGM202509、CDGM-ZEMAX202509；自定义库名不会自动推断厂家，宜在原厂家库上匹配再筛选组合。不修改源文件或覆盖软件原码，只给导出报告附加厂家来源。忽略牌号大小写、空格、连字符，其他差异不猜测。同一牌号分级冲突会提示；未匹配牌号不参加分级筛选。核对文件名解析的年月版本（没有则未标注）、SHA256、matched/input_count；旧版 CODE V 搭配新版表只表示该表的生产频率，不声称二者同版本。
- 成都光明厂家表定义 MA 常年在库、A 每年两次以上、B 每年一次、C 每 1～2 年一次、D 两年以上一次；其他厂家按其原说明解释。实测 CDGM 同版 AGF 有多处 C/D 共用软件等级 4；需要厂家字母却无对应表时，说明缺少数据，不用固定逆映射替代。人工版在“导出设置”选择表，回到筛选页选择“厂家分级”；关闭再打开会重新读取记住的本地表。
- 内透过率条件示例：`--it-at-nm 550 --it-thickness-mm 10 --it-min 95 --it-max 100`，单位为 nm、mm、百分数。范围内线性波长插值后按指数换算厚度；不外推，缺数据在设阈值时排除。inspect 返回筛选计算值。
- AGF 的 nd / Vd 筛选使用原 NM 参考数据；XML 用支持模型计算 C / d / F 线。不能计算或可见谱线超出有效波段时是未知值，会被数值范围条件排除。
- 名称变换必须查看报告。CODE V 兼容处理会去掉连字符，可能产生冲突；`--prefix-source` 保留来源前缀，但同库两个名字仍可能冲突。
- `--json` 成功返回 `ok: true`，失败返回 `ok: false`、原因及退出码 2；将工具错误视为待解决，不能凭输出路径存在就称作本次成功。
- 现阶段跨格式不是全属性无损。原始库与输出报告一起保留；热光参考温度、CTE 温区、未映射厂家属性按工具 README 的范围核对。
- AGF → XML 对 `1 < IT ≤ 1.001` 默认自动按 100% 导出，用户已确认这类轻微超限无需逐次询问；`transmission_corrections` 逐点保留原值、导出值、波长、厚度、源行号和 `automatic_cap_at_one` 策略。源 AGF、原生 AGF 导出保持原值。`--strict-transmission` 可关闭自动处理；更大超限需明确解决，接受全部按 100% 写出时可用 `--cap-transmission-at-one`。
- CODE V 默认完整交付：`convert --codev-root <安装目录>` 生成 XML 及材料、热光目录包，JSON 的 `codev_bundle` 给出位置；`--bundle` 可指定新目录。人工窗口默认勾选同步生成两张表，另有备份安装按钮。生成包和实际安装是两个动作；只有 XML 的请求可不带 `--codev-root`。

用户要求直接安装时，在上述转换命令加 `--install-codev`，工具自动建包、备份、安装和核对四个文件，结果在 `codev_installation`。人工窗口对应“一键转换并安装到 CODE V”；默认安装当前筛选结果，可勾选只安装选中材料。卸载入口从已安装库列表选择，AI 则调用：

```powershell
python -X utf8 $glassTool codev uninstall CUSTOM --codev-root 'C:\CODEV202503' --json
```

卸载默认备份到目标 CODE V 的 `catalog_backups/uninstall_<库名>_<时间>/`；可用 `--backup <新目录>` 指定。删除该库 XML / 单库 DAT，并按库名清理两张当前总表；结果包含 `removed_catalog_rows` 和备份报告。安装与卸载均须用户已授权操作该库。

程序根目录由 config 的 tool_root 指定；独立分享版用 executable / gui_executable 的相对路径，直接运行 EXE 无需 Python。Zemax 管理见 [zemax-management.md](zemax-management.md)，Glass Expert DAT 见 [glass-expert.md](glass-expert.md)。原 MATLAB 文件保留作历史兼容；新功能使用同一 Python / 独立程序核心。

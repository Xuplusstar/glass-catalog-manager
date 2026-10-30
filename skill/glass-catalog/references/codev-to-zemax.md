# CODE V → Zemax 反向转换

输入 CODE V 原生 Catalog XML，输出 Zemax AGF。整库、按牌号和按参数筛选共用这条路径；不需要 MATLAB。导出新 AGF 与向 Zemax 安装库是两个不同任务范围。

## 检查并选择材料

```powershell
$glassTool = '<本技能目录>\scripts\glass_catalog.py'
python -X utf8 $glassTool inspect 'C:\CODEV202503\glass\SCHOTT.xml' --names NBK7 --json
```

检查 `formula`、`cross_format_supported`、`issues`、`wavelength_range_um`，以及 `transmission_thicknesses_mm` 和 `transmission_point_count`。按 nd / Vd、密度筛选或多来源组合时先确认实际保留的材料与数量。

仅有 CatalogFull.dat 等宏总表时，先取得对应 XML；总表没有完整的色散、透过率和热光记录，不能保证反向还原。

## 输出 AGF

```powershell
# 按名称反向转换；NBK7 明确取 25 mm 透过率曲线
python -X utf8 $glassTool convert 'C:\CODEV202503\glass\SCHOTT.xml' --names NBK7 --transmission-thickness 25 --output 'D:\glass\SCHOTT_CUSTOM.AGF' --json

# 按参数筛选后创建 Zemax 新库，缺少支持或厚度选择时按具体错误解决
python -X utf8 $glassTool convert 'D:\glass\MYCODEV.xml' --nd-min 1.6 --nd-max 1.8 --vd-min 30 --vd-max 65 --output 'D:\glass\MY_ZEMAX.AGF' --json
```

多厚度曲线先确认用户要保留哪组；同一命令的厚度参数作用于所有 XML 材料。各材料没有共同厚度时按厚度分组分别转换，或先与用户确定逐材料策略。单厚度数据可直接转换。超过 100 个透过率点时明确处理策略，不自行删点。

支持的直接映射：

| CODE V 色散模型 | Zemax 公式 |
|---|---|
| Laurent | 1 Schott |
| Glass Manufacturer Sellmeier | 2 Sellmeier 1 |
| Herzberger | 3 Herzberger |
| 六系数 Glass Manufacturer Laurent | 1 Schott |

保留有效色散系数；波长 nm → μm，厚度保持 mm；CTE 从 CODE V 的 10e-6 / 10e-7 标记转成 AGF ppm/K。原始温区可能不同，按报告核对。可表达的 TD 常数写入 AGF TD；只有 dn/dT 温区表而无常数，或不同类别的常数冲突时需先解决，当前程序会明确报出。

玻璃名称默认沿用 CODE V 名称，例如 NBK7；不凭猜测补回 N-BK7 等厂家写法。六位纯数字名称在 Zemax 会被理解为 MIL 模型，按提示加来源前缀。价格、日期、替代材料、厂家扩展属性等附加信息不保证能映射，交付时保留原 XML 和报告。

## 核对输出与交付

复读 AGF，核对材料数、牌号、公式、色散系数、有效波段、选定厚度的透过率，以及可映射的热光常数。至少在有效波段内抽取波长比较转换前后 n(λ)；仅红外材料不外推到可见谱线来强造 nd / Vd。

交付 `.AGF` 与 `.AGF.report.json`，明确所选厚度和损失项。人工窗口同样支持：导入 CODE V XML → 筛选 → 选择“Zemax AGF”→ 选择厚度 → 导出。

用户进一步要求装入 Zemax 时，先确认实际 Glasscat 目录（config 记录本机路径）。备份同名 AGF 后安装；BGF 是软件自动生成的缓存，不手工生成。随后在对应镜头的 System Explorer → Material Catalogs 加入库名，并用材料目录查看器或 ZOS-API 核对牌号与折射率。未完成软件内查询时，交付状态只写“AGF 已生成 / 文件已安装，软件识别待验证”。

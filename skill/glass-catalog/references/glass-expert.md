# CODE V Glass Expert 候选清单

输出 TAB 分隔的 `Catalog` 与 `Glass` 两列，CRLF 换行和 ASCII 名称。依据 CODE V `help/optimization/Opt_9_ExpertTools.10.03.html` 与 `.10.06.html`：用户库与 macro/SCHOTT.DAT 格式相同，只要求前两列；SPECIAL 材料用 SPECIAL，私有材料用 PRV。用户本机 `6Macros_CodeV/Glass Expert/PLASTIC.dat`、`CDGM_H.dat` 等也是两列清单。

清单引用已存在于 CODE V 的材料，不携带完整色散或热光数据。它也不是 `USER.dat` 中包含 Surfaces、Catalogs Used、User Catalog 等项的优化输入配置，不替用户编造优化面号。

DAT 只从目标 CODE V 已安装的 XML 库选材。先按 config 的 `codev_root` 列出 `glass/*.xml`，从中选用户需要的库；不使用外部 XML 副本或 AGF 直接导出。新材料先按 XML 转换安装流程交付，只有用户授权安装时才写入软件目录，再从已安装位置生成 DAT。

调用统一转换入口，输出扩展名 `.dat`，`--codev-root` 必填，可传入多个已安装 XML：

```text
convert <CODEV目录>/glass/CDGM.xml --supply-status codev:10 codev:11 codev:12 --output CANDIDATES.dat --codev-root <CODEV目录> --json
```

沿用已安装 XML 的库名和牌号。跨库可组合，允许不同库同名；同一库同牌号重复会报错。无需前缀、安装或 bundle 参数，清单名称只决定输出文件名。不要求材料能转 AGF 或具有可见光 nd / Vd，红外材料也能列入。`--expert-reference source` 可省略；`auto` 仅作 source 的兼容别名，已取消 new 和自动配套 XML。

供应状态按 CODE V 原生 Availability 筛选，含义与厂家及 AGF status 不同；例如 10/11/12 是不同熔炼频率，8 是请询厂家。使用 inspect 的 supply_label / supply_status 核对，不用旧近似 status 将它们归为 Special。厂家 MA/A/B 字母需另有同版对照，不能仅凭 XML 推断。

导出核心检查来源确属目标 `glass/`，并复读实际安装文件核对库名和牌号；库已卸载或材料已改名会停止导出，不静默排除。核对报告 `reference_catalogs`、`name_map`、`reference_verification`（`checked: true`、`missing: []`），交付 DAT 和报告。此流程不修改已安装 XML 或两张总表；文件核对不等于已完成软件内优化验证。

人工操作：选择“Glass Expert DAT”→ 核对“导出设置”中的 CODE V 位置 →“选择已安装库”→ 勾选一个或多个库并载入 → 筛选 → 填清单名称 →“导出 DAT 清单”（全部筛选结果）或“仅导出选中 · DAT”（Ctrl / Shift 选中行）。DAT 与 AGF/XML 转换保留各自来源；更换 CODE V 位置后重新选择库。

CODE V 的 Glass Expert 对话框 / 提示中选择 USER，再将此文件作为 User Catalog；若用优化输入配置，其 `Catalogs Used` 为 USER、`User Catalog` 为此 DAT。使用原有的 AUTO / PERF 配置，不自动启动优化或改当前镜头。

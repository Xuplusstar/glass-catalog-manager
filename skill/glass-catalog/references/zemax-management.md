# Zemax Glasscat 文件管理

从 config 或用户指定路径确认 Zemax 实际使用的 Glasscat，不能把本机示例路径套到其他电脑。统一入口也可用分享包的 GlassCatalogCLI.exe 直接执行：

```text
zemax list --glasscat <目录> --json
zemax install CUSTOM.AGF --glasscat <目录> --json
zemax backup CUSTOM --glasscat <目录> --json
zemax uninstall CUSTOM --glasscat <目录> --json
zemax restore <包含backup.json的备份目录> --glasscat <目录> --json
```

`list` 给库名、材料数、路径、BGF 缓存状态与读取提示。`install` 只接受 AGF，CODE V XML 先 `convert` 输出 AGF；可用 `--catalog-name` 指定安装文件名。保留源文件，更新前备份目标同名 AGF 和 BGF，再写入 AGF、移除旧 BGF 缓存，核对字节一致。BGF 由 Zemax 自动创建。

`backup` 单独备份当前库。`uninstall` 备份后移除选定库的 AGF 与 BGF，不改其他库。`restore` 校验 backup.json 中 AGF 哈希，恢复前再备份当前同名库；不恢复旧缓存，仍由 Zemax 重建。默认备份位于 Glasscat/catalog_backups/，结果返回 backup 与文件处理状态。

人工界面“Zemax 库管理”可查看、双击载入筛选工作区、安装已有 AGF、备份、卸载及选择备份恢复。导出 AGF 时，底部“转换并安装到 Zemax”使用同一目录与逻辑，可勾选仅安装选中材料。

文件安装后，在目标镜头 System Explorer → Material Catalogs 加入库名，再用材料查看器或 ZOS-API 查询材料与折射率。仅文件处理时 `application_verified` 为 false；未做软件查询就说明识别待验证。用户不允许操控桌面时，保留文件证据并说明该边界，不启动软件交互。

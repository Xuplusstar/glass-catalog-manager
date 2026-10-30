# 项目维护

- 人工窗口、CLI 与 skill 共用根目录的转换和库管理核心，不另建一套映射。
- 续接本机任务时读取 `项目恢复记录.md`（若存在），以实际代码与验证结果核对进度。该记录只保留本地。
- 测试：`python -X utf8 -m unittest discover -s tests -v`，Qt 使用 `QT_QPA_PLATFORM=offscreen`。安装卸载测试只用临时目录。
- 构建与独立包验收见 README。不要把原始厂家库、厂家表、个人设置、历史输出或软件原总表提交到 Git。
- 本机 `skill/glass-catalog` 是指向统一技能正本的 Junction；修改前遵守技能正本目录的 AGENTS.md。公开项目仅分发技能内容，个人 config.json 排除。

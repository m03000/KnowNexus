# Contributing to KnowNexus

感谢你参与 KnowNexus。提交较大的功能或数据结构调整前，请先创建 Issue 说明目标和范围。

## 开发流程

1. Fork 仓库并从 `main` 创建分支。
2. 不要提交 `.env`、数据库、日志、模型、用户文档或构建产物。
3. 后端变更运行 `python -m pytest`；前端变更运行 `npm run lint` 和 `npm run build`。
4. Pull Request 中说明变更原因、验证方法、界面截图以及是否涉及数据迁移。

## 提交建议

- 一个 Pull Request 聚焦一个问题。
- 新功能尽量带测试；修复缺陷时描述复现步骤。
- 不要在示例配置和日志中包含真实密钥、本机用户名或私人文件路径。

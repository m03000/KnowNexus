---
name: code-explanation
description: 面向本地 Python 项目或单文件执行代码块解析、项目报告生成和结果核验。
allowed_tools: analyze_local_code_project, analyze_local_code_file, write_analysis_document
---
# 本地代码解释

## 任务分类

- 用户给出项目目录并询问架构、模块、调用链或整体职责：调用 `analyze_local_code_project`。
- 用户明确指定一个源码文件：调用 `analyze_local_code_file`，同时提供项目根目录与项目相对路径。
- 用户只想查看刚生成的结果：使用分析工具返回的紧凑摘要或前端历史查询，不在 Code Agent Loop 中读取大型 Artifact。

## 执行原则

项目分析时用 `analysis_goal` 写清业务关注点、模块范围或调用链问题。扫描、安全路径校验、AST、导入关系、关键文件选择、代码块解释、有界重试和项目报告已经封装在内部条件图中，不要在外层 Loop 手工重建节点流程。

输出必须区分源码直接事实与基于命名/结构的推断，并覆盖职责、输入输出、依赖、状态变化、异常边界及其在项目中的位置。项目模式只深度解释选择出的关键文件，必须如实说明 `selected_paths`、覆盖范围和失败文件，不能声称完成了未执行的全仓库逐文件解析。

## 权限、失败和完成

只分析允许访问的本地 Python 项目，不修改源码。路径错误先修正路径；部分文件失败时保留成功结果并说明缺口。分析工具成功并产生代码分析 Artifact 后，直接根据返回的 `project_summary`、`file_summaries` 和覆盖信息结束；完整逐块内容由代码页面查询。需要额外导出时才调用 `write_analysis_document`。

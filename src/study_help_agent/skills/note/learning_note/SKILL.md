---
name: learning-note
description: 学习笔记 Agent 的通用质量原则、工具选择规则和最终验收要求。
allowed_tools: merge_text_files, build_learning_note, build_single_learning_note, build_learning_notes_batch, read_artifact, write_analysis_document
---
# 学习笔记通用规范

## 输入分类与成本控制

先判断输入是直接文本、单个资源、多个本地文本文件、多个独立资源，还是已有笔记重组，再加载更具体的场景 Skill。普通文本、Markdown 或合并后的干净正文进入 `build_learning_note`；单资源使用 `build_single_learning_note`；多个独立资源使用一次 `build_learning_notes_batch`。不要在外层 Loop 手工重演高层工具已经封装的获取、提取、清洗和生成步骤。

## 内容与结构要求

`build_learning_note` 会审查局部内容、整体结构和材料规模，再动态规划一篇或多篇笔记。原文有标题不代表整体结构合理：合理结构可以复用和微调，不合理结构应重新规划、合并、拆分、排序和命名。目标是把材料转化为专业、连贯、可复习的笔记，不是摘要，也不是逐句复制。

最大限度保留有知识价值的事实、解释、示例、代码、数据、操作步骤、约束、反例和来源观点；允许删除纯噪声、机械重复和无意义寒暄。不得补写来源没有支持的专业事实。

## Artifact 与结果处理

大内容通过 Artifact ID 在工具间传递。调用后检查 `partial`、warnings、生成的笔记数量及质量审查结果；超长材料被拆成多篇时保持来源元数据和主题边界。最终笔记由底层自动保存并进入索引，展示、查询和删除由前端 API 管理。知识点或片段提取必须以最终笔记为来源。

## 完成标准

至少产生 `learning_note_bundle`，标题和章节符合内容，重要信息覆盖充分，来源元数据可追溯，并且没有未说明的部分失败。

工具完成不等于用户任务完成。单资源任务在笔记产物生成后还要用一次 `finish` 形成最终说明；多资源任务必须逐项核对来源和笔记完成清单。最终回答应利用 `learning_note_bundle` 的标题、内容简介和核心知识点，按来源概括材料内容并提炼重点，不能只返回数量或保存状态。

---
name: multi-document-note
description: 将多个本地 txt、Markdown 或 docx 文本文件按顺序合成为一份笔记材料。
allowed_tools: merge_text_files, build_learning_note, read_artifact
---
# 多文档合并笔记

## 适用条件

用户明确希望把 2～50 个 `.txt`、`.md`、`.markdown` 或 `.docx` 本地文本文件合成同一份笔记。图片、PDF、音视频和外部链接不属于本流程，应改用批量资源流程。

## 标准步骤

1. 确认全部绝对路径、文件数量、合并顺序和最终主题。路径由 Main Agent 消歧后，应按原顺序传入。
2. 调用 `merge_text_files`。它不使用 LLM，只提取正文、保留文件边界、追加文件名/格式/原路径/字符数等元数据，并确定性拼接。
3. 检查 `document_count`、`sources`、字符总数和 warning，确认没有漏文件或顺序错误。
4. 将 `merged_text_content` Artifact ID 交给 `build_learning_note`。由内部图审查跨文件整体结构、消除重复并动态决定生成一篇还是多篇。

## 边界与失败

不要在 Agent 上下文里手工复制多份全文。某个文件格式错误、为空或无权限时，先处理该问题，不要悄悄忽略。合并只代表形成共同输入，不代表必须保留原文件章节顺序；最终结构由内容关系决定。

## 完成标准

所有指定文件都出现在来源元数据中，顺序正确，最终笔记覆盖各来源的有效知识并明确处理重复内容。

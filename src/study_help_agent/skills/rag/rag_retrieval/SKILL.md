---
name: rag-retrieval
description: 从个人知识库执行混合检索、证据审查，并按需生成带来源的回答。
allowed_tools: retrieve_personal_knowledge, answer_from_retrieved_knowledge, read_artifact
---
# 个人知识库检索与回答

## 何时检索

只有用户问题需要个人笔记、项目知识、长期记忆或明确来源依据时才检索。普通聊天、仅依靠当前输入即可完成的改写和无需外部证据的推理不应强制调用 RAG。

## 检索流程

1. 将问题整理为保留原意、包含关键实体和限制条件的检索目标。
2. 调用 `retrieve_personal_knowledge`。内部图已经负责查询改写、按知识库类型路由、BM25/FTS 与向量或图召回、RRF 融合、重排、证据审查和一次有界重试。
3. 检查 `status`、`warnings`、`review_summary`、命中文档和来源，不在外层重复构建底层检索链。
4. 需要查看完整检索上下文时读取 `retrieved_context` Artifact。
5. 用户需要最终答案时，把原问题与检索 Artifact ID 交给 `answer_from_retrieved_knowledge`；只要检索列表时无需生成回答。

## 证据边界

回答必须区分知识库证据和推断，引用只能指向检索结果允许的 Chunk。不得用模型常识填补知识库中不存在的事实。证据不足时应明确说明缺少什么，而不是编造结论。

## 完成标准

检索型请求应返回可追溯命中及来源；回答型请求应产生通过引用白名单校验的 grounded answer。部分失败需保留有效证据并展示 warning。

---
name: multi-agent-request
description: 处理跨代码解析、学习笔记与个人知识库检索的复合目标，并决定委派顺序。
allowed_tools: delegate_code_agent, delegate_note_agent, delegate_rag_agent, read_artifact, read_local_text_file
---
# 复合任务规划与委派

## 何时使用

当一个请求同时涉及两个以上领域，或者必须先取得一个领域的结果再交给另一个领域处理时使用。例如：解析本地项目后把报告整理成笔记，或检索知识库后结合用户材料生成学习内容。单纯聊天和单领域请求不需要加载本 Skill。

## 决策步骤

1. 把用户目标拆成具有明确输入、输出和验收条件的能力块。
2. 判断依赖关系：没有数据依赖的任务可以分别委派；后一步需要前一步 Artifact 时必须串行。
3. 本地项目或单文件解析委派 Code Agent；资料处理和笔记生成委派 Learning Agent；个人知识库证据检索委派 RAG Agent。
4. 大文本结果通过 Artifact ID 传递，路径和简短约束可直接写入委派目标。
5. 每次委派后检查状态、Artifact、warning 和 partial，再决定继续、修正参数或询问用户。

## 权限边界

Main Agent 负责理解、规划、委派和汇总，不直接执行代码解析、资源提取、笔记生成或底层检索。`read_local_text_file` 只用于核对短期记忆中的路径和少量文本，不能取代专业 Sub-Agent。

## 失败与完成

失败时先区分路径/权限、参数、证据不足、外部资源失败和模型失败；不得无条件重复同一调用。所有必要能力块达到用户验收目标后即可结束，不以“调用过全部 Agent”为完成标准。

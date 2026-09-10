"""代码解释 Agent 的 Prompt 模板和构造函数。"""

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from study_help_agent.capabilities.code_analysis.domain.source_analysis import (
    FileImportContext,
    ParsedCodeBlock,
)


FILE_CONTEXT_SYSTEM_PROMPT = """
你是项目结构分析专家。
请根据文件路径、导入关系以及文件中的代码符号，判断该文件在整个项目中的职责。

要求：
1. file_role 使用一句简洁中文描述。
2. function_roles 为函数、类、方法名称到职责的映射。
3. 不确定时给出保守描述，不要编造不存在的调用关系。

function_roles 必须直接返回 JSON 对象，
不能把 JSON 对象编码为字符串。

正确：
{
  "function_roles": {
    "main": "程序入口"
  }
}

错误：
{
  "function_roles": "{\"main\":\"程序入口\"}"
}
""".strip()


PROJECT_SUMMARY_SYSTEM_PROMPT = """
你是项目架构分析专家。

请根据当前选中关键文件的职责和依赖证据，生成项目解析报告。你看到的可能只是项目的有限范围，禁止把有限样本描述成完整仓库事实。

必须包含：
1. 当前分析范围与证据边界。
2. 项目的主要定位和功能。
3. 关键文件、主要模块或分层。
4. 已有证据支持的依赖关系与核心数据流。
5. 建议继续深挖但尚未验证的区域。

使用 Markdown 小标题，控制在 800 字以内。
不要编造输入信息中没有体现的外部系统。
""".strip()


BLOCK_EXPLANATION_SYSTEM_PROMPT = """
你是代码讲解专家。

请结合项目架构总览和文件职责，解释指定代码块在整个项目中的作用。

要求：
1. 说明代码块职责。
2. 说明关键逻辑和数据结构。
3. 函数或方法需要说明输入、输出和返回值。
4. 解释重要 Python 语法。
5. 不要逐行翻译，不要编造未出现在代码中的行为。
6. 根据项目、模块、文件相关内容分析代码块的综合定位，一句话即可。
7. 直接返回 Markdown 内容，不要使用代码围栏包裹全文。
""".strip()



def build_file_context_messages(
    *,
    relative_path: str,
    symbol_names: list[str],
    import_context: FileImportContext,
) -> list[BaseMessage]:
    """构造文件职责分析消息。"""

    human_content = f"""
文件路径：
{relative_path}

文件中的函数、类和方法：
{", ".join(symbol_names) or "无"}

导入的项目内部文件：
{", ".join(import_context.internal_imports) or "无"}

导入的外部包：
{", ".join(import_context.external_imports) or "无"}

引用当前文件的项目文件：
{", ".join(import_context.imported_by) or "无"}
""".strip()

    return [
        SystemMessage(
            content=FILE_CONTEXT_SYSTEM_PROMPT
        ),
        HumanMessage(
            content=human_content
        ),
    ]


def build_project_summary_messages(
    *,
    file_roles: dict[str, str],
    dependencies: dict[str, list[str]] | None = None,
) -> list[BaseMessage]:
    """用文件职责和项目内依赖证据构造项目报告消息。"""

    lines = [
        f"- {file_path}: {role}"
        for file_path, role
        in sorted(file_roles.items())
    ]

    dependency_lines = [
        f"- {path} -> {', '.join(targets) or '无已识别项目内依赖'}"
        for path, targets in sorted((dependencies or {}).items())
    ]
    human_content = (
        "本次选中文件职责：\n"
        + "\n".join(lines)
        + "\n\n项目内导入证据：\n"
        + ("\n".join(dependency_lines) or "无")
    )

    return [
        SystemMessage(
            content=(
                PROJECT_SUMMARY_SYSTEM_PROMPT
            )
        ),
        HumanMessage(
            content=human_content
        ),
    ]


def build_block_explanation_messages(
    *,
    project_summary: str,
    file_role: str,
    function_role: str,
    block: ParsedCodeBlock,
) -> list[BaseMessage]:
    """构造代码块解释消息。"""
    name = {
        "function": "函数",
        "method": "方法",
        "class": "类",
        "block": "顶层代码块",
        "module": "模块",
    }
    type_name = name.get(block.block_type.value, "代码块")

    human_content = f"""
项目架构总览：
{project_summary or "暂无"}
            
当前文件职责：
{file_role or "普通代码文件"}

当前代码块职责：
{function_role or "暂无预分析结果，请根据代码谨慎判断"}
            
代码块：
{type_name} {block.name}
第 {block.line_start}-{block.line_end} 行
            
源代码：
```python
{block.code}
```
""".strip()
    return [
        SystemMessage(
            content=(
                BLOCK_EXPLANATION_SYSTEM_PROMPT
            )
        ),
        HumanMessage(
            content=human_content
        ),
    ]


def build_block_batch_explanation_messages(
    *,
    project_summary: str,
    file_role: str,
    blocks: list[dict[str, str]],
) -> list[BaseMessage]:
    """一次提交多个代码块，并要求模型按稳定 block_id 分别返回解释。"""

    sections = []
    for item in blocks:
        sections.append(
            "\n".join((
                f"block_id: {item['block_id']}",
                f"代码块职责预判: {item['function_role'] or '暂无'}",
                f"代码块位置: {item['location']}",
                "源代码:",
                "```python",
                item["code"],
                "```",
            ))
        )
    return [
        SystemMessage(content=(
            BLOCK_EXPLANATION_SYSTEM_PROMPT
            + "\n你将收到多个代码块。必须为每个 block_id 返回一条独立解释，"
              "不得遗漏、合并或虚构 block_id。"
        )),
        HumanMessage(content=(
            f"项目架构总览：\n{project_summary or '暂无'}\n\n"
            f"当前文件职责：\n{file_role or '普通代码文件'}\n\n"
            "待解释代码块：\n\n" + "\n\n---\n\n".join(sections)
        )),
    ]

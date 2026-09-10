"""笔记规划图节点：规模分析、内容审查、动态规划、多笔记生成和有限修订。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from study_help_agent.capabilities.learning_notes.llm.note_builder import (
    LearningNoteBuilderOperations,
)
from study_help_agent.observability.context import map_with_trace

from .state import LearningNoteBuilderState


class LearningNoteBuilderNodes:
    """实现来源可追踪、内容规模自适应的专业笔记生成闭环。"""

    CHUNK_TARGET_CHARACTERS = 10_000
    MAX_SOURCE_CHARACTERS = 400_000
    MAX_CHUNKS = 48
    MAX_NOTE_SOURCE_CHARACTERS = 24_000
    MAX_NOTES = 12
    MAX_REVISIONS = 1

    def __init__(
        self,
        *,
        operations: LearningNoteBuilderOperations,
        max_parallelism: int = 4,
    ) -> None:
        self._operations = operations
        self._max_parallelism = max(1, max_parallelism)

    @staticmethod
    def _light_clean(text: str) -> str:
        """只统一换行、行尾空白和连续空行，不删除任何语义内容。"""

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = []
        previous_blank = False
        for raw_line in normalized.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                if lines and not previous_blank:
                    lines.append("")
                previous_blank = True
            else:
                lines.append(line)
                previous_blank = False
        return "\n".join(lines).strip()

    @classmethod
    def _split_long_unit(cls, unit: str) -> list[str]:
        """超长段落优先在换行或句末附近切开，最后才退化到字符边界。"""

        result: list[str] = []
        remaining = unit
        while len(remaining) > cls.CHUNK_TARGET_CHARACTERS:
            target = cls.CHUNK_TARGET_CHARACTERS
            lower = int(target * 0.65)
            window = remaining[lower:target]
            candidates = [window.rfind(mark) for mark in ("\n", "。", "！", "？", ". ")]
            relative = max(candidates)
            cut = lower + relative + 1 if relative >= 0 else target
            result.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            result.append(remaining)
        return result

    @classmethod
    def _build_chunks(cls, text: str) -> list[dict[str, Any]]:
        """按标题和段落语义边界打包为模型可审查的稳定来源块。"""

        paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
        units: list[tuple[str, str]] = []
        current_heading = ""
        for paragraph in paragraphs:
            heading_match = re.match(r"^#{1,6}\s+(.+)$", paragraph.splitlines()[0])
            if heading_match:
                current_heading = heading_match.group(1).strip()
            for part in cls._split_long_unit(paragraph):
                units.append((current_heading, part))

        chunks: list[dict[str, Any]] = []
        parts: list[str] = []
        headings: list[str] = []
        size = 0

        def flush() -> None:
            nonlocal parts, headings, size
            if not parts:
                return
            chunk_id = f"chunk_{len(chunks) + 1:03d}"
            chunk_text = "\n\n".join(parts)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "heading": " / ".join(dict.fromkeys(item for item in headings if item)),
                    "text": chunk_text,
                    "character_count": len(chunk_text),
                    "estimated_tokens": max(1, len(chunk_text) // 2),
                }
            )
            parts, headings, size = [], [], 0

        for heading, unit in units:
            addition = len(unit) + (2 if parts else 0)
            if parts and size + addition > cls.CHUNK_TARGET_CHARACTERS:
                flush()
            parts.append(unit)
            if heading:
                headings.append(heading)
            size += addition
        flush()
        return chunks

    def prepare(self, state: LearningNoteBuilderState) -> dict:
        """校验材料、估算规模并在任何 LLM 调用前完成稳定语义切块。"""

        original = state["input_text"].strip()
        if not original:
            raise ValueError("学习笔记输入不能为空")
        cleaned = self._light_clean(original)
        if not cleaned:
            raise ValueError("学习笔记输入清洗后没有有效内容")
        if len(cleaned) > self.MAX_SOURCE_CHARACTERS:
            raise ValueError(
                f"单次笔记规划最多处理 {self.MAX_SOURCE_CHARACTERS} 字符，请先按资源拆分"
            )
        chunks = self._build_chunks(cleaned)
        if not chunks or len(chunks) > self.MAX_CHUNKS:
            raise ValueError(
                f"材料产生 {len(chunks)} 个内容块，超过单次上限 {self.MAX_CHUNKS}"
            )
        if len(cleaned) <= 18_000 and len(chunks) <= 2:
            scale = "small"
        elif len(cleaned) <= 90_000 and len(chunks) <= 10:
            scale = "medium"
        else:
            scale = "large"
        return {
            "cleaned_text": cleaned,
            "chunks": chunks,
            "scale": scale,
            "revision_count": 0,
            "warnings": [],
        }

    def audit_content(self, state: LearningNoteBuilderState) -> dict:
        """并行审查内容块，形成带来源 ID 的全局信息清单。"""

        chunks = state["chunks"]
        with ThreadPoolExecutor(
            max_workers=min(self._max_parallelism, len(chunks))
        ) as executor:
            outputs = map_with_trace(
                executor,
                lambda chunk: self._operations.audit_chunk(chunk=chunk),
                chunks,
            )
        audits: list[dict[str, Any]] = []
        inventory: list[dict[str, Any]] = []
        for chunk, output in zip(chunks, outputs, strict=True):
            audit = output.model_dump()
            raw_items = audit.pop("information_items", [])[:30]
            normalized_items: list[dict[str, Any]] = []
            for index, item in enumerate(raw_items, start=1):
                local_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(item["item_id"]))
                item_id = f"{chunk['chunk_id']}:{local_id or f'i{index:03d}'}"
                normalized = {
                    **item,
                    "item_id": item_id,
                    "source_chunk_id": chunk["chunk_id"],
                }
                normalized_items.append(normalized)
                inventory.append(normalized)
            if not normalized_items:
                fallback = {
                    "item_id": f"{chunk['chunk_id']}:summary",
                    "category": "explanation",
                    "content": audit["summary"],
                    "importance": "required",
                    "source_excerpt": "",
                    "source_chunk_id": chunk["chunk_id"],
                }
                normalized_items.append(fallback)
                inventory.append(fallback)
            audits.append(
                {
                    **audit,
                    "chunk_id": chunk["chunk_id"],
                    "information_item_ids": [item["item_id"] for item in normalized_items],
                }
            )
        return {"chunk_audits": audits, "inventory": inventory}

    def plan_notes(self, state: LearningNoteBuilderState) -> dict:
        """进行全局结构审查，验证规划引用并约束单篇来源大小。"""

        output = self._operations.plan_notes(
            scale=state["scale"],
            chunks=state["chunks"],
            audits=state["chunk_audits"],
            inventory=state["inventory"],
        )
        plan = output.model_dump()
        plan["notes"] = self._normalize_plans(
            notes=plan.get("notes", []),
            chunks=state["chunks"],
            inventory=state["inventory"],
        )
        if len(plan["notes"]) > 1:
            plan["strategy"] = "multiple"
        return {"plan": plan}

    @staticmethod
    def route_after_audit(state: LearningNoteBuilderState) -> str:
        """短材料走确定性单篇计划，较长材料才调用 LLM 做全局结构规划。"""

        structure_is_coherent = all(
            audit.get("local_structure_quality") == "coherent"
            and not audit.get("structural_issues")
            for audit in state.get("chunk_audits", [])
        )
        top_level_headings = len(
            re.findall(r"(?m)^#\s+.+$", str(state.get("cleaned_text", "")))
        )
        return (
            "small"
            if (
                state.get("scale") == "small"
                and structure_is_coherent
                and top_level_headings <= 1
            )
            else "planned"
        )

    def plan_small_note(self, state: LearningNoteBuilderState) -> dict:
        """为短材料构造单篇计划，省去一次独立的 LLM 规划调用。"""

        chunks = state["chunks"]
        inventory = state["inventory"]
        topics = list(dict.fromkeys(
            topic
            for audit in state["chunk_audits"]
            for topic in audit.get("topics", [])
            if str(topic).strip()
        ))[:8]
        source_name = str(state.get("source_name") or "学习材料").strip()
        title = source_name.rsplit(".", 1)[0] or "学习笔记"
        required_ids = [
            item["item_id"] for item in inventory
            if item.get("importance") == "required"
        ]
        plan = {
            "bundle_title": title,
            "bundle_introduction": f"围绕《{title}》整理的专业学习笔记。",
            "strategy": "single",
            "rationale": "材料规模较小，使用确定性单篇结构以减少规划成本。",
            "source_structure_reasonable": True,
            "audit_summary": "短材料已完成内容审查，直接进入单篇生成。",
            "notes": [{
                "note_id": "note_001",
                "title": title,
                "purpose": "完整整理来源中的核心内容、解释、示例和约束。",
                "topics": topics,
                "sections": [{
                    "heading": "核心内容",
                    "purpose": "根据材料内容形成自然、专业的章节结构。",
                    "source_chunk_ids": [chunk["chunk_id"] for chunk in chunks],
                    "required_item_ids": required_ids,
                }],
            }],
        }
        return {"plan": plan}

    @classmethod
    def _normalize_plans(
        cls,
        *,
        notes: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """过滤虚构引用、补齐未分配信息，并把超预算规划拆成有界笔记。"""

        if not notes:
            raise ValueError("笔记规划没有生成任何笔记")
        chunk_map = {item["chunk_id"]: item for item in chunks}
        item_map = {item["item_id"]: item for item in inventory}
        normalized: list[dict[str, Any]] = []
        assigned: set[str] = set()
        for note in notes[:8]:
            sections: list[dict[str, Any]] = []
            for section in note.get("sections", []):
                chunk_ids = list(
                    dict.fromkeys(
                        item for item in section.get("source_chunk_ids", [])
                        if item in chunk_map
                    )
                )
                item_ids = list(
                    dict.fromkeys(
                        item for item in section.get("required_item_ids", [])
                        if item in item_map
                    )
                )
                chunk_ids.extend(
                    item_map[item_id]["source_chunk_id"]
                    for item_id in item_ids
                    if item_map[item_id]["source_chunk_id"] not in chunk_ids
                )
                assigned.update(item_ids)
                sections.append(
                    {
                        "heading": str(section.get("heading") or "核心内容"),
                        "purpose": str(section.get("purpose") or note.get("purpose") or ""),
                        "source_chunk_ids": chunk_ids,
                        "required_item_ids": item_ids,
                    }
                )
            if not sections:
                sections = [{
                    "heading": "核心内容",
                    "purpose": str(note.get("purpose") or "整理来源内容"),
                    "source_chunk_ids": list(chunk_map),
                    "required_item_ids": [],
                }]
            normalized.append({
                "title": str(note.get("title") or "学习笔记"),
                "purpose": str(note.get("purpose") or "形成专业学习内容"),
                "topics": list(dict.fromkeys(note.get("topics", []))),
                "sections": sections,
            })

        required = {
            item["item_id"] for item in inventory if item["importance"] == "required"
        }
        missing = sorted(required - assigned)
        if missing:
            first_section = normalized[0]["sections"][0]
            first_section["required_item_ids"].extend(missing)
            for item_id in missing:
                chunk_id = item_map[item_id]["source_chunk_id"]
                if chunk_id not in first_section["source_chunk_ids"]:
                    first_section["source_chunk_ids"].append(chunk_id)
        bounded: list[dict[str, Any]] = []
        for note in normalized:
            bounded.extend(cls._split_oversized_plan(note, chunk_map, item_map))
        if len(bounded) > cls.MAX_NOTES:
            raise ValueError(
                f"材料需要生成 {len(bounded)} 篇笔记，超过单次上限 {cls.MAX_NOTES}"
            )
        for index, note in enumerate(bounded, start=1):
            note["note_id"] = f"note_{index:03d}"
        return bounded

    @classmethod
    def _split_oversized_plan(
        cls,
        note: dict[str, Any],
        chunk_map: dict[str, dict[str, Any]],
        item_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按规划章节与来源块把超上下文笔记拆为连续部分。"""

        expanded_sections: list[dict[str, Any]] = []
        for section in note["sections"]:
            groups: list[list[str]] = []
            current: list[str] = []
            size = 0
            for chunk_id in section["source_chunk_ids"]:
                chunk_size = chunk_map[chunk_id]["character_count"]
                if current and size + chunk_size > cls.MAX_NOTE_SOURCE_CHARACTERS:
                    groups.append(current)
                    current, size = [], 0
                current.append(chunk_id)
                size += chunk_size
            if current or not groups:
                groups.append(current)
            for group_index, group in enumerate(groups, start=1):
                item_ids = [
                    item_id for item_id in section["required_item_ids"]
                    if item_map[item_id]["source_chunk_id"] in group
                ]
                heading = section["heading"]
                if len(groups) > 1:
                    heading = f"{heading}（{group_index}）"
                expanded_sections.append({
                    **section,
                    "heading": heading,
                    "source_chunk_ids": group,
                    "required_item_ids": item_ids,
                })

        parts: list[list[dict[str, Any]]] = []
        current_sections: list[dict[str, Any]] = []
        current_chunks: set[str] = set()
        current_size = 0
        for section in expanded_sections:
            new_chunks = set(section["source_chunk_ids"]) - current_chunks
            addition = sum(chunk_map[item]["character_count"] for item in new_chunks)
            if current_sections and current_size + addition > cls.MAX_NOTE_SOURCE_CHARACTERS:
                parts.append(current_sections)
                current_sections, current_chunks, current_size = [], set(), 0
                new_chunks = set(section["source_chunk_ids"])
                addition = sum(chunk_map[item]["character_count"] for item in new_chunks)
            current_sections.append(section)
            current_chunks.update(new_chunks)
            current_size += addition
        if current_sections:
            parts.append(current_sections)
        if len(parts) == 1:
            return [{**note, "sections": parts[0]}]
        return [
            {
                **note,
                "title": f"{note['title']}（第 {index} 部分）",
                "sections": sections,
            }
            for index, sections in enumerate(parts, start=1)
        ]

    def generate_notes(self, state: LearningNoteBuilderState) -> dict:
        """按照规划并行生成一篇或多篇专业笔记。"""

        plans = state["plan"]["notes"]
        chunk_map = {item["chunk_id"]: item for item in state["chunks"]}
        item_map = {item["item_id"]: item for item in state["inventory"]}

        def generate(plan: dict[str, Any]) -> dict[str, Any]:
            chunk_ids = list(dict.fromkeys(
                chunk_id
                for section in plan["sections"]
                for chunk_id in section["source_chunk_ids"]
            ))
            planned_item_ids = list(dict.fromkeys(
                item_id
                for section in plan["sections"]
                for item_id in section["required_item_ids"]
            ))
            item_ids = list(planned_item_ids)
            item_ids.extend(
                item_id for item_id, item in item_map.items()
                if item["source_chunk_id"] in chunk_ids and item_id not in item_ids
            )
            source_chunks = [chunk_map[item] for item in chunk_ids]
            information = [item_map[item] for item in item_ids]
            output = self._operations.generate_note(
                plan=plan,
                chunks=source_chunks,
                inventory=information,
            )
            payload = output.model_dump()
            payload["content"] = self._normalize_heading_style(payload["content"])
            source_characters = sum(item["character_count"] for item in source_chunks)
            payload.update({
                "note_id": plan["note_id"],
                "plan": plan,
                "source_chunk_ids": chunk_ids,
                "assigned_item_ids": item_ids,
                "covered_item_ids": [
                    item for item in dict.fromkeys(output.covered_item_ids)
                    if item in item_ids
                ],
                "quality_passed": False,
                "quality_issues": [],
                "revision_count": 0,
                "source_characters": source_characters,
            })
            return payload

        with ThreadPoolExecutor(
            max_workers=min(self._max_parallelism, len(plans))
        ) as executor:
            notes = map_with_trace(executor, generate, plans)
        return {"generated_notes": notes}

    def review_notes(self, state: LearningNoteBuilderState) -> dict:
        """并行执行语义审查，并用代码校验模型声明的信息覆盖 ID。"""

        item_map = {item["item_id"]: item for item in state["inventory"]}

        def review(note: dict[str, Any]) -> dict[str, Any]:
            assigned = set(note["assigned_item_ids"])
            claimed = set(note.get("covered_item_ids", [])) & assigned
            deterministic_missing = sorted(
                item_id for item_id in assigned - claimed
                if item_map[item_id]["importance"] == "required"
            )
            information = [item_map[item] for item in note["assigned_item_ids"]]
            output = self._operations.review_note(
                plan=note["plan"],
                note={
                    "title": note["title"],
                    "introduction": note["introduction"],
                    "topics": note["topics"],
                    "content": note["content"],
                    "covered_item_ids": sorted(claimed),
                },
                inventory=information,
            )
            llm_missing = [
                item for item in output.missing_item_ids if item in assigned
            ]
            missing = list(dict.fromkeys([*deterministic_missing, *llm_missing]))
            issues = list(output.issues)
            source_characters = int(note.get("source_characters", 0))
            video_source = "video" in str(state.get("source_type", "")).lower()
            minimum_detail = (
                min(8_000, max(800, int(source_characters * 0.28)))
                if video_source and source_characters >= 3_000
                else 0
            )
            if minimum_detail and len(note["content"].strip()) < minimum_detail:
                issues.append(
                    f"正文仅 {len(note['content'].strip())} 字符，来源约 "
                    f"{source_characters} 字符；长材料的信息保留不足"
                )
            if deterministic_missing:
                issues.append(
                    "生成结果未声明覆盖 required 信息："
                    + ", ".join(deterministic_missing)
                )
            passed = (
                output.passed
                and output.structure_professional
                and output.faithful
                and output.coverage_sufficient
                and not missing
                and (not minimum_detail or len(note["content"].strip()) >= minimum_detail)
            )
            return {
                **note,
                "covered_item_ids": sorted(claimed),
                "missing_item_ids": missing,
                "quality_passed": passed,
                "quality_issues": list(dict.fromkeys(issues)),
                "review_summary": output.summary,
            }

        notes = state["generated_notes"]
        with ThreadPoolExecutor(
            max_workers=min(self._max_parallelism, len(notes))
        ) as executor:
            reviewed = map_with_trace(executor, review, notes)
        issues = [
            f"{note['title']}：{issue}"
            for note in reviewed
            for issue in note["quality_issues"]
        ]
        return {
            "generated_notes": reviewed,
            "quality_passed": all(note["quality_passed"] for note in reviewed),
            "quality_issues": issues,
        }

    @staticmethod
    def _normalize_heading_style(content: str) -> str:
        """移除机械章节编号并规整标题周围空行，不改写正文语义。"""

        normalized = re.sub(
            r"(?m)^(#{2,6})\s+\d+(?:\.\d+)*(?:[.、：:]\s*|\s+)",
            r"\1 ",
            content.strip(),
        )
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    @classmethod
    def route_after_review(cls, state: LearningNoteBuilderState) -> str:
        """全部通过则结束，否则在全局修订上限内修订失败笔记。"""

        if state.get("quality_passed"):
            return "finish"
        if int(state.get("revision_count", 0)) < cls.MAX_REVISIONS:
            return "revise"
        return "finish"

    def repair_notes(self, state: LearningNoteBuilderState) -> dict:
        """只修订未通过的笔记，已经通过的并行结果保持不变。"""

        chunk_map = {item["chunk_id"]: item for item in state["chunks"]}
        item_map = {item["item_id"]: item for item in state["inventory"]}

        def repair(note: dict[str, Any]) -> dict[str, Any]:
            if note["quality_passed"]:
                return note
            source_chunks = [chunk_map[item] for item in note["source_chunk_ids"]]
            information = [item_map[item] for item in note["assigned_item_ids"]]
            feedback = list(note["quality_issues"])
            if note.get("missing_item_ids"):
                feedback.append(
                    "必须补回信息单元：" + ", ".join(note["missing_item_ids"])
                )
            output = self._operations.generate_note(
                plan=note["plan"],
                chunks=source_chunks,
                inventory=information,
                current_note={
                    "title": note["title"],
                    "introduction": note["introduction"],
                    "topics": note["topics"],
                    "content": note["content"],
                    "covered_item_ids": note["covered_item_ids"],
                },
                feedback=feedback,
            )
            repaired = output.model_dump()
            repaired["content"] = self._normalize_heading_style(repaired["content"])
            repaired.update({
                **{key: value for key, value in note.items() if key not in repaired},
                "covered_item_ids": [
                    item for item in dict.fromkeys(output.covered_item_ids)
                    if item in note["assigned_item_ids"]
                ],
                "quality_passed": False,
                "quality_issues": [],
                "revision_count": 1,
            })
            return repaired

        notes = state["generated_notes"]
        with ThreadPoolExecutor(
            max_workers=min(self._max_parallelism, len(notes))
        ) as executor:
            repaired = map_with_trace(executor, repair, notes)
        return {"generated_notes": repaired, "revision_count": 1}

    @staticmethod
    def _is_video_source(state: LearningNoteBuilderState) -> bool:
        """根据来源类型和提取元数据判断本轮是否源自单个视频。"""

        metadata = state.get("source_metadata", {})
        return (
            "video" in str(state.get("source_type", "")).lower()
            or str(metadata.get("media_type", "")).lower().startswith("video/")
            or str(metadata.get("extraction_mode", "")).lower().startswith("video_")
        )

    @classmethod
    def _merge_video_generation_units(
        cls, state: LearningNoteBuilderState
    ) -> list[dict[str, Any]]:
        """把长视频的多个有界生成单元确定性合并为一篇最终笔记。"""

        notes = list(state["generated_notes"])
        if len(notes) <= 1 or not cls._is_video_source(state):
            return notes
        plan = state["plan"]
        chunk_ids = list(dict.fromkeys(
            chunk_id for note in notes for chunk_id in note["source_chunk_ids"]
        ))
        assigned_ids = list(dict.fromkeys(
            item_id for note in notes for item_id in note["assigned_item_ids"]
        ))
        covered_ids = list(dict.fromkeys(
            item_id for note in notes for item_id in note.get("covered_item_ids", [])
        ))
        topics = list(dict.fromkeys(
            str(topic).strip()
            for note in notes
            for topic in note.get("topics", [])
            if str(topic).strip()
        ))
        bodies: list[str] = []
        for note in notes:
            body = re.sub(r"\A#\s+[^\n]+\n+", "", note["content"].strip())
            if body:
                bodies.append(body)
        merged_plan = {
            "note_id": "note_001",
            "title": plan["bundle_title"],
            "purpose": "完整保留单个视频的内容，并按内部生成单元组织为一篇长笔记。",
            "topics": topics,
            "sections": [
                section
                for note in notes
                for section in note["plan"].get("sections", [])
            ],
        }
        issues = list(dict.fromkeys(
            issue for note in notes for issue in note.get("quality_issues", [])
        ))
        return [{
            "note_id": "note_001",
            "title": plan["bundle_title"],
            "introduction": plan["bundle_introduction"],
            "topics": topics,
            "content": "\n\n".join(bodies),
            "plan": merged_plan,
            "source_chunk_ids": chunk_ids,
            "assigned_item_ids": assigned_ids,
            "covered_item_ids": covered_ids,
            "quality_passed": all(note.get("quality_passed") for note in notes),
            "quality_issues": issues,
            "revision_count": max(int(note.get("revision_count", 0)) for note in notes),
            "source_characters": sum(int(note.get("source_characters", 0)) for note in notes),
            "review_summary": "；".join(
                str(note.get("review_summary", "")).strip()
                for note in notes if str(note.get("review_summary", "")).strip()
            ),
            "processing_notes": [
                f"单个视频在内部拆为 {len(notes)} 个有界单元生成与审查，最终合并为一篇笔记。"
            ],
        }]

    @classmethod
    def finalize(cls, state: LearningNoteBuilderState) -> dict:
        """汇总结果；单个视频的内部生成单元最终只形成一篇笔记。"""

        warnings = list(state.get("warnings", []))
        if not state.get("quality_passed"):
            warnings.extend(state.get("quality_issues", []))
            warnings.append("部分笔记在一次定向修订后仍未通过质量审查")
        plan = state["plan"]
        generated_notes = cls._merge_video_generation_units(state)
        metadata = {
            **dict(state.get("source_metadata", {})),
            "source_type": state.get("source_type", "text"),
            "source_name": state.get("source_name", ""),
            "source_uri": state.get("source_uri", ""),
            "original_characters": len(state["input_text"]),
            "cleaned_characters": len(state["cleaned_text"]),
            "source_chunks": len(state["chunks"]),
            "information_items": len(state["inventory"]),
            "generated_notes": len(generated_notes),
            "internal_generation_units": len(state["generated_notes"]),
            "scale": state["scale"],
            "strategy": plan["strategy"],
            "source_structure_reasonable": plan["source_structure_reasonable"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "generated_notes": generated_notes,
            "metadata": metadata,
            "status": "completed" if state.get("quality_passed") else "partial",
            "warnings": list(dict.fromkeys(warnings)),
        }

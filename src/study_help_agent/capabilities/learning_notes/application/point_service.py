"""知识点提取与应用服务。"""
import hashlib
import json
import re
import unicodedata

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.infrastructure.llm.local_structured_output import (
    LocalStructuredOutput,
)
from study_help_agent.capabilities.learning_notes.application.point_ports import (
    KnowledgePointRepository,
)
from study_help_agent.capabilities.learning_notes.domain.models import NoteSegment
from study_help_agent.capabilities.learning_notes.domain.point_models import (
    KnowledgePoint,
    NotePointLink,
    PointExtractionResult,
)
from study_help_agent.capabilities.learning_notes.llm.point_schemas import (
    PointExtractionOutput,
)


class KnowledgePointService:
    """按文章规模提炼粒度适中的核心知识点并建立段落级关联。"""

    STRICT_IMPORTANCE = 0.75
    FALLBACK_IMPORTANCE = 0.60

    def __init__(self, *, repository: KnowledgePointRepository,
                 llm: BaseChatModel) -> None:
        self._repo = repository
        self._extractor = LocalStructuredOutput(llm, PointExtractionOutput)

    @property
    def last_usage(self) -> dict[str, int]:
        """最近一次知识点提取的模型 Token 用量。"""

        return dict(self._extractor.last_usage)

    def extract_and_link(self, note_filename: str,
                         segments: list[NoteSegment]) -> PointExtractionResult:
        """从笔记 segments 中提炼知识点并写入数据库。

        流程：
        1. 一次 LLM 调用提炼全部 segments 的知识点
        2. 每个知识点名 → normalize → 查 knowledge_points 去重
        3. 不存在则写入，存在则复用其 point_id
        4. 无论新旧都写入 note_point_links 关联
        """
        if not segments:
            return PointExtractionResult()

        existing = self._repo.list_all_points()
        existing_catalog = [
            {
                "point_id": str(item["point_id"]),
                "name": str(item["name"]),
                "description": str(item.get("description", ""))[:160],
                "domain": str(item.get("domain", "")),
                "entity_type": str(item.get("entity_type", "")),
            }
            for item in existing[:300]
        ]

        payload = "\n\n".join(
            f"--- segment {index} ---\n{segment.title}\n{segment.content}"
            for index, segment in enumerate(segments)
        )
        content_characters = sum(len(segment.content) for segment in segments)
        minimum_points, target_points, maximum_points = self._point_budget(
            content_characters
        )
        candidate_limit = min(30, max(maximum_points + 3, maximum_points * 2))
        output = self._extractor.invoke(
            "你负责为知识图谱精选整篇笔记最核心的概念，而不是做全文关键词提取。"
            "只保留理解文章主线不可缺少、被正式定义、反复展开或直接支撑主要结论的概念。"
            "知识点粒度必须与文章主题相邻：允许文章的直接主主题，以及文中被重点讲解的"
            "关键子概念、机制、方法或框架。例如文章主要讨论 Agent，可以选择 Agent、Skill、"
            "ReAct；但不能选择比文章主题宽泛多个层级的 AI、计算机科学、技术，也不能选择"
            "变量名、参数名、文件名、按钮动作、单句操作或只出现一次的实现碎片。"
            "不要把完整句子当作知识点，不要拆出同一概念的多个同义变体。每个候选都要"
            "相对文章主主题判断粒度；只有粒度合适时 granularity_fit 才能为 true。"
            "description 只定义知识点本身：说明它是什么、核心机制或适用边界，必须是"
            "脱离当前文章上下文后仍然成立的通用概念定义。description 不得总结或评价"
            "当前文章，不得描述‘文章如何使用该知识点’，也不得出现‘本文、文中、"
            "本笔记、该笔记、作者提到、上述内容、在这里’等依赖原文的措辞。"
            "生成新节点前必须检查已有知识点目录：如果只是大小写、空格、常见译名、简称、"
            "全称或措辞差异，但语义上确实是同一个规范概念，必须填写对应的"
            " matched_existing_point_id，并优先沿用已有规范名称。仅仅相关、属于上下位关系、"
            "共同出现或名称相似，不得匹配已有 ID；无法确定时填写 null。"
            "domain 必须填写一个清晰、单一、稳定的主题名称。禁止用斜杠、顿号、逗号、"
            "加号或‘与’把两个主题拼成一个主题，例如不得输出‘Agent/AI’或‘Agent 与 AI’；"
            "应选择最能概括文章主线的一个上位主题，同一篇文章中的候选应尽量使用同一主题。"
            f"本文约 {content_characters} 字，目标提取 {target_points} 个，最多返回"
            f" {candidate_limit} 个候选供程序筛选；优先保证质量，不得为了数量虚构概念。"
            "候选按 importance 从高到低排列；核心概念应达到 0.75，具备明确原文证据但"
            "重要性略低的候选可以在 0.60～0.74，供数量不足时兜底。"
            "每个知识点必须提供对应 segment 中可以直接找到的简短 evidence_excerpt。"
            "已存在的知识点必须优先复用其规范名称，不要重复创建。\n"
            f"已有知识点目录：{json.dumps(existing_catalog, ensure_ascii=False)}\n"
            f"笔记内容：{payload}"
        )

        points: list[KnowledgePoint] = []
        links: list[NotePointLink] = []
        existing_by_normalized = {
            self._normalize_name(str(item["name"])): item for item in existing
        }
        existing_by_id = {
            str(item["point_id"]): item for item in existing
        }
        candidates = sorted(
            output.points,
            key=lambda item: item.importance,
            reverse=True,
        )[:candidate_limit]
        valid_candidates = []
        candidate_identities: set[str] = set()
        for item in candidates:
            normalized_name = self._normalize_name(item.name)
            matched_id = str(item.matched_existing_point_id or "").strip()
            identity = (
                f"point:{matched_id}"
                if matched_id in existing_by_id
                else f"candidate:{normalized_name}"
            )
            if (
                identity not in candidate_identities
                and self._is_valid_candidate(item=item, segments=segments)
            ):
                valid_candidates.append(item)
                candidate_identities.add(identity)
        selected = [
            item for item in valid_candidates
            if item.importance >= self.STRICT_IMPORTANCE
        ][:maximum_points]
        if len(selected) < minimum_points:
            selected_ids = {id(item) for item in selected}
            for item in valid_candidates:
                if len(selected) >= target_points:
                    break
                if (
                    id(item) not in selected_ids
                    and item.importance >= self.FALLBACK_IMPORTANCE
                ):
                    selected.append(item)
        linked_point_ids: set[str] = set()
        for item in selected:
            normalized_name = self._normalize_name(item.name)
            name = item.name.strip()
            segment_index = item.segment_index
            if not 0 <= segment_index < len(segments):
                continue
            evidence = item.evidence_excerpt.strip()
            # 知识点去重
            matched_id = str(item.matched_existing_point_id or "").strip()
            existing_point = existing_by_id.get(matched_id)
            if existing_point is None:
                existing_point = existing_by_normalized.get(normalized_name)
            if existing_point is None:
                point_id = self._compute_point_id(name)
                self._repo.save_point(
                    point_id=point_id,
                    name=name,
                    description=item.description,
                    domain=item.domain,
                    entity_type=item.entity_type,
                )
                points.append(
                    KnowledgePoint(
                        point_id=point_id,
                        name=name,
                        description=item.description,
                        domain=item.domain,
                        entity_type=item.entity_type,
                    )
                )
            else:
                point_id = str(existing_point["point_id"])
                name = str(existing_point["name"])

            if point_id in linked_point_ids:
                continue

            self._repo.link_point_to_note(
                point_id=point_id,
                note_filename=note_filename,
                segment_index=segment_index,
                relevance="core",
            )
            links.append(
                NotePointLink(
                    point_id=point_id,
                    note_filename=note_filename,
                    segment_index=segment_index,
                    evidence_excerpt=evidence,
                )
            )
            linked_point_ids.add(point_id)
        return PointExtractionResult(knowledge_points=points, links=links)

    @staticmethod
    def _point_budget(content_characters: int) -> tuple[int, int, int]:
        """根据正文字符数返回软下限、目标数和硬上限。"""

        if content_characters <= 3_000:
            return 2, 3, 5
        if content_characters <= 8_000:
            return 5, 7, 10
        if content_characters <= 20_000:
            return 6, 10, 14
        return 8, 14, 20

    def _is_valid_candidate(self, *, item, segments: list[NoteSegment]) -> bool:
        """用确定性规则过滤过宽名称、非法段落与无法定位的证据。"""

        name = item.name.strip()
        if not name or not item.granularity_fit:
            return False
        if len(name) > 60 or "\n" in name:
            return False
        if not 0 <= item.segment_index < len(segments):
            return False
        evidence = item.evidence_excerpt.strip()
        return bool(
            evidence
            and evidence.casefold()
            in segments[item.segment_index].content.casefold()
        )

    def delete_links_for_note(self, note_filename: str) -> None:
        """删除笔记时清理其全部知识点关联（LearningNoteService.delete 调用）。"""
        self._repo.delete_links_for_note(note_filename)

    def points_for_source(self, source_key: str) -> list[dict]:
        """查询来源已关联的知识点，用于避免用户重复触发 LLM 分析。"""
        return self._repo.get_points_by_note(source_key)

    def retain_extracted_links(
        self, source_key: str, links: list[NotePointLink]
    ) -> None:
        """Wiki 增量构建成功后移除本来源已经失效的旧关联。"""

        self._repo.retain_links_for_note(
            source_key,
            [(link.point_id, link.segment_index) for link in links],
        )

    def _normalize_name(self, name: str) -> str:
        """统一 Unicode、大小写和非语义分隔符，用于低成本精确复用。"""

        normalized = unicodedata.normalize("NFKC", name).strip().casefold()
        return re.sub(
            r"[\s_\-–—·•（）()\[\]【】「」『』“”\"'，,。.:：；;]+",
            "",
            normalized,
        )

    def _compute_point_id(self, name: str) -> str:
        """sha256(标准化名称) 作为主键。"""
        return hashlib.sha256(
            self._normalize_name(name).encode("utf-8")
        ).hexdigest()

    def get_graph_data(self) -> dict:
        """返回知识点—笔记二部图。

        图中只有知识点与笔记两类节点；关联边携带 ``segment_index``，
        供前端打开完整笔记后定位到知识点所在段落。
        """
        points = self._repo.list_all_points()
        point_nodes: list[dict] = []
        note_nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for point in points:
            point_id = str(point["point_id"])
            point_node_id = f"note-point:{point_id}"
            point_nodes.append(
                {
                    "id": point_node_id,
                    "label": str(point["name"]),
                    "node_type": "knowledge_point",
                    "domain": "note",
                    "summary": str(point["description"]),
                    "payload": {
                        "point_id": point_id,
                        "name": str(point["name"]),
                        "knowledge_domain": str(point["domain"]),
                        "entity_type": str(point["entity_type"]),
                    },
                }
            )
            for link in self._repo.get_notes_by_point(point_id):
                filename = str(link["note_filename"])
                segment_index = int(link["segment_index"])
                note_node_id = f"note:{filename}"

                note_nodes.setdefault(
                    note_node_id,
                    {
                        "id": note_node_id,
                        "label": filename,
                        "node_type": "note",
                        "domain": "note",
                        "summary": f"学习笔记：{filename}",
                        "payload": {
                            "filename": filename,
                        },
                    },
                )

                edges.append(
                    {
                        "id": (
                            f"note-edge:{point_id}:"
                            f"{filename}:{segment_index}"
                        ),
                        "source": point_node_id,
                        "target": note_node_id,
                        "label": "appears_in",
                        "payload": {
                            "point_id": point_id,
                            "filename": filename,
                            "segment_index": segment_index,
                        },
                    }
                )
        return {
            "nodes": [
                *point_nodes,
                *note_nodes.values(),
            ],
            "edges": edges,
        }

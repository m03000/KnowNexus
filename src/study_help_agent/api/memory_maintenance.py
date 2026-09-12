"""Daily summaries and review of memory conflict edges."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from study_help_agent.infrastructure.llm.local_structured_output import LocalStructuredOutput

router = APIRouter(prefix="/api/memory-maintenance", tags=["memory-maintenance"])
LOCAL_ZONE = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

class SummaryItem(BaseModel):
    title: str = Field(max_length=20)
    content: str = Field(max_length=1200)

class SummaryOutput(BaseModel):
    items: list[SummaryItem] = Field(default_factory=list, max_length=5)

class HotspotOutput(BaseModel):
    title: str = Field(max_length=40)
    content: str = Field(max_length=5000)

class TopicPayload(BaseModel):
    name: str = Field(min_length=1, max_length=30)

class SlotPayload(BaseModel):
    topic_id: int | None = None

def day_bounds(day) -> tuple[str, str]:
    start = datetime.combine(day, time.min, LOCAL_ZONE).astimezone(UTC)
    return start.isoformat(timespec="seconds"), (start + timedelta(days=1)).isoformat(timespec="seconds")

class DailyMemorySummaryService:
    def __init__(self, database, llm, note_service=None) -> None:
        self.database, self.llm, self.note_service = database, llm, note_service

    def ensure_yesterday(self) -> list[dict]:
        return self.ensure((datetime.now(LOCAL_ZONE).date() - timedelta(days=1)).isoformat())

    def ensure(self, summary_date: str) -> list[dict]:
        with self.database.connect() as connection:
            saved = connection.execute("SELECT title,content FROM daily_memory_summaries WHERE summary_date=? ORDER BY item_order", (summary_date,)).fetchall()
        if saved:
            return [dict(row) for row in saved]
        start, end = day_bounds(datetime.fromisoformat(summary_date).date())
        with self.database.connect() as connection:
            memories = connection.execute("""SELECT content,summary,origin_client FROM memory_points
                WHERE created_at>=? AND created_at<? AND origin_type!='internal'
                AND status IN ('active','superseded','conflicted') ORDER BY created_at""", (start, end)).fetchall()
        if not memories:
            return []
        evidence = "\n".join(f"- [{row['origin_client']}] {row['summary'] or row['content']}" for row in memories)
        output = LocalStructuredOutput(self.llm, SummaryOutput).invoke(
            "请根据以下昨天由外部智能体监听并形成的记忆，总结用户做了什么、推进了什么、形成了哪些决定。"
            "最多生成五个总结，但不是一定要生成五个总结，按照具体的内容和内容量来决定要生成几个总结；"
            "每项标题不超过20字，正文是约150至400字的一个自然段。不要虚构，也不要只罗列指标。\n\n" + evidence)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        items = output.items[:5]
        with self.database.connect() as connection:
            for index, item in enumerate(items):
                connection.execute("INSERT OR IGNORE INTO daily_memory_summaries(summary_date,item_order,title,content,created_at) VALUES (?,?,?,?,?)", (summary_date, index, item.title.strip()[:20], item.content.strip()[:1200], now))
        return [{"title": item.title.strip()[:20], "content": item.content.strip()[:1200]} for item in items]

    def latest(self) -> dict:
        target = datetime.now(LOCAL_ZONE).date() - timedelta(days=1)
        with self.database.connect() as connection:
            rows = connection.execute("SELECT title,content FROM daily_memory_summaries WHERE summary_date=? ORDER BY item_order", (target.isoformat(),)).fetchall()
        return {"summary_date": target.isoformat(), "items": [dict(row) for row in rows]}

    @staticmethod
    def _github_hotspot_evidence(topic: str) -> str:
        """Collect recent popular repositories for a configured interest topic."""
        since = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
        query = f'{topic} in:name,description,readme pushed:>={since}'
        with httpx.Client(
            timeout=20,
            follow_redirects=False,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "personal-agent-hotspot-research",
            },
        ) as client:
            response = client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": 8},
            )
            response.raise_for_status()
        if response.is_redirect:
            raise PermissionError("GitHub 热点接口不接受重定向")
        payload = response.json()
        rows = []
        for repository in payload.get("items", [])[:8]:
            name = str(repository.get("full_name") or "").strip()
            if not name:
                continue
            description = str(repository.get("description") or "暂无项目说明").strip()
            rows.append(
                f"- {name}（Stars {int(repository.get('stargazers_count') or 0):,}，"
                f"语言 {repository.get('language') or '未标注'}，更新 {repository.get('pushed_at') or '未知'}）："
                f"{description}；{repository.get('html_url') or ''}"
            )
        return "\n".join(rows)

    def refresh_hotspots(self) -> None:
        today = datetime.now(LOCAL_ZONE).date().isoformat()
        with self.database.connect() as connection:
            slots = connection.execute("""SELECT s.slot_id,t.topic_id,t.name FROM research_hotspot_slots s
                JOIN research_topics t ON t.topic_id=s.topic_id WHERE s.topic_id IS NOT NULL""").fetchall()
        for slot in slots:
            with self.database.connect() as connection:
                exists = connection.execute("SELECT 1 FROM research_hotspots WHERE slot_id=? AND topic_id=? AND research_date=?", (slot["slot_id"], slot["topic_id"], today)).fetchone()
            if exists:
                continue
            evidence = self._github_hotspot_evidence(slot["name"])
            if not evidence:
                continue
            result = LocalStructuredOutput(self.llm, HotspotOutput).invoke(
                f"根据 GitHub 公开项目数据，详细介绍“{slot['name']}”最近活跃的热点项目。"
                f"标题不超过30字，正文控制在2000至5000字；数据不足时可以更短，但不得凑字数或虚构。"
                f"正文必须使用以下清晰层级，各部分之间空一行：\n一、主题趋势概览\n二、重点项目详解\n"
                f"三、项目横向比较\n四、值得关注的技术方向\n五、数据限制与待验证事项。"
                f"重点项目逐个说明用途、核心能力、适用场景、Stars、主要语言、近期活跃度和项目地址；"
                f"比较项目之间的定位差异，并明确推断与事实的边界。不得补充下列项目数据之外的事实。\n\n{evidence}")
            with self.database.connect() as connection:
                connection.execute("""INSERT INTO research_hotspots(slot_id,topic_id,research_date,title,content,is_read,added_to_wiki,created_at)
                    VALUES (?,?,?,?,?,0,0,?) ON CONFLICT(slot_id,research_date) DO UPDATE SET
                    topic_id=excluded.topic_id,title=excluded.title,content=excluded.content,is_read=0,
                    added_to_wiki=0,created_at=excluded.created_at""", (slot["slot_id"], slot["topic_id"], today, result.title[:20], result.content[:4000], datetime.now(UTC).isoformat(timespec="seconds")))

def service(request: Request) -> DailyMemorySummaryService:
    return request.app.state.daily_memory_summary_service

@router.get("/wiki-workspace")
def wiki_workspace(request: Request) -> dict:
    today = datetime.now(LOCAL_ZONE).date().isoformat()
    with request.app.state.container.database.connect() as connection:
        topics = [dict(row) for row in connection.execute("SELECT topic_id,name FROM research_topics ORDER BY created_at")]
        rows = connection.execute("""SELECT s.slot_id,s.topic_id,t.name topic_name,h.hotspot_id,h.title,h.content,h.is_read,h.added_to_wiki
            FROM research_hotspot_slots s LEFT JOIN research_topics t ON t.topic_id=s.topic_id
            LEFT JOIN research_hotspots h ON h.hotspot_id=(SELECT hotspot_id FROM research_hotspots x WHERE x.slot_id=s.slot_id AND x.topic_id=s.topic_id ORDER BY x.created_at DESC LIMIT 1)
            ORDER BY s.slot_id""").fetchall()
        note_count = connection.execute("SELECT COUNT(*) n FROM note_library_entries WHERE date(created_at, '+8 hours')=?", (today,)).fetchone()["n"]
        wiki_count = connection.execute("SELECT COUNT(*) n FROM wiki_sources WHERE date(created_at, '+8 hours')=?", (today,)).fetchone()["n"]
        hotspot_count = connection.execute("SELECT COUNT(*) n FROM research_hotspots WHERE research_date=?", (today,)).fetchone()["n"]
    return {"topics": topics, "slots": [dict(row) for row in rows], "today_notes": note_count, "today_wiki": wiki_count, "today_hotspots": hotspot_count}

@router.post("/topics")
def add_topic(payload: TopicPayload, request: Request) -> dict:
    with request.app.state.container.database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO research_topics(name,created_at) VALUES (?,?)", (payload.name.strip(), datetime.now(UTC).isoformat(timespec="seconds")))
    return wiki_workspace(request)

@router.put("/hotspot-slots/{slot_id}")
def select_slot_topic(slot_id: int, payload: SlotPayload, request: Request) -> dict:
    if slot_id not in {1, 2, 3}:
        raise HTTPException(400, "热点卡片不存在")
    with request.app.state.container.database.connect() as connection:
        connection.execute("UPDATE research_hotspot_slots SET topic_id=? WHERE slot_id=?", (payload.topic_id, slot_id))
    return wiki_workspace(request)

@router.post("/hotspots/refresh")
def refresh_hotspots(request: Request) -> dict:
    service(request).refresh_hotspots()
    return wiki_workspace(request)

@router.post("/hotspots/{hotspot_id}/read")
def mark_hotspot_read(hotspot_id: int, request: Request) -> dict:
    with request.app.state.container.database.connect() as connection:
        connection.execute("UPDATE research_hotspots SET is_read=1 WHERE hotspot_id=?", (hotspot_id,))
    return {"read": True}

@router.post("/hotspots/{hotspot_id}/add-to-wiki")
def add_hotspot_to_wiki(hotspot_id: int, request: Request) -> dict:
    summary_service = service(request)
    with request.app.state.container.database.connect() as connection:
        row = connection.execute("""SELECT h.title,h.content,t.name topic_name FROM research_hotspots h
            JOIN research_topics t ON t.topic_id=h.topic_id WHERE h.hotspot_id=?""", (hotspot_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "热点不存在")
    # 保留热点语义完整性；原先 15 字符硬截断会把目录文件名永久截成半句话。
    title = f"{datetime.now(LOCAL_ZONE):%m%d}-{row['topic_name']}-{row['title']}"[:96].rstrip()
    created = summary_service.note_service.create_manual_note(title)
    summary_service.note_service.update(created["filename"], f"# {title}\n\n{row['content']}")
    with request.app.state.container.database.connect() as connection:
        connection.execute("UPDATE research_hotspots SET added_to_wiki=1 WHERE hotspot_id=?", (hotspot_id,))
    return {"added": True, "filename": created["filename"], "title": title}

@router.get("/dashboard")
def dashboard(request: Request) -> dict:
    start, end = day_bounds(datetime.now(LOCAL_ZONE).date())
    with request.app.state.container.database.connect() as connection:
        points = connection.execute("SELECT COUNT(*) n FROM memory_points WHERE created_at>=? AND created_at<? AND origin_type!='internal'", (start, end)).fetchone()["n"]
        relations = connection.execute("""SELECT COUNT(*) n FROM memory_relations r
            JOIN memory_points p ON r.source_type='memory_point' AND p.memory_id=r.source_id
            WHERE r.created_at>=? AND r.created_at<? AND p.origin_type!='internal'""", (start, end)).fetchone()["n"]
        conflicts = connection.execute("SELECT COUNT(*) n FROM memory_relations WHERE relation_type='CONTRADICTS'").fetchone()["n"]
        def internal_agent(start_at: str = "", end_at: str = "") -> dict:
            date_filter = " AND c.created_at>=? AND c.created_at<?" if start_at and end_at else ""
            params = (start_at, end_at) if date_filter else ()
            conversation_count = connection.execute(
                "SELECT COUNT(*) n FROM conversations c WHERE c.origin_type='internal'" + date_filter,
                params,
            ).fetchone()["n"]
            turn_filter = " AND m.created_at>=? AND m.created_at<?" if start_at and end_at else ""
            captured_turns = connection.execute(
                "SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.session_id=m.session_id "
                "WHERE c.origin_type='internal' AND m.role='user'" + turn_filter,
                params,
            ).fetchone()["n"]
            point_filter = " AND p.created_at>=? AND p.created_at<?" if start_at and end_at else ""
            memory_points = connection.execute(
                "SELECT COUNT(*) n FROM memory_points p WHERE p.origin_type='internal' AND p.status='active'" + point_filter,
                params,
            ).fetchone()["n"]
            relation_filter = " AND r.created_at>=? AND r.created_at<?" if start_at and end_at else ""
            relations_count = connection.execute(
                "SELECT COUNT(DISTINCT r.relation_id) n FROM memory_relations r JOIN memory_points p ON "
                "(r.source_type='memory_point' AND r.source_id=p.memory_id) OR "
                "(r.target_type='memory_point' AND r.target_id=p.memory_id) "
                "WHERE p.origin_type='internal'" + relation_filter,
                params,
            ).fetchone()["n"]
            return {"id": "internal-conversation", "name": "内部对话", "adapter_id": "personal_agent",
                    "running": True, "conversation_count": conversation_count,
                    "captured_turns": captured_turns, "memory_points": memory_points,
                    "relations": relations_count, "distillation_tokens": 0}
        internal_today = internal_agent(start, end)
        internal_history = internal_agent()
    return {"start_at": start, "end_at": end, "memory_points": points, "relations": relations,
            "conflicts": conflicts, "summary": service(request).latest(),
            "internal_agent_today": internal_today, "internal_agent": internal_history}

@router.get("/conflicts")
def list_conflicts(request: Request) -> dict:
    with request.app.state.container.database.connect() as connection:
        rows = connection.execute("""SELECT r.relation_id,r.confidence,a.memory_id source_id,a.content source_content,
            b.memory_id target_id,b.content target_content FROM memory_relations r
            JOIN memory_points a ON a.memory_id=r.source_id JOIN memory_points b ON b.memory_id=r.target_id
            WHERE r.relation_type='CONTRADICTS' AND a.status!='archived' AND b.status!='archived'
            ORDER BY r.created_at DESC""").fetchall()
    return {"conflicts": [dict(row) for row in rows]}

@router.post("/conflicts/{relation_id}/keep/{side}")
def resolve_conflict(relation_id: str, side: str, request: Request) -> dict:
    if side not in {"source", "target"}:
        raise HTTPException(400, "side 必须是 source 或 target")
    with request.app.state.container.database.connect() as connection:
        relation = connection.execute("SELECT source_id,target_id FROM memory_relations WHERE relation_id=? AND relation_type='CONTRADICTS'", (relation_id,)).fetchone()
        if relation is None:
            raise HTTPException(404, "冲突关系不存在")
        archived = relation["target_id" if side == "source" else "source_id"]
        connection.execute("UPDATE memory_points SET status='archived',updated_at=CURRENT_TIMESTAMP WHERE memory_id=?", (archived,))
        connection.execute("DELETE FROM memory_relations WHERE relation_id=?", (relation_id,))
    return {"resolved": True, "kept": side, "archived_memory_id": archived}

async def run_daily_summary_loop(summary_service: DailyMemorySummaryService) -> None:
    while True:
        if datetime.now(LOCAL_ZONE).hour >= 12:
            try:
                await asyncio.to_thread(summary_service.ensure_yesterday)
            except Exception:
                logger.warning("每日记忆总结生成失败", exc_info=True)
            try:
                await asyncio.to_thread(summary_service.refresh_hotspots)
            except Exception:
                logger.warning("每日兴趣热点生成失败", exc_info=True)
        await asyncio.sleep(300)

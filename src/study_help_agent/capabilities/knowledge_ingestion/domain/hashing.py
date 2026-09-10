"""生成幂等资产 ID、内容摘要和 Outbox 任务 ID。"""

from hashlib import sha256


def content_digest(content: str) -> str:
    """计算完整内容摘要，用于判断知识是否真的发生变化。"""

    return sha256(content.encode("utf-8")).hexdigest()


def stable_asset_id(*, space: str, stable_source_key: str) -> str:
    """同一业务来源始终映射到同一个资产 ID。"""

    digest = sha256(f"{space}|{stable_source_key}".encode("utf-8")).hexdigest()[:32]
    return f"asset_{digest}"


def stable_job_id(*, asset_id: str, version: int, content_hash: str) -> str:
    """同一资产版本只产生一个可重试的索引任务。"""

    digest = sha256(
        f"{asset_id}|{version}|{content_hash}".encode("utf-8")
    ).hexdigest()[:32]
    return f"ingestion_{digest}"


def stable_chunk_id(
    *, asset_id: str, version: int, logical_key: str, content_hash: str
) -> str:
    """生成适合 SQLite 和 Qdrant 使用的 UUID 字符串。"""

    from uuid import NAMESPACE_URL, uuid5

    value = f"{asset_id}|{version}|{logical_key}|{content_hash}"
    return str(uuid5(NAMESPACE_URL, value))


def stable_deletion_job_id(*, asset_id: str, version: int) -> str:
    """为资产删除事件生成与 ready 任务不同的稳定 ID。"""

    digest = sha256(f"delete|{asset_id}|{version}".encode("utf-8")).hexdigest()[:32]
    return f"ingestion_delete_{digest}"

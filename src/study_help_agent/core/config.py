"""应用配置。

本模块只负责：
1. 声明应用需要哪些配置；
2. 从环境变量或 .env 文件读取配置；
3. 校验配置类型。

本模块不创建 LLM，不连接数据库，也不读取业务数据。
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# 当前 config.py 位于：
# project_root/src/study_help_agent/core/config.py
#
# parents[0] = core
# parents[1] = study_help_agent
# parents[2] = src
# parents[3] = project_root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 运行期模型加载器通过 ``local_files_only`` 保证不联网。这里不能全局设置
# HF_HUB_OFFLINE，否则模型管理页发起的“显式下载”也会被一并禁止。
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class Settings(BaseSettings):
    """整个应用的统一配置模型。"""

    # 优先查找项目根目录下.env文件
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用配置 ----------

    app_name: str = "Study Help Agent"
    environment: str = "development"
    debug: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
            "null",
        ],
        description="允许访问后端 API 的前端来源",
    )

    # ---------- LLM 配置 ----------

    llm_api_key: SecretStr = Field(
        description="LLM 服务 API Key",
    )

    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="OpenAI 兼容接口地址",
    )

    llm_model: str = Field(
        default="deepseek-chat",
        description="默认聊天模型名称",
    )

    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="默认采样温度",
    )

    llm_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="单次模型调用超时时间",
    )

    llm_max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        description="模型调用失败后的最大重试次数",
    )

    llm_thinking_mode: Literal[
        "enabled",
        "disabled",
    ] = Field(
        default="disabled",
        description=(
            "模型 Thinking Mode。"
            "代码解释的结构化调用默认关闭。"
        ),
    )

    agent_shutdown_grace_seconds: float = Field(
        default=15.0,
        ge=0.0,
        le=300.0,
        description="应用关闭时等待活跃 Agent在安全边界退出的秒数",
    )

    # ---------- 数据库配置 ----------

    database_path: Path = Field(
        default=PROJECT_ROOT
                / "var"
                / "data"
                / "study_help.db",
        description="项目使用的 SQLite 数据库",
    )

    sqlite_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        description="等待 SQLite 数据库锁的最长时间",
    )

    sqlite_busy_timeout_ms: int = Field(
        default=5000,
        ge=0,
        le=300000,
        description="SQLite busy_timeout，单位为毫秒",
    )

    # ---------- 项目源码访问配置 ----------

    allowed_project_roots: list[Path] = Field(
        default_factory=list,
        description=(
            "允许分析的项目根目录。"
            "为空时不限制，仅适合本地开发环境。"
        ),
    )

    source_scan_max_files: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="单次项目扫描允许的最大源码文件数",
    )

    source_file_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        description="允许读取的单个源码文件最大字节数",
    )

    # ---------- 运行期目录 ----------

    runtime_data_directory: Path = Field(
        default=PROJECT_ROOT / "var" / "data",
    )

    runtime_log_directory: Path = Field(
        default=PROJECT_ROOT / "var" / "logs",
    )

    note_export_directory: Path = Field(
        default_factory=lambda: Path.home() / "Documents" / "AgentForge" / "导出笔记",
        description="AI 笔记导出的固定目录",
    )

    llm_max_tokens: int = Field(
        default=8192,
        ge=1,
        le=131072,
        description="默认模型单次回答允许的最大输出 Token",
    )

    # ---------- Codex 外部对话监听 ----------

    codex_watcher_enabled: bool = Field(
        default=False,
        description="后端启动时是否默认启动 Codex 会话监听器",
    )
    codex_watcher_sessions_directory: Path = Field(
        default=Path.home() / ".codex" / "sessions",
        description="Codex rollout JSONL 会话根目录",
    )
    codex_watcher_poll_seconds: float = Field(default=20.0, ge=1.0, le=300.0)
    codex_watcher_full_scan_seconds: float = Field(default=60.0, ge=3.0, le=3600.0)
    codex_watcher_active_window_seconds: float = Field(
        default=86_400.0, ge=60.0, le=2_592_000.0,
    )

    @property
    def external_watcher_poll_seconds(self) -> float:
        """所有外部智能体共用的轮询间隔（保留旧环境变量名称兼容性）。"""

        return self.codex_watcher_poll_seconds


    knowledge_base_directory: Path = Field(
        default=PROJECT_ROOT / "data" / "knowledge_base",
    )

    code_analysis_max_parallelism: int = Field(
        default=5,
        ge=1,
        le=25,
        description="代码职责与代码块分析阶段允许的最大并行 LLM 请求数",
    )

    # ---------- 学习资源处理配置 ----------

    learning_resource_max_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=1024,
        description="单个文档、音频或视频资源允许的最大字节数",
    )
    learning_video_cookie_browser: str = Field(
        default="edge",
        description="Browser used by yt-dlp to load platform cookies; empty disables it",
    )
    learning_whisper_model: str = Field(
        default="small",
        description="音视频语音转写使用的 faster-whisper 模型",
    )
    learning_whisper_device: str = Field(
        default="auto",
        description="Whisper 运行设备；auto 优先 CUDA，初始化失败时回退 CPU",
    )
    learning_whisper_compute_type: str = Field(
        default="auto",
        description="Whisper 计算精度；auto 在 CUDA 使用 float16，在 CPU 使用 int8",
    )
    learning_video_sample_seconds: int = Field(
        default=15,
        ge=1,
        le=600,
        description="视频画面 OCR 的抽帧时间间隔",
    )
    learning_video_max_frames: int = Field(
        default=120,
        ge=1,
        le=10000,
        description="单个视频最多执行 OCR 的画面数量",
    )
    learning_ocr_languages: str = Field(
        default="chi_sim+eng",
        description="Tesseract OCR 语言组合",
    )
    learning_media_max_parallelism: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Whisper 与视频 OCR 等重型媒体提取的最大并发数",
    )
    learning_video_split_threshold_seconds: int = Field(
        default=600,
        ge=60,
        description="超过该时长的视频才执行低内存分片处理",
    )
    learning_video_segment_seconds: int = Field(
        default=480,
        ge=60,
        description="长视频单个处理分片的目标时长",
    )
    learning_video_parallel_audio_visual: bool = Field(
        default=True,
        description="普通视频及长视频的音频转写与画面 OCR 是否并行",
    )
    learning_normalization_chunk_characters: int = Field(
        default=8000,
        ge=2000,
        le=30000,
        description="长文本去噪单个 LLM 分块的最大字符数",
    )
    learning_normalization_max_parallelism: int = Field(
        default=3,
        ge=1,
        le=8,
        description="长文本去噪分块的最大并行数",
    )

    # ---------- 基础 RAG 检索配置 ----------

    rag_vector_database_path: Path = Field(
        default=PROJECT_ROOT / "var" / "data" / "vector_db",
        description="Qdrant 本地向量数据库目录",
    )
    rag_embedding_model: str = Field(
        default="BAAI/bge-m3",
        description="与原版索引一致的 Embedding 模型",
    )
    rag_reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="混合召回后的 CrossEncoder 重排模型",
    )
    rag_models_local_files_only: bool = Field(
        default=True,
        description="是否只从本机缓存加载 Embedding 与 Reranker 模型",
    )
    rag_model_cache_directory: Path = Field(
        default=PROJECT_ROOT / "var" / "models" / "huggingface" / "hub",
        description="项目私有 Hugging Face Hub 缓存目录",
    )
    rag_retrieval_cache_ttl_seconds: int = Field(
        default=1800,
        ge=0,
        description="检索结果内存缓存 TTL；0 表示结果立即过期",
    )


# 第一次创建后，后续获得同一个对象。
    # ---------- Knowledge ingestion ----------

    knowledge_ingestion_enabled: bool = True
    knowledge_ingestion_poll_seconds: float = Field(default=2.0, gt=0, le=300)
    knowledge_ingestion_batch_size: int = Field(default=8, ge=1, le=100)
    knowledge_ingestion_max_attempts: int = Field(default=5, ge=1, le=20)
    rag_project_code_collection: str = "project_code"
    rag_personal_knowledge_collection: str = "personal_knowledge"
    rag_user_memory_collection: str = "user_memory"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回应用配置单例。

    第一次调用时创建 Settings，后续调用返回同一个对象。
    """

    return Settings()

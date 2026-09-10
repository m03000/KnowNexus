"""笔记图谱（知识点）数据库迁移。"""
import sqlite3
from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_009_create_knowledge_points(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    CREATE TABLE knowledge_points (
        point_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        domain TEXT NOT NULL DEFAULT '',
        entity_type TEXT NOT NULL DEFAULT 'concept',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_kp_domain ON knowledge_points(domain);
    CREATE INDEX idx_kp_entity_type ON knowledge_points(entity_type);

    CREATE TABLE note_point_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        point_id TEXT NOT NULL,
        note_filename TEXT NOT NULL,
        segment_index INTEGER NOT NULL,
        relevance TEXT NOT NULL DEFAULT 'defined',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (point_id) REFERENCES knowledge_points(point_id) ON DELETE CASCADE,
        UNIQUE (point_id, note_filename, segment_index)
    );
    CREATE INDEX idx_npl_note ON note_point_links(note_filename);
    CREATE INDEX idx_npl_point ON note_point_links(point_id);
    """)


def migration_019_allow_linked_library_documents(connection: sqlite3.Connection) -> None:
    """将个人文档的新默认语义从“复制导入”扩展为“原路径关联”。"""
    connection.executescript(
        """
        ALTER TABLE library_documents RENAME TO library_documents_v16;

        CREATE TABLE library_documents (
            document_id TEXT PRIMARY KEY,
            folder_id TEXT NOT NULL,
            name TEXT NOT NULL,
            stored_path TEXT NOT NULL UNIQUE,
            media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            resource_id TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL CHECK (source_kind IN ('import', 'linked', 'agent_source')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (folder_id) REFERENCES library_folders(folder_id) ON DELETE RESTRICT
        );
        INSERT INTO library_documents
            (document_id, folder_id, name, stored_path, media_type, size_bytes, resource_id, source_kind, created_at)
        SELECT document_id, folder_id, name, stored_path, media_type, size_bytes, resource_id, source_kind, created_at
        FROM library_documents_v16;
        DROP TABLE library_documents_v16;
        CREATE INDEX idx_library_documents_folder ON library_documents(folder_id);
        CREATE INDEX idx_library_documents_resource ON library_documents(resource_id);
        """
    )


NOTE_POINT_MIGRATIONS = [
    Migration(
        version=9,
        name="create knowledge points and note point links",
        upgrade=migration_009_create_knowledge_points,
    ),
    Migration(
        version=16,
        name="create note library folders and documents",
        upgrade=lambda connection: connection.executescript(
            """
            CREATE TABLE library_folders (
                folder_id TEXT PRIMARY KEY,
                parent_id TEXT,
                library_type TEXT NOT NULL CHECK (library_type IN ('ai_note', 'personal_document')),
                name TEXT NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (parent_id) REFERENCES library_folders(folder_id) ON DELETE RESTRICT,
                UNIQUE (parent_id, name)
            );
            INSERT INTO library_folders(folder_id, parent_id, library_type, name, is_system, sort_order)
            VALUES
                ('ai-note-root', NULL, 'ai_note', 'AI 笔记', 1, 0),
                ('personal-document-root', NULL, 'personal_document', '个人文档', 1, 1),
                ('source-files', 'personal-document-root', 'personal_document', '源文件', 1, 0);

            CREATE TABLE note_library_entries (
                filename TEXT PRIMARY KEY,
                folder_id TEXT NOT NULL DEFAULT 'ai-note-root',
                source_document_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (folder_id) REFERENCES library_folders(folder_id) ON DELETE RESTRICT
            );
            CREATE INDEX idx_note_library_folder ON note_library_entries(folder_id);

            CREATE TABLE library_documents (
                document_id TEXT PRIMARY KEY,
                folder_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stored_path TEXT NOT NULL UNIQUE,
                media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                resource_id TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL CHECK (source_kind IN ('import', 'agent_source')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (folder_id) REFERENCES library_folders(folder_id) ON DELETE RESTRICT
            );
            CREATE INDEX idx_library_documents_folder ON library_documents(folder_id);
            CREATE INDEX idx_library_documents_resource ON library_documents(resource_id);
            """
        ),
    ),
    Migration(
        version=19,
        name="allow linked library documents",
        upgrade=migration_019_allow_linked_library_documents,
    ),
]

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import subprocess
import threading
import time as time_module
import uuid
import warnings
from collections import OrderedDict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageMath, ImageOps, ImageSequence, features


DEFAULT_CATEGORIES = (
    ("pending", "待处理", False),
    ("cos", "cos人像", False),
    ("scenery", "风景", False),
    ("meme", "梗图", False),
    ("nsfw", "NSFW", True),
)
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "GIF", "WEBP", "BMP"}
VIDEO_SUFFIXES = {
    "MP4": ".mp4",
    "MOV": ".mov",
    "3GP": ".3gp",
    "AVI": ".avi",
    "MKV": ".mkv",
    "WEBM": ".webm",
}
FORMAT_SUFFIXES = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
}
MAX_IMAGE_PIXELS = 160_000_000
MAX_MIRAGE_OUTPUT_EDGE = 8192
MAX_IMAGE_DECODE_PIXELS = 40_000_000
MAX_ANIMATED_IMAGE_PIXELS = 40_000_000
PAGE_SIZE_MAX = 60
PERCEPTUAL_HASH_DIMENSION = 32
PERCEPTUAL_HASH_LOW_FREQUENCIES = 8
MAX_SIMILAR_CANDIDATES = 3000


class GalleryError(ValueError):
    pass


class ProcessingTaskCancelled(Exception):
    pass


class GalleryStore:
    def __init__(
        self,
        data_dir: Path,
        max_image_size_mb: int = 20,
        max_video_size_mb: int = 100,
        max_source_image_size_mb: int = 200,
        max_source_video_size_mb: int = 500,
        compress_oversized_media: bool = True,
    ):
        self.root = Path(data_dir)
        self.images_dir = self.root / "images"
        self.thumbnails_dir = self.root / "thumbnails"
        self.staging_dir = self.root / "staging"
        self.db_path = self.root / "gallery.sqlite3"
        self.max_image_bytes = max(1, min(int(max_image_size_mb), 100)) * 1024 * 1024
        self.max_video_bytes = max(1, min(int(max_video_size_mb), 100)) * 1024 * 1024
        self.compress_oversized_media = bool(compress_oversized_media)
        self.max_source_image_bytes = max(
            self.max_image_bytes,
            max(1, min(int(max_source_image_size_mb), 500)) * 1024 * 1024,
        )
        self.max_source_video_bytes = max(
            self.max_video_bytes,
            max(1, min(int(max_source_video_size_mb), 1000)) * 1024 * 1024,
        )
        self._lock = threading.RLock()
        self._video_thumbnail_failures: set[str] = set()
        self._mirage_preview_cache: OrderedDict[tuple[int, int, int], tuple[str, int, int]] = OrderedDict()
        self._mirage_preview_cache_bytes = 0
        self._mirage_preview_cache_limit = 8 * 1024 * 1024
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    is_nsfw INTEGER NOT NULL DEFAULT 0,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
                    filename TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    image_format TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_nsfw INTEGER NOT NULL DEFAULT 0,
                    media_type TEXT NOT NULL DEFAULT 'image',
                    manual_tags TEXT NOT NULL DEFAULT '[]',
                    ai_tags TEXT NOT NULL DEFAULT '[]',
                    ai_description TEXT NOT NULL DEFAULT '',
                    description_override TEXT NOT NULL DEFAULT '',
                    ai_status TEXT NOT NULL DEFAULT 'not_evaluated',
                    ai_error TEXT NOT NULL DEFAULT '',
                    ai_provider_id TEXT NOT NULL DEFAULT '',
                    ai_updated_at TEXT NOT NULL DEFAULT '',
                    phash TEXT NOT NULL DEFAULT '',
                    UNIQUE(category_id, sha256)
                );
                CREATE TABLE IF NOT EXISTS media_tags (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    source TEXT NOT NULL CHECK (source IN ('manual', 'ai')),
                    PRIMARY KEY(image_id, tag, source)
                );
                CREATE INDEX IF NOT EXISTS idx_media_tags_tag ON media_tags(tag);
                CREATE TABLE IF NOT EXISTS tag_aliases (
                    alias TEXT PRIMARY KEY COLLATE NOCASE,
                    canonical_tag TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL,
                    CHECK (LOWER(alias) <> LOWER(canonical_tag))
                );
                CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical
                    ON tag_aliases(canonical_tag);
                CREATE TABLE IF NOT EXISTS tag_hierarchy (
                    child_tag TEXT PRIMARY KEY COLLATE NOCASE,
                    parent_tag TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL,
                    CHECK (LOWER(child_tag) <> LOWER(parent_tag))
                );
                CREATE INDEX IF NOT EXISTS idx_tag_hierarchy_parent
                    ON tag_hierarchy(parent_tag);
                CREATE TABLE IF NOT EXISTS media_embeddings (
                    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
                    scope TEXT NOT NULL CHECK (scope IN ('sfw', 'nsfw')),
                    provider_id TEXT NOT NULL,
                    provider_fingerprint TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media_trash (
                    trash_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_id INTEGER NOT NULL UNIQUE,
                    category_id TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    filename TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    image_format TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_nsfw INTEGER NOT NULL DEFAULT 0,
                    media_type TEXT NOT NULL DEFAULT 'image',
                    manual_tags TEXT NOT NULL DEFAULT '[]',
                    ai_tags TEXT NOT NULL DEFAULT '[]',
                    ai_description TEXT NOT NULL DEFAULT '',
                    description_override TEXT NOT NULL DEFAULT '',
                    ai_status TEXT NOT NULL DEFAULT 'not_evaluated',
                    ai_error TEXT NOT NULL DEFAULT '',
                    ai_provider_id TEXT NOT NULL DEFAULT '',
                    ai_updated_at TEXT NOT NULL DEFAULT '',
                    phash TEXT NOT NULL DEFAULT '',
                    trashed_at TEXT NOT NULL,
                    embedding_scope TEXT NOT NULL DEFAULT '',
                    embedding_provider_id TEXT NOT NULL DEFAULT '',
                    embedding_fingerprint TEXT NOT NULL DEFAULT '',
                    embedding_dimension INTEGER NOT NULL DEFAULT 0,
                    embedding_vector BLOB,
                    embedding_created_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_media_trash_trashed_at
                    ON media_trash(trashed_at DESC, trash_id DESC);
                CREATE TABLE IF NOT EXISTS deleted_builtin_categories (
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS plugin_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processing_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    media_id INTEGER,
                    scope TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    model_id TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL DEFAULT '',
                    batch_id TEXT NOT NULL DEFAULT '',
                    retry_of TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT '',
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_processing_tasks_created
                    ON processing_tasks(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_processing_tasks_batch
                    ON processing_tasks(batch_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_processing_tasks_media
                    ON processing_tasks(media_id, task_type, status);
                CREATE INDEX IF NOT EXISTS idx_images_category_created
                    ON images(category_id, id DESC);
                """
            )
            image_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(images)")
            }
            if "is_nsfw" not in image_columns:
                db.execute(
                    "ALTER TABLE images ADD COLUMN is_nsfw INTEGER NOT NULL DEFAULT 0"
                )
            if "media_type" not in image_columns:
                db.execute(
                    "ALTER TABLE images ADD COLUMN media_type TEXT NOT NULL DEFAULT 'image'"
                )
            for column, definition in (
                ("manual_tags", "TEXT NOT NULL DEFAULT '[]'"),
                ("ai_tags", "TEXT NOT NULL DEFAULT '[]'"),
                ("ai_description", "TEXT NOT NULL DEFAULT ''"),
                ("description_override", "TEXT NOT NULL DEFAULT ''"),
                ("ai_status", "TEXT NOT NULL DEFAULT 'not_evaluated'"),
                ("ai_error", "TEXT NOT NULL DEFAULT ''"),
                ("ai_provider_id", "TEXT NOT NULL DEFAULT ''"),
                ("ai_updated_at", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in image_columns:
                    db.execute(f"ALTER TABLE images ADD COLUMN {column} {definition}")
            if "phash" not in image_columns:
                db.execute("ALTER TABLE images ADD COLUMN phash TEXT NOT NULL DEFAULT ''")
            trash_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(media_trash)")
            }
            if "phash" not in trash_columns:
                db.execute("ALTER TABLE media_trash ADD COLUMN phash TEXT NOT NULL DEFAULT ''")
            task_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(processing_tasks)")
            }
            if "retry_of" not in task_columns:
                db.execute(
                    "ALTER TABLE processing_tasks ADD COLUMN retry_of TEXT NOT NULL DEFAULT ''"
                )
            db.execute("CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash)")
            now = self._now()
            deleted_builtins = {
                row["id"]
                for row in db.execute("SELECT id FROM deleted_builtin_categories")
            }
            for category_id, name, is_nsfw in DEFAULT_CATEGORIES:
                if category_id in deleted_builtins:
                    continue
                db.execute(
                    """INSERT OR IGNORE INTO categories
                       (id, name, is_nsfw, is_builtin, created_at)
                       VALUES (?, ?, ?, 1, ?)""",
                    (category_id, name, int(is_nsfw), now),
                )
            db.execute(
                "UPDATE categories SET is_nsfw = 1 WHERE name = 'NSFW' COLLATE NOCASE"
            )
            db.execute(
                """UPDATE images SET is_nsfw = 1
                   WHERE category_id IN (
                       SELECT id FROM categories WHERE is_nsfw = 1
                   )"""
            )
            db.execute(
                """UPDATE images SET ai_status = 'manual_required'
                   WHERE is_nsfw = 1 AND ai_status IN ('pending', 'not_evaluated')"""
            )
        self._cleanup_orphans()

    def mark_interrupted_processing_tasks(self) -> int:
        now = self._now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """UPDATE processing_tasks
                   SET status = 'failed', progress = 0,
                       message = '插件重载时任务中断，可从任务中心重试。',
                       error = '插件重载时任务中断。', updated_at = ?,
                       completed_at = ?, cancel_requested = 1
                   WHERE status IN ('queued', 'running')""",
                (now, now),
            )
            return cursor.rowcount

    def create_processing_task(
        self,
        task_type: str,
        *,
        media_id: int | None = None,
        scope: str = "",
        model_id: str = "",
        prompt_version: str = "",
        batch_id: str = "",
        retry_of: str = "",
        source_path: str = "",
        metadata: dict | None = None,
        message: str = "等待处理",
    ) -> str:
        task_id = uuid.uuid4().hex
        now = self._now()
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO processing_tasks
                   (task_id, task_type, media_id, scope, status, progress, message,
                    model_id, prompt_version, batch_id, retry_of, source_path, metadata_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    str(task_type),
                    int(media_id) if media_id is not None else None,
                    str(scope or ""),
                    str(message or "等待处理")[:500],
                    str(model_id or "")[:255],
                    str(prompt_version or "")[:80],
                    str(batch_id or "")[:80],
                    str(retry_of or "")[:80],
                    str(source_path or ""),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return task_id

    def update_processing_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        error: str | None = None,
        media_id: int | None = None,
        source_path: str | None = None,
        allow_terminal_update: bool = False,
    ) -> bool:
        now = self._now()
        terminal = {"succeeded", "failed", "cancelled", "skipped"}
        updates = ["updated_at = ?"]
        values: list[object] = [now]
        if status is not None:
            status = str(status)
            updates.append("status = ?")
            values.append(status)
            if status == "running":
                updates.append("started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END")
                values.append(now)
            if status in terminal:
                updates.append("completed_at = ?")
                values.append(now)
        if progress is not None:
            updates.append("progress = ?")
            values.append(max(0, min(int(progress), 100)))
        if message is not None:
            updates.append("message = ?")
            values.append(str(message)[:500])
        if error is not None:
            updates.append("error = ?")
            values.append(str(error)[:2000])
        if media_id is not None:
            updates.append("media_id = ?")
            values.append(int(media_id))
        if source_path is not None:
            updates.append("source_path = ?")
            values.append(str(source_path))
        values.append(str(task_id))
        where = "task_id = ?"
        if not allow_terminal_update:
            where += " AND status NOT IN ('succeeded', 'failed', 'cancelled', 'skipped')"
        with self._lock, self._connect() as db:
            cursor = db.execute(
                f"UPDATE processing_tasks SET {', '.join(updates)} WHERE {where}",
                values,
            )
            return cursor.rowcount > 0

    def get_processing_task(self, task_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM processing_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        return dict(row) if row else None

    def latest_processing_task(self, media_id: int, task_type: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT * FROM processing_tasks
                   WHERE media_id = ? AND task_type = ?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (int(media_id), str(task_type)),
            ).fetchone()
        return dict(row) if row else None

    def processing_task_cancel_requested(self, task_id: str) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT cancel_requested FROM processing_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def request_processing_task_cancel(self, task_id: str) -> bool:
        now = self._now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """UPDATE processing_tasks SET cancel_requested = 1,
                   message = '正在取消…', updated_at = ?
                   WHERE task_id = ? AND status IN ('queued', 'running')""",
                (now, str(task_id)),
            )
            return cursor.rowcount > 0

    def request_cancel_all_active_processing_tasks(self) -> int:
        now = self._now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """UPDATE processing_tasks SET cancel_requested = 1,
                   message = '插件正在关闭，任务将停止。', updated_at = ?
                   WHERE status IN ('queued', 'running')""",
                (now,),
            )
            return cursor.rowcount

    def list_processing_tasks(self, limit: int = 150) -> list[dict]:
        limit = max(1, min(int(limit), 300))
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT t.*, CASE WHEN i.id IS NULL THEN 0 ELSE 1 END AS media_exists,
                          EXISTS (SELECT 1 FROM processing_tasks retry
                                  WHERE retry.retry_of = t.task_id) AS has_retry
                   FROM processing_tasks t LEFT JOIN images i ON i.id = t.media_id
                   ORDER BY t.created_at DESC, t.rowid DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["metadata"] = {}
                item.pop("metadata_json", None)
            task_type = item["task_type"]
            retryable_state = item["status"] in {"failed", "cancelled"}
            has_retry = bool(item.get("has_retry"))
            source_available = bool(item.get("source_path") and Path(item["source_path"]).is_file())
            can_retry = retryable_state and not has_retry and (
                (task_type == "compression" and source_available)
                or (task_type in {"video_preview", "ai_evaluation", "semantic_index"}
                    and bool(item.get("media_id") and item.get("media_exists")))
            )
            item["can_retry"] = can_retry
            item["can_cancel"] = item["status"] in {"queued", "running"}
            item["has_retry"] = has_retry
            item["source_available"] = source_available
            item.pop("source_path", None)
            item.pop("cancel_requested", None)
            item.pop("media_exists", None)
            result.append(item)
        return result

    def processing_task_batch_summary(self, batch_id: str) -> dict:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS amount FROM processing_tasks WHERE batch_id = ? GROUP BY status",
                (str(batch_id),),
            ).fetchall()
        counts = {str(row["status"]): int(row["amount"]) for row in rows}
        total = sum(counts.values())
        processed = sum(counts.get(status, 0) for status in ("succeeded", "failed", "cancelled", "skipped"))
        active = counts.get("queued", 0) + counts.get("running", 0)
        return {
            "total": total,
            "processed": processed,
            "indexed": counts.get("succeeded", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "active": active,
        }

    def stale_evaluation_candidates(
        self, scope: str, model_id: str, prompt_version: str
    ) -> list[int]:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("评估范围无效。")
        scope_filter = (
            "(i.is_nsfw = 1 OR c.is_nsfw = 1)"
            if scope == "nsfw"
            else "(i.is_nsfw = 0 AND c.is_nsfw = 0 AND c.id <> 'pending')"
        )
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.id,
                         (SELECT t.model_id FROM processing_tasks t
                          WHERE t.media_id = i.id AND t.task_type = 'ai_evaluation'
                            AND t.status = 'succeeded'
                          ORDER BY t.completed_at DESC, t.created_at DESC LIMIT 1) AS last_model,
                         (SELECT t.prompt_version FROM processing_tasks t
                          WHERE t.media_id = i.id AND t.task_type = 'ai_evaluation'
                            AND t.status = 'succeeded'
                          ORDER BY t.completed_at DESC, t.created_at DESC LIMIT 1) AS last_prompt
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE {scope_filter} AND i.ai_description <> ''
                     AND i.description_override = ''
                   ORDER BY i.id"""
            ).fetchall()
        return [
            int(row["id"])
            for row in rows
            if str(row["last_model"] or "") != str(model_id)
            or str(row["last_prompt"] or "") != str(prompt_version)
        ]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _decode_tags(raw: str | None) -> list[str]:
        try:
            values = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        return [str(value) for value in values if isinstance(value, str)]

    @staticmethod
    def normalize_tags(value: object) -> list[str]:
        if isinstance(value, str):
            raw_tags = value.replace("，", ",").replace("、", ",").split(",")
        elif isinstance(value, list):
            raw_tags = value
        else:
            raise GalleryError("标签格式无效，请用逗号分隔标签。")
        tags: list[str] = []
        seen: set[str] = set()
        for raw_tag in raw_tags:
            if not isinstance(raw_tag, str):
                continue
            tag = " ".join(raw_tag.strip().split())
            if not tag:
                continue
            if len(tag) > 32:
                raise GalleryError("单个标签不能超过 32 个字符。")
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                tags.append(tag)
        if len(tags) > 30:
            raise GalleryError("每个媒体最多保留 30 个标签。")
        return tags

    @staticmethod
    def _sync_tag_index(
        db: sqlite3.Connection,
        image_id: int,
        manual_tags: list[str],
        ai_tags: list[str],
    ) -> None:
        db.execute("DELETE FROM media_tags WHERE image_id = ?", (image_id,))
        db.executemany(
            "INSERT OR IGNORE INTO media_tags (image_id, tag, source) VALUES (?, ?, ?)",
            [(image_id, tag, "manual") for tag in manual_tags]
            + [(image_id, tag, "ai") for tag in ai_tags],
        )

    @staticmethod
    def _tag_name(value: object, label: str) -> str:
        if not isinstance(value, str):
            raise GalleryError(f"{label}必须是文本。")
        tags = GalleryStore.normalize_tags([value])
        if len(tags) != 1:
            raise GalleryError(f"请输入一个有效的{label}。")
        return tags[0]

    @staticmethod
    def _expanded_tag_terms(db: sqlite3.Connection, value: str) -> list[str]:
        query = " ".join(str(value or "").strip().split())
        if not query:
            return []
        alias_rows = db.execute(
            "SELECT alias, canonical_tag FROM tag_aliases ORDER BY alias COLLATE NOCASE"
        ).fetchall()
        alias_to_canonical = {
            str(row["alias"]).casefold(): str(row["canonical_tag"])
            for row in alias_rows
        }
        canonical_to_aliases: dict[str, list[str]] = {}
        for row in alias_rows:
            canonical_to_aliases.setdefault(
                str(row["canonical_tag"]).casefold(), []
            ).append(str(row["alias"]))

        query_key = query.casefold()
        canonical_root = alias_to_canonical.get(query_key, query)
        terms = {query}
        child_rows = db.execute(
            "SELECT child_tag, parent_tag FROM tag_hierarchy"
        ).fetchall()
        children: dict[str, list[str]] = {}
        hierarchy_nodes = set()
        for row in child_rows:
            child = str(row["child_tag"])
            parent = str(row["parent_tag"])
            children.setdefault(parent.casefold(), []).append(child)
            hierarchy_nodes.add(child.casefold())
            hierarchy_nodes.add(parent.casefold())
        has_alias_mapping = (
            query_key in alias_to_canonical
            or any(str(row["canonical_tag"]).casefold() == query_key for row in alias_rows)
        )
        if has_alias_mapping or canonical_root.casefold() in hierarchy_nodes:
            terms.add(canonical_root)
            terms.update(canonical_to_aliases.get(canonical_root.casefold(), []))

            pending = [canonical_root]
            seen = {canonical_root.casefold()}
            while pending:
                parent = pending.pop()
                for child in children.get(parent.casefold(), []):
                    child_key = child.casefold()
                    if child_key in seen:
                        continue
                    seen.add(child_key)
                    terms.add(child)
                    terms.update(canonical_to_aliases.get(child_key, []))
                    pending.append(child)
        return sorted(terms, key=str.casefold)

    def tag_taxonomy(self) -> dict:
        with self._lock, self._connect() as db:
            aliases = [
                {"alias": row["alias"], "canonical_tag": row["canonical_tag"]}
                for row in db.execute(
                    "SELECT alias, canonical_tag FROM tag_aliases ORDER BY alias COLLATE NOCASE"
                )
            ]
            hierarchy = [
                {"child_tag": row["child_tag"], "parent_tag": row["parent_tag"]}
                for row in db.execute(
                    "SELECT child_tag, parent_tag FROM tag_hierarchy ORDER BY parent_tag COLLATE NOCASE, child_tag COLLATE NOCASE"
                )
            ]
            usage = {
                str(row["tag"]): int(row["usage_count"])
                for row in db.execute(
                    """SELECT tag, COUNT(*) AS usage_count FROM media_tags
                       GROUP BY tag ORDER BY usage_count DESC, tag COLLATE NOCASE LIMIT 1000"""
                )
            }
        for entry in aliases:
            usage.setdefault(entry["canonical_tag"], 0)
        for entry in hierarchy:
            usage.setdefault(entry["child_tag"], 0)
            usage.setdefault(entry["parent_tag"], 0)
        suggestions = [
            {"tag": tag, "usage_count": count}
            for tag, count in sorted(
                usage.items(), key=lambda item: (-item[1], item[0].casefold())
            )
        ]
        return {"aliases": aliases, "hierarchy": hierarchy, "suggestions": suggestions}

    def save_tag_alias(self, alias: object, canonical_tag: object) -> dict:
        alias = self._tag_name(alias, "别名")
        canonical_tag = self._tag_name(canonical_tag, "规范标签")
        alias_key = alias.casefold()
        canonical_key = canonical_tag.casefold()
        if alias_key == canonical_key:
            raise GalleryError("别名和规范标签不能相同。")
        with self._lock, self._connect() as db:
            if db.execute(
                "SELECT 1 FROM tag_aliases WHERE alias = ? COLLATE NOCASE",
                (canonical_tag,),
            ).fetchone():
                raise GalleryError("规范标签不能本身也是别名，请改用其对应的规范标签。")
            if db.execute(
                """SELECT 1 FROM tag_aliases
                   WHERE canonical_tag = ? COLLATE NOCASE
                     AND alias <> ? COLLATE NOCASE LIMIT 1""",
                (alias, alias),
            ).fetchone():
                raise GalleryError("该名称已作为其他别名的规范标签，不能再设为别名。")
            if db.execute(
                """SELECT 1 FROM tag_hierarchy
                   WHERE child_tag = ? COLLATE NOCASE
                      OR parent_tag = ? COLLATE NOCASE LIMIT 1""",
                (alias, alias),
            ).fetchone():
                raise GalleryError("该名称已用于标签层级，请先调整层级关系再设为别名。")
            db.execute(
                """INSERT INTO tag_aliases (alias, canonical_tag, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(alias) DO UPDATE SET
                     canonical_tag = excluded.canonical_tag,
                     created_at = excluded.created_at""",
                (alias, canonical_tag, self._now()),
            )
        return {"alias": alias, "canonical_tag": canonical_tag}

    def delete_tag_alias(self, alias: object) -> bool:
        alias = self._tag_name(alias, "别名")
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "DELETE FROM tag_aliases WHERE alias = ? COLLATE NOCASE", (alias,)
            )
            return cursor.rowcount > 0

    def save_tag_parent(self, child_tag: object, parent_tag: object) -> dict:
        child = self._tag_name(child_tag, "子标签")
        parent = self._tag_name(parent_tag, "父标签")
        child_key = child.casefold()
        parent_key = parent.casefold()
        if child_key == parent_key:
            raise GalleryError("子标签和父标签不能相同。")
        with self._lock, self._connect() as db:
            alias_names = {
                str(row["alias"]).casefold()
                for row in db.execute("SELECT alias FROM tag_aliases")
            }
            if child_key in alias_names or parent_key in alias_names:
                raise GalleryError("层级关系请使用规范标签名称，不能使用别名。")
            parent_map = {
                str(row["child_tag"]).casefold(): str(row["parent_tag"])
                for row in db.execute("SELECT child_tag, parent_tag FROM tag_hierarchy")
                if str(row["child_tag"]).casefold() != child_key
            }
            parent_map[child_key] = parent
            current = parent
            visited = {child_key}
            while current:
                current_key = current.casefold()
                if current_key in visited:
                    raise GalleryError("该层级关系会形成循环。")
                visited.add(current_key)
                current = parent_map.get(current_key, "")
            db.execute(
                """INSERT INTO tag_hierarchy (child_tag, parent_tag, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(child_tag) DO UPDATE SET
                     parent_tag = excluded.parent_tag,
                     created_at = excluded.created_at""",
                (child, parent, self._now()),
            )
        return {"child_tag": child, "parent_tag": parent}

    def delete_tag_parent(self, child_tag: object) -> bool:
        child = self._tag_name(child_tag, "子标签")
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "DELETE FROM tag_hierarchy WHERE child_tag = ? COLLATE NOCASE",
                (child,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _normalization_plan(db: sqlite3.Connection) -> dict:
        alias_rows = db.execute(
            "SELECT alias, canonical_tag FROM tag_aliases ORDER BY alias COLLATE NOCASE"
        ).fetchall()
        alias_map = {
            str(row["alias"]).casefold(): (str(row["alias"]), str(row["canonical_tag"]))
            for row in alias_rows
        }
        counts: dict[str, int] = {}
        changes = []
        for table, id_column, query in (
            ("images", "id", "SELECT id, manual_tags, ai_tags FROM images ORDER BY id"),
            ("media_trash", "original_id", "SELECT original_id, manual_tags, ai_tags FROM media_trash ORDER BY trash_id"),
        ):
            for row in db.execute(query):
                old_manual = GalleryStore._decode_tags(row["manual_tags"])
                old_ai = GalleryStore._decode_tags(row["ai_tags"])

                def replace_aliases(tags):
                    output = []
                    seen = set()
                    changed = False
                    for tag in tags:
                        rule = alias_map.get(tag.casefold())
                        if rule:
                            _, canonical = rule
                            counts[rule[0]] = counts.get(rule[0], 0) + 1
                            changed = True
                        else:
                            canonical = tag
                        key = canonical.casefold()
                        if key not in seen:
                            seen.add(key)
                            output.append(canonical)
                        elif canonical.casefold() != tag.casefold():
                            changed = True
                        if canonical != tag:
                            changed = True
                    return output, changed

                new_manual, manual_changed = replace_aliases(old_manual)
                new_ai, ai_changed = replace_aliases(old_ai)
                if manual_changed or ai_changed:
                    changes.append({
                        "table": table,
                        "id_column": id_column,
                        "id": int(row[id_column]),
                        "manual_tags": new_manual,
                        "ai_tags": new_ai,
                        "ai_changed": ai_changed,
                    })
        token_payload = [
            [
                change["table"],
                change["id"],
                change["manual_tags"],
                change["ai_tags"],
                change["ai_changed"],
            ]
            for change in changes
        ]
        token = hashlib.sha256(
            json.dumps(token_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "token": token,
            "changes": changes,
            "updated_media": len(changes),
            "updated_tags": sum(counts.values()),
            "by_alias": [
                {
                    "alias": str(row["alias"]),
                    "canonical_tag": str(row["canonical_tag"]),
                    "occurrences": counts.get(str(row["alias"]), 0),
                }
                for row in alias_rows
            ],
            "ai_changed_ids": [
                change["id"] for change in changes
                if change["table"] == "images" and change["ai_changed"]
            ],
        }

    def preview_tag_normalization(self) -> dict:
        with self._lock, self._connect() as db:
            plan = self._normalization_plan(db)
            active_ids = plan.pop("ai_changed_ids")
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                plan["invalidated_embeddings"] = int(db.execute(
                    f"SELECT COUNT(*) FROM media_embeddings WHERE image_id IN ({placeholders})",
                    active_ids,
                ).fetchone()[0])
            else:
                plan["invalidated_embeddings"] = 0
            plan.pop("changes")
            plan["plan_token"] = plan.pop("token")
            return plan

    def normalize_tag_aliases(self, plan_token: object) -> dict:
        token = str(plan_token or "").strip()
        if len(token) != 64:
            raise GalleryError("规范化预览已失效，请重新预览。")
        with self._lock, self._connect() as db:
            plan = self._normalization_plan(db)
            if plan["token"] != token:
                raise GalleryError("标签或别名规则已有变化，请重新预览后确认。")
            alias_keys = {
                entry["alias"].casefold() for entry in plan["by_alias"]
            }
            updated_media = 0
            updated_tags = 0
            invalidated_embeddings = 0
            for change in plan["changes"]:
                table = change["table"]
                id_column = change["id_column"]
                media_id = change["id"]
                row = db.execute(
                    f"SELECT manual_tags, ai_tags FROM {table} WHERE {id_column} = ?",
                    (media_id,),
                ).fetchone()
                if not row:
                    continue
                old_manual = self._decode_tags(row["manual_tags"])
                old_ai = self._decode_tags(row["ai_tags"])
                new_manual = change["manual_tags"]
                new_ai = change["ai_tags"]
                updated_tags += sum(
                    1 for tag in old_manual if tag.casefold() in alias_keys
                )
                updated_tags += sum(
                    1 for tag in old_ai if tag.casefold() in alias_keys
                )
                if table == "images":
                    db.execute(
                        "UPDATE images SET manual_tags = ?, ai_tags = ? WHERE id = ?",
                        (
                            json.dumps(new_manual, ensure_ascii=False),
                            json.dumps(new_ai, ensure_ascii=False),
                            media_id,
                        ),
                    )
                    self._sync_tag_index(db, media_id, new_manual, new_ai)
                    if change["ai_changed"]:
                        cursor = db.execute(
                            "DELETE FROM media_embeddings WHERE image_id = ?",
                            (media_id,),
                        )
                        invalidated_embeddings += cursor.rowcount
                else:
                    db.execute(
                        """UPDATE media_trash SET manual_tags = ?, ai_tags = ?
                           WHERE original_id = ?""",
                        (
                            json.dumps(new_manual, ensure_ascii=False),
                            json.dumps(new_ai, ensure_ascii=False),
                            media_id,
                        ),
                    )
                updated_media += 1
            return {
                "updated_media": updated_media,
                "updated_tags": updated_tags,
                "invalidated_embeddings": invalidated_embeddings,
            }

    def _cleanup_orphans(self) -> None:
        with self._lock, self._connect() as db:
            known = {row[0] for row in db.execute("SELECT filename FROM images")}
            known.update(row[0] for row in db.execute("SELECT filename FROM media_trash"))
        for path in self.images_dir.iterdir():
            if path.is_file() and path.name not in known:
                try:
                    path.unlink()
                except OSError:
                    pass
        for path in self.staging_dir.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _category_dict(row: sqlite3.Row, image_count: int = 0) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "is_nsfw": bool(row["is_nsfw"]),
            "is_builtin": bool(row["is_builtin"]),
            "image_count": image_count,
        }

    def categories(self, include_nsfw: bool = True) -> list[dict]:
        count_expr = (
            "COUNT(i.id)"
            if include_nsfw
            else "SUM(CASE WHEN i.is_nsfw = 0 THEN 1 ELSE 0 END)"
        )
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT c.*, {count_expr} AS image_count
                   FROM categories c LEFT JOIN images i ON i.category_id = c.id
                   GROUP BY c.id ORDER BY c.is_builtin DESC, c.name COLLATE NOCASE"""
            ).fetchall()
        return [
            self._category_dict(row, row["image_count"] or 0) for row in rows
        ]

    def category_by_name(self, name: str) -> dict | None:
        name = str(name).strip()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM categories WHERE id = ? OR name = ? COLLATE NOCASE",
                (name, name),
            ).fetchone()
        return self._category_dict(row) if row else None

    def category_by_id(self, category_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM categories WHERE id = ?", (str(category_id),)
            ).fetchone()
        return self._category_dict(row) if row else None

    def create_category(self, name: str, is_nsfw: bool = False) -> dict:
        name = str(name).strip()
        if not name or len(name) > 32 or any(ch.isspace() for ch in name):
            raise GalleryError("分类名需为 1–32 个字符，且不能包含空格。")
        if any(ch in name for ch in "/\\\0") or name in {".", ".."}:
            raise GalleryError("分类名包含不支持的字符。")
        is_nsfw = bool(is_nsfw) or name.casefold() == "nsfw"
        category_id = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            try:
                db.execute(
                    """INSERT INTO categories (id, name, is_nsfw, is_builtin, created_at)
                       VALUES (?, ?, ?, 0, ?)""",
                    (category_id, name, int(bool(is_nsfw)), self._now()),
                )
            except sqlite3.IntegrityError as exc:
                raise GalleryError("已有同名分类。") from exc
        return self.category_by_id(category_id) or {}

    def get_or_create_category(self, name: str) -> dict:
        name = str(name).strip()
        existing = self.category_by_name(name)
        if existing:
            return existing
        try:
            return self.create_category(name, is_nsfw=name.casefold() == "nsfw")
        except GalleryError:
            # A concurrent save may have created this category meanwhile.
            existing = self.category_by_name(name)
            if existing:
                return existing
            raise

    def ensure_nsfw_category(self, name: str) -> dict:
        name = str(name).strip()
        category = self.category_by_name(name)
        if not category:
            try:
                return self.create_category(name, is_nsfw=True)
            except GalleryError:
                category = self.category_by_name(name)
                if not category:
                    raise
        if category["is_nsfw"]:
            return category

        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT id FROM categories WHERE id = ?", (category["id"],)
            ).fetchone()
            if not row:
                raise GalleryError("找不到目标分类。")
            db.execute(
                "UPDATE categories SET is_nsfw = 1 WHERE id = ?",
                (category["id"],),
            )
            db.execute(
                "UPDATE images SET is_nsfw = 1 WHERE category_id = ?",
                (category["id"],),
            )
            db.execute(
                """UPDATE media_embeddings SET scope = 'nsfw'
                   WHERE image_id IN (
                       SELECT id FROM images WHERE category_id = ?
                   )""",
                (category["id"],),
            )
            db.execute(
                """UPDATE media_trash SET is_nsfw = 1,
                       embedding_scope = CASE
                           WHEN embedding_vector IS NOT NULL THEN 'nsfw'
                           ELSE embedding_scope
                       END
                   WHERE category_id = ?""",
                (category["id"],),
            )
        return self.category_by_id(category["id"]) or {}

    def delete_category(self, category_id: str) -> dict:
        if str(category_id) == "pending":
            raise GalleryError("“待处理”是媒体回收分类，不能删除。")

        redundant_files: list[str] = []
        moved = 0
        merged = 0
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if not row:
                raise GalleryError("找不到该分类。")
            pending = db.execute(
                "SELECT * FROM categories WHERE id = 'pending'"
            ).fetchone()
            if not pending:
                raise GalleryError("找不到“待处理”分类，无法安全迁移媒体。")

            pending_hashes = {
                image["sha256"]
                for image in db.execute(
                    "SELECT sha256 FROM images WHERE category_id = 'pending'"
                )
            }
            images = db.execute(
                "SELECT id, filename, sha256 FROM images WHERE category_id = ?",
                (category_id,),
            ).fetchall()
            for image in images:
                if image["sha256"] in pending_hashes:
                    db.execute("DELETE FROM images WHERE id = ?", (image["id"],))
                    redundant_files.append(image["filename"])
                    merged += 1
                else:
                    db.execute(
                        "UPDATE images SET category_id = 'pending' WHERE id = ?",
                        (image["id"],),
                    )
                    pending_hashes.add(image["sha256"])
                    moved += 1
            if row["is_builtin"]:
                db.execute(
                    "INSERT OR IGNORE INTO deleted_builtin_categories (id) VALUES (?)",
                    (row["id"],),
                )
            db.execute("DELETE FROM categories WHERE id = ?", (category_id,))

        for filename in redundant_files:
            try:
                (self.images_dir / filename).unlink(missing_ok=True)
            except OSError:
                pass
            self._remove_media_thumbnails(filename)
        return {"deleted": True, "moved": moved, "merged": merged}

    def _inspect_image(
        self, path: Path, max_bytes: int | None = None
    ) -> tuple[str, int, int, int]:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise GalleryError("无法读取图片文件。") from exc
        if size <= 0:
            raise GalleryError("图片文件为空。")
        size_limit = self.max_image_bytes if max_bytes is None else int(max_bytes)
        if size > size_limit:
            raise GalleryError(
                f"图片文件不能超过 {size_limit // (1024 * 1024)} MB。"
            )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(path) as img:
                    image_format = str(img.format or "").upper()
                    width, height = img.size
                    if image_format not in ALLOWED_FORMATS:
                        raise GalleryError("仅支持 JPG、MPO、PNG、GIF、WebP 和 BMP 图片。")
                    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                        raise GalleryError("图片尺寸过大，无法安全处理。")
                    img.verify()
        except GalleryError:
            raise
        except Image.DecompressionBombError as exc:
            raise GalleryError("图片像素超过安全处理上限，未入库。") from exc
        except Exception as exc:
            raise GalleryError("文件不是有效的受支持图片。") from exc
        return image_format, width, height, size

    def _normalize_mpo_to_jpeg(self, path: Path) -> bool:
        """Extract an MPO's primary picture and replace it with a standard JPEG."""
        temporary_path = self.staging_dir / f"mpo-normalized-{uuid.uuid4().hex}.jpg"
        frame: Image.Image | None = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    if str(source.format or "").upper() != "MPO":
                        return False
                    source_pixels = source.width * source.height
                    if (
                        source.width <= 0
                        or source.height <= 0
                        or source_pixels > MAX_IMAGE_PIXELS
                    ):
                        raise GalleryError("MPO 主画面尺寸超过图片安全上限。")
                    source.seek(0)
                    if source_pixels > MAX_IMAGE_DECODE_PIXELS:
                        source.draft(
                            "RGB",
                            (max(1, source.width // 2), max(1, source.height // 2)),
                        )
                        if source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                            raise GalleryError(
                                "MPO 主画面超过安全解码上限，请先缩小后再导入。"
                            )
                    icc_profile = source.info.get("icc_profile")
                    frame = ImageOps.exif_transpose(source.copy()).convert("RGB")
                    save_options: dict[str, object] = {
                        "format": "JPEG",
                        "quality": 95,
                        "optimize": True,
                    }
                    exif = frame.getexif().tobytes()
                    if exif:
                        save_options["exif"] = exif
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    frame.save(temporary_path, **save_options)
            os.replace(temporary_path, path)
            return True
        except GalleryError:
            raise
        except Image.DecompressionBombError as exc:
            raise GalleryError("MPO 主画面像素超过安全处理上限。") from exc
        except Exception as exc:
            raise GalleryError("MPO 主画面转为标准 JPEG 失败。") from exc
        finally:
            if frame is not None:
                frame.close()
            temporary_path.unlink(missing_ok=True)

    def _inspect_video(
        self, path: Path, max_bytes: int | None = None
    ) -> tuple[str, int, int, int]:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise GalleryError("无法读取视频文件。") from exc
        if size < 12:
            raise GalleryError("视频文件不完整。")
        size_limit = self.max_video_bytes if max_bytes is None else int(max_bytes)
        if size > size_limit:
            raise GalleryError(
                f"视频文件不能超过 {size_limit // (1024 * 1024)} MB。"
            )
        try:
            with path.open("rb") as file:
                header = file.read(4096)
        except OSError as exc:
            raise GalleryError("无法读取视频文件。") from exc

        video_format = None
        if header[4:8] == b"ftyp":
            brand = header[8:12].lower()
            compatible_brands = header[8:64].lower()
            if b"avif" in compatible_brands or b"avis" in compatible_brands:
                raise GalleryError("AVIF 是图片格式，不作为视频收藏。")
            if brand.startswith(b"3g"):
                video_format = "3GP"
            elif brand == b"qt  ":
                video_format = "MOV"
            else:
                video_format = "MP4"
        elif header[:4] == b"RIFF" and header[8:12] == b"AVI ":
            video_format = "AVI"
        elif header.startswith(b"\x1a\x45\xdf\xa3"):
            video_format = "WEBM" if b"webm" in header.lower() else "MKV"

        if not video_format:
            raise GalleryError("仅支持 MP4、MOV、3GP、AVI、MKV 和 WebM 视频。")
        return video_format, 0, 0, size

    def _compress_image_to_target(
        self,
        source_path: Path,
        target_bytes: int,
        progress_callback=None,
        cancel_check=None,
    ) -> Path:
        output_path: Path | None = None
        current_frames: list[Image.Image] = []
        succeeded = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(source_path) as source:
                    frame_count = int(getattr(source, "n_frames", 1))
                    animated = frame_count > 1
                    source_pixels = source.width * source.height
                    if animated and source_pixels * frame_count > MAX_ANIMATED_IMAGE_PIXELS:
                        raise GalleryError(
                            "动图解码后的总像素过多，未执行压缩；请先缩小或转换该动图。"
                        )
                    if not animated and source_pixels > MAX_IMAGE_DECODE_PIXELS:
                        if str(source.format or "").upper() != "JPEG":
                            raise GalleryError(
                                "超大非 JPEG 图片无法在当前安全解码上限内压缩；请先转为 JPG 或缩小分辨率。"
                            )
                        source.draft(
                            "RGB",
                            (
                                max(1, source.width // 2),
                                max(1, source.height // 2),
                            ),
                        )
                        if source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                            raise GalleryError(
                                "当前 Pillow 无法将超大 JPEG 安全降采样，未入库；请更新 Pillow 或先缩小图片。"
                            )
                    has_alpha = "A" in source.getbands() or "transparency" in source.info
                    output_format = "WEBP" if animated or has_alpha else "JPEG"
                    if not features.check("webp"):
                        if output_format == "WEBP":
                            raise GalleryError(
                                "当前 Pillow 不支持 WebP 编码，无法压缩透明图片或动图。"
                            )
                    if animated and not features.check("webp_anim"):
                        raise GalleryError(
                            "当前 Pillow 不支持动画 WebP 编码，无法压缩动图。"
                        )

                    durations: list[int] = []
                    current_frames = []
                    for frame_index, frame in enumerate(ImageSequence.Iterator(source)):
                        if cancel_check and cancel_check("compression"):
                            raise ProcessingTaskCancelled("压缩任务已取消。")
                        if (
                            progress_callback
                            and frame_index % max(1, frame_count // 10) == 0
                        ):
                            progress_callback(
                                "compression",
                                min(35, 20 + round(15 * (frame_index + 1) / max(1, frame_count))),
                                f"正在解码图片画面（{frame_index + 1}/{frame_count}）",
                            )
                        converted = ImageOps.exif_transpose(frame.copy())
                        current_frames.append(
                            converted.convert("RGBA" if has_alpha else "RGB")
                        )
                        try:
                            duration = int(
                                frame.info.get(
                                    "duration", source.info.get("duration", 100)
                                )
                            )
                        except (TypeError, ValueError):
                            duration = 100
                        durations.append(max(20, duration))
                    loop = int(source.info.get("loop", 0) or 0)

            if not current_frames:
                raise GalleryError("图片没有可压缩的画面。")
            base_width, base_height = current_frames[0].size
            suffix = ".webp" if output_format == "WEBP" else ".jpg"
            output_path = self.staging_dir / f"compressed-{uuid.uuid4().hex}{suffix}"
            scales = (1.0, 0.85, 0.70, 0.55, 0.40, 0.30, 0.20)
            qualities = (82, 66, 50, 34, 24)
            previous_scale = 1.0

            attempt = 0
            attempts_total = len(scales) * len(qualities)
            for scale in scales:
                if cancel_check and cancel_check("compression"):
                    raise ProcessingTaskCancelled("压缩任务已取消。")
                if scale < previous_scale:
                    width = max(1, round(base_width * scale))
                    height = max(1, round(base_height * scale))
                    resized_frames: list[Image.Image] = []
                    for frame_index, frame in enumerate(current_frames):
                        if cancel_check and cancel_check("compression"):
                            raise ProcessingTaskCancelled("压缩任务已取消。")
                        resized_frames.append(
                            frame.resize((width, height), Image.Resampling.LANCZOS)
                        )
                        frame.close()
                    current_frames = resized_frames
                    previous_scale = scale

                for quality in qualities:
                    attempt += 1
                    if cancel_check and cancel_check("compression"):
                        raise ProcessingTaskCancelled("压缩任务已取消。")
                    if progress_callback:
                        progress_callback(
                            "compression",
                            min(92, 25 + round(65 * attempt / attempts_total)),
                            f"正在压缩图片（第 {attempt}/{attempts_total} 轮）",
                        )
                    save_options: dict[str, object] = {
                        "format": output_format,
                        "quality": quality,
                    }
                    if output_format == "WEBP":
                        save_options["method"] = 4
                        if animated:
                            save_options.update(
                                save_all=True,
                                append_images=current_frames[1:],
                                duration=durations,
                                loop=loop,
                            )
                    else:
                        save_options.update(optimize=True, progressive=True)
                    current_frames[0].save(output_path, **save_options)
                    if output_path.stat().st_size <= target_bytes:
                        succeeded = True
                        return output_path

            target_mb = max(1, target_bytes // (1024 * 1024))
            raise GalleryError(
                f"图片多轮压缩后仍超过配置目标 {target_mb} MB，未入库。"
            )
        except GalleryError:
            raise
        except Exception as exc:
            raise GalleryError("图片自动压缩失败，原文件未入库。") from exc
        finally:
            for frame in current_frames:
                try:
                    frame.close()
                except Exception:
                    pass
            if output_path is not None and not succeeded:
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _ffmpeg_executable() -> str | None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def _compress_video_to_target(
        self,
        source_path: Path,
        target_bytes: int,
        progress_callback=None,
        cancel_check=None,
    ) -> Path:
        ffmpeg = self._ffmpeg_executable()
        if not ffmpeg:
            raise GalleryError(
                "视频超过配置目标，但当前环境没有可用的 FFmpeg，无法自动压缩。"
            )

        output_path = self.staging_dir / f"compressed-{uuid.uuid4().hex}.mp4"
        succeeded = False
        scale = 1.0
        crf = 28
        deadline = time_module.monotonic() + 1800
        try:
            for attempt in range(8):
                if cancel_check and cancel_check("compression"):
                    raise ProcessingTaskCancelled("压缩任务已取消。")
                remaining_seconds = deadline - time_module.monotonic()
                if remaining_seconds <= 0:
                    raise GalleryError(
                        "视频自动压缩超过 30 分钟，未入库。"
                    )
                output_path.unlink(missing_ok=True)
                command = [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                ]
                if scale < 0.999:
                    vf = (
                        f"scale=w='max(2,trunc(iw*{scale:.4f}/2)*2)':"
                        f"h='max(2,trunc(ih*{scale:.4f}/2)*2)'"
                    )
                    command.extend(["-vf", vf])
                command.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        str(crf),
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "96k",
                        "-movflags",
                        "+faststart",
                        str(output_path),
                    ]
                )
                if progress_callback:
                    progress_callback(
                        "compression",
                        min(92, 25 + attempt * 8),
                        f"正在压缩视频（第 {attempt + 1}/8 轮）",
                    )
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                stderr_text = ""
                while True:
                    try:
                        _, stderr_text = process.communicate(timeout=0.25)
                        break
                    except subprocess.TimeoutExpired:
                        if cancel_check and cancel_check("compression"):
                            process.terminate()
                            try:
                                process.communicate(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.communicate()
                            raise ProcessingTaskCancelled("压缩任务已取消。")
                        if time_module.monotonic() >= deadline:
                            process.terminate()
                            try:
                                process.communicate(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.communicate()
                            raise GalleryError("视频自动压缩超过 30 分钟，未入库。")
                if process.returncode != 0 or not output_path.is_file():
                    error_text = str(stderr_text or "").lower()
                    if "unknown encoder" in error_text or "encoder not found" in error_text:
                        raise GalleryError(
                            "当前 FFmpeg 不支持 H.264 编码，无法自动压缩视频。"
                        )
                    raise GalleryError("FFmpeg 无法压缩该视频，原文件未入库。")

                output_size = output_path.stat().st_size
                if 0 < output_size <= target_bytes:
                    succeeded = True
                    return output_path

                ratio = target_bytes / max(1, output_size)
                scale_factor = max(0.55, min(0.95, math.sqrt(ratio) * 0.92))
                scale = max(0.30, scale * scale_factor)
                crf = min(48, crf + (3 if ratio > 0.85 else 5))

            target_mb = max(1, target_bytes // (1024 * 1024))
            raise GalleryError(
                f"视频多轮压缩后仍超过配置目标 {target_mb} MB，未入库。"
            )
        finally:
            if not succeeded:
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _perceptual_hash(path: Path) -> str:
        """Return a 64-bit DCT perceptual hash for the first image frame."""
        size = PERCEPTUAL_HASH_DIMENSION
        low = PERCEPTUAL_HASH_LOW_FREQUENCIES
        cosine = tuple(
            tuple(
                math.cos((2 * position + 1) * frequency * math.pi / (2 * size))
                for position in range(size)
            )
            for frequency in range(low)
        )
        scale = tuple(
            math.sqrt(1 / size) if frequency == 0 else math.sqrt(2 / size)
            for frequency in range(low)
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if getattr(source, "is_animated", False):
                    source.seek(0)
                if source.format == "JPEG":
                    source.draft("L", (size, size))
                elif source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                    raise ValueError("image is too large for perceptual hashing")
                image = ImageOps.exif_transpose(source).convert("L")
                image = image.resize((size, size), Image.Resampling.LANCZOS)
                pixel_data = list(image.getdata())
                pixels = [
                    pixel_data[y * size : (y + 1) * size] for y in range(size)
                ]

        horizontal = [[0.0] * size for _ in range(low)]
        for y in range(size):
            row = pixels[y]
            for u in range(low):
                horizontal[u][y] = sum(
                    row[x] * cosine[u][x] for x in range(size)
                ) * scale[u]

        coefficients = []
        for v in range(low):
            for u in range(low):
                value = sum(
                    horizontal[u][y] * cosine[v][y] for y in range(size)
                ) * scale[v]
                coefficients.append(value * scale[u])

        median = sorted(coefficients[1:])[len(coefficients[1:]) // 2]
        value = 0
        for coefficient in coefficients:
            value = (value << 1) | int(coefficient >= median)
        return f"{value:016x}"

    @staticmethod
    def _hash_file(path: Path, cancel_check=None) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                if cancel_check and cancel_check():
                    raise ProcessingTaskCancelled("压缩任务已取消。")
                digest.update(chunk)
        return digest.hexdigest()

    def add_media(
        self,
        source_path: str | Path,
        category_id: str,
        media_type: str,
        source: str,
        progress_callback=None,
        cancel_check=None,
    ) -> dict:
        media_type = str(media_type).lower()
        if media_type not in {"image", "video"}:
            raise GalleryError("不支持的媒体类型。")
        source_path = Path(source_path)
        if not source_path.is_file():
            raise GalleryError("找不到媒体文件。")
        try:
            source_size = source_path.stat().st_size
        except OSError as exc:
            raise GalleryError("无法读取媒体文件。") from exc
        target_bytes = (
            self.max_video_bytes if media_type == "video" else self.max_image_bytes
        )
        source_limit_bytes = (
            self.max_source_video_bytes
            if media_type == "video"
            else self.max_source_image_bytes
        )
        if cancel_check and cancel_check("compression"):
            raise ProcessingTaskCancelled("压缩任务已取消。")
        if source_size > source_limit_bytes:
            limit_mb = source_limit_bytes // (1024 * 1024)
            media_label = "视频" if media_type == "video" else "图片"
            raise GalleryError(
                f"{media_label}原始文件不能超过接收上限 {limit_mb} MB。"
            )
        if source_size > target_bytes and not self.compress_oversized_media:
            limit_mb = target_bytes // (1024 * 1024)
            media_label = "视频" if media_type == "video" else "图片"
            raise GalleryError(
                f"{media_label}超过入库体积上限 {limit_mb} MB，且已关闭自动压缩，未入库。"
            )
        staging_path = self.staging_dir / f"{uuid.uuid4().hex}.tmp"
        compressed_path: Path | None = None
        prepared_path = staging_path
        final_path: Path | None = None
        thumbnail_path: Path | None = None
        thumbnail_error = ""
        thumbnail_cancelled = False
        try:
            if source_size > target_bytes and progress_callback:
                progress_callback("compression", 5, "正在复制并检查源文件")
            if cancel_check and cancel_check("compression"):
                raise ProcessingTaskCancelled("压缩任务已取消。")
            shutil.copyfile(source_path, staging_path)
            source_size = staging_path.stat().st_size
            original_size_bytes = source_size
            if source_size > source_limit_bytes:
                limit_mb = source_limit_bytes // (1024 * 1024)
                media_label = "视频" if media_type == "video" else "图片"
                raise GalleryError(
                    f"{media_label}原始文件不能超过接收上限 {limit_mb} MB。"
                )

            if media_type == "video":
                self._inspect_video(staging_path, self.max_source_video_bytes)
                if source_size > target_bytes:
                    if progress_callback:
                        progress_callback("compression", 20, "视频检查完成，开始压缩")
                    compressed_path = self._compress_video_to_target(
                        staging_path,
                        target_bytes,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                    )
                    prepared_path = compressed_path
                media_format, width, height, size = self._inspect_video(prepared_path)
                suffix = VIDEO_SUFFIXES[media_format]
            else:
                image_format, _, _, _ = self._inspect_image(
                    staging_path, self.max_source_image_bytes
                )
                if image_format == "MPO":
                    self._normalize_mpo_to_jpeg(staging_path)
                    source_size = staging_path.stat().st_size
                    self._inspect_image(staging_path, self.max_source_image_bytes)
                if source_size > target_bytes:
                    if progress_callback:
                        progress_callback("compression", 20, "图片检查完成，开始压缩")
                    compressed_path = self._compress_image_to_target(
                        staging_path,
                        target_bytes,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                    )
                    prepared_path = compressed_path
                media_format, width, height, size = self._inspect_image(prepared_path)
                suffix = FORMAT_SUFFIXES[media_format]
            if cancel_check and cancel_check("compression"):
                raise ProcessingTaskCancelled("压缩任务已取消。")
            compressed = compressed_path is not None
            digest = self._hash_file(
                prepared_path,
                (lambda: cancel_check("compression")) if cancel_check else None,
            )
            perceptual_hash = ""
            if media_type == "image":
                try:
                    perceptual_hash = self._perceptual_hash(prepared_path)
                except Exception:
                    # A perceptual fingerprint is optional and must not block import.
                    perceptual_hash = ""
            with self._lock, self._connect() as db:
                category = db.execute(
                    "SELECT id, is_nsfw FROM categories WHERE id = ?", (category_id,)
                ).fetchone()
                if not category:
                    raise GalleryError("找不到目标分类，请刷新页面后重试。")
                existing = db.execute(
                    "SELECT * FROM images WHERE category_id = ? AND sha256 = ?",
                    (category_id, digest),
                ).fetchone()
                if existing:
                    return {
                        "id": existing["id"],
                        "duplicate": True,
                        "filename": existing["filename"],
                        "size_bytes": existing["size_bytes"],
                        "original_size_bytes": original_size_bytes,
                        "compressed": compressed,
                        "width": existing["width"],
                        "height": existing["height"],
                        "media_type": existing["media_type"],
                    }
                filename = f"{uuid.uuid4().hex}{suffix}"
                final_path = self.images_dir / filename
                os.replace(prepared_path, final_path)
                try:
                    cursor = db.execute(
                        """INSERT INTO images
                           (category_id, filename, sha256, size_bytes, width, height,
                            image_format, source, created_at, is_nsfw, media_type, phash)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            category_id,
                            filename,
                            digest,
                            size,
                            width,
                            height,
                            media_format,
                            source,
                            self._now(),
                            int(category["is_nsfw"]),
                            media_type,
                            perceptual_hash,
                        ),
                    )
                    image_id = cursor.lastrowid
                    db.execute(
                        "UPDATE images SET ai_status = ? WHERE id = ?",
                        (
                            "manual_required"
                            if category["is_nsfw"]
                            else ("not_evaluated" if category["id"] == "pending" else "pending"),
                            image_id,
                        ),
                    )
                except Exception:
                    try:
                        final_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
            if source_size > target_bytes and progress_callback:
                progress_callback("compression", 100, "压缩并入库完成")
            if media_type == "video":
                if progress_callback:
                    progress_callback("video_preview", 5, "开始生成视频预览图")
                try:
                    thumbnail_path = self._ensure_gallery_thumbnail(
                        final_path,
                        media_type,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                    )
                    if thumbnail_path is None:
                        thumbnail_error = "FFmpeg 未能从视频生成预览图。"
                except ProcessingTaskCancelled:
                    thumbnail_cancelled = True
                    thumbnail_error = "视频预览生成已取消。"
                except Exception as exc:
                    thumbnail_error = str(exc) or "视频预览生成失败。"
            else:
                try:
                    self._ensure_gallery_thumbnail(final_path, media_type)
                except Exception:
                    # Thumbnail creation must not invalidate an otherwise successful import.
                    pass
            if media_type == "video" and not thumbnail_cancelled and progress_callback:
                progress_callback(
                    "video_preview",
                    100 if thumbnail_path else 0,
                    "视频预览图已生成" if thumbnail_path else thumbnail_error,
                )
            return {
                "id": image_id,
                "duplicate": False,
                "filename": filename,
                "size_bytes": size,
                "original_size_bytes": original_size_bytes,
                "compressed": compressed,
                "width": width,
                "height": height,
                "media_type": media_type,
                "thumbnail_ready": bool(thumbnail_path),
                "thumbnail_error": thumbnail_error,
                "thumbnail_cancelled": thumbnail_cancelled,
            }
        except Exception:
            if final_path is not None:
                try:
                    final_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            staging_path.unlink(missing_ok=True)
            if compressed_path is not None:
                compressed_path.unlink(missing_ok=True)

    def add_image(self, source_path: str | Path, category_id: str, source: str) -> dict:
        return self.add_media(source_path, category_id, "image", source)

    def add_video(self, source_path: str | Path, category_id: str, source: str) -> dict:
        return self.add_media(source_path, category_id, "video", source)

    def scan_duplicates(self, threshold: int = 8, progress_callback=None) -> dict:
        """Find exact cross-category duplicates and perceptually similar images."""
        threshold = max(0, min(int(threshold), 16))
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT i.id, i.category_id, c.name AS category_name,
                          i.filename, i.sha256, i.size_bytes, i.width, i.height,
                          i.image_format, i.media_type, i.is_nsfw, i.phash
                   FROM images i
                   JOIN categories c ON c.id = i.category_id
                   ORDER BY i.id"""
            ).fetchall()

        items = []
        hashes_by_sha256: dict[str, list[dict]] = {}
        for row in rows:
            item = {
                "id": int(row["id"]),
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                "filename": row["filename"],
                "sha256": row["sha256"],
                "size_bytes": int(row["size_bytes"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "image_format": row["image_format"],
                "media_type": row["media_type"],
                "is_nsfw": bool(row["is_nsfw"]),
                "phash": str(row["phash"] or ""),
            }
            items.append(item)
            hashes_by_sha256.setdefault(item["sha256"], []).append(item)

        exact_groups = [
            {"sha256": digest, "ids": [item["id"] for item in group]}
            for digest, group in hashes_by_sha256.items()
            if len({item["category_id"] for item in group}) > 1
        ]
        exact_groups.sort(key=lambda group: (-len(group["ids"]), group["sha256"]))

        image_items = [item for item in items if item["media_type"] == "image"]
        missing_hashes = sum(not item["phash"] for item in image_items)
        hash_errors = 0
        updates: list[tuple[str, int]] = []

        def flush_updates() -> None:
            if not updates:
                return
            with self._lock, self._connect() as db:
                db.executemany(
                    "UPDATE images SET phash = ? WHERE id = ?",
                    updates,
                )
            updates.clear()

        if progress_callback:
            progress_callback("hashing", 0, missing_hashes, hash_errors)
        hashed = 0
        for item in image_items:
            if not item["phash"]:
                try:
                    media_path = self.images_dir / item["filename"]
                    if not media_path.is_file():
                        raise OSError("media file is missing")
                    item["phash"] = self._perceptual_hash(media_path)
                    updates.append((item["phash"], item["id"]))
                except Exception:
                    hash_errors += 1
                hashed += 1
                if len(updates) >= 50:
                    flush_updates()
                if progress_callback and (
                    hashed == missing_hashes or hashed % 5 == 0
                ):
                    progress_callback("hashing", hashed, missing_hashes, hash_errors)
            if item["phash"]:
                try:
                    item["phash_value"] = int(item["phash"], 16)
                except ValueError:
                    item["phash"] = ""
                    item["phash_value"] = None
            else:
                item["phash_value"] = None
        flush_updates()

        class BKTree:
            def __init__(self):
                self.root = None

            def add(self, value, item):
                if self.root is None:
                    self.root = {"value": value, "items": [item], "children": {}}
                    return
                node = self.root
                while True:
                    distance = (node["value"] ^ value).bit_count()
                    if distance == 0:
                        node["items"].append(item)
                        return
                    child = node["children"].get(distance)
                    if child is None:
                        node["children"][distance] = {
                            "value": value,
                            "items": [item],
                            "children": {},
                        }
                        return
                    node = child

            def search(self, value, radius):
                if self.root is None:
                    return
                pending = [self.root]
                while pending:
                    node = pending.pop()
                    distance = (node["value"] ^ value).bit_count()
                    if distance <= radius:
                        yield node, distance
                    lower = distance - radius
                    upper = distance + radius
                    pending.extend(
                        child
                        for edge, child in node["children"].items()
                        if lower <= edge <= upper
                    )

        tree = BKTree()
        similar_pairs = []
        truncated = False
        compare_total = sum(item["phash_value"] is not None for item in image_items)
        if progress_callback:
            progress_callback("comparing", 0, compare_total, hash_errors)
        compared = 0
        for item in image_items:
            value = item["phash_value"]
            if value is None:
                continue
            for node, distance in tree.search(value, threshold):
                for other in node["items"]:
                    if (
                        other["category_id"] == item["category_id"]
                        or other["sha256"] == item["sha256"]
                    ):
                        continue
                    similar_pairs.append(
                        {
                            "first_id": other["id"],
                            "second_id": item["id"],
                            "distance": distance,
                        }
                    )
                    if len(similar_pairs) >= MAX_SIMILAR_CANDIDATES:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
            tree.add(value, item)
            compared += 1
            if progress_callback and (
                compared == compare_total or compared % 100 == 0
            ):
                progress_callback("comparing", compared, compare_total, hash_errors)
        similar_pairs.sort(
            key=lambda pair: (pair["distance"], pair["first_id"], pair["second_id"])
        )
        if progress_callback:
            progress_callback("completed", compare_total, compare_total, hash_errors)
        return {
            "exact_groups": exact_groups,
            "similar_pairs": similar_pairs,
            "hash_errors": hash_errors,
            "truncated": truncated,
            "threshold": threshold,
            "total_images": len(image_items),
        }

    def duplicate_media_cards(self, image_ids: list[int]) -> dict[int, dict]:
        ids = list(dict.fromkeys(int(value) for value in image_ids))
        if not ids:
            return {}
        if len(ids) > 2000:
            ids = ids[:2000]
        rows = []
        with self._lock, self._connect() as db:
            for offset in range(0, len(ids), 500):
                chunk = ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    db.execute(
                        f"""SELECT i.*, c.name AS category_name,
                                   c.is_nsfw AS category_nsfw
                            FROM images i JOIN categories c ON c.id = i.category_id
                            WHERE i.id IN ({placeholders})""",
                        chunk,
                    ).fetchall()
                )
        by_id = {}
        for row in rows:
            path = self.images_dir / row["filename"]
            try:
                thumbnail_path = (
                    self._ensure_gallery_thumbnail(path, row["media_type"])
                    if path.is_file()
                    else None
                )
            except Exception:
                thumbnail_path = None
            by_id[int(row["id"])] = {
                "id": int(row["id"]),
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                "media_type": row["media_type"],
                "image_format": row["image_format"],
                "width": int(row["width"]),
                "height": int(row["height"]),
                "size_bytes": int(row["size_bytes"]),
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                "thumbnail": (
                    self._thumbnail_data_url(thumbnail_path)
                    if thumbnail_path is not None
                    else ""
                ),
            }
        return by_id

    def list_images(
        self,
        category_id: str,
        page: int = 1,
        page_size: int = 30,
        tag: str = "",
        defer_video_thumbnails: bool = False,
        media_type: str = "",
    ) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), PAGE_SIZE_MAX))
        media_type = str(media_type or "").strip().lower()
        if media_type not in {"", "image", "video"}:
            raise GalleryError("媒体类型筛选无效。")
        media_filter = " AND media_type = ?" if media_type else ""
        offset = (page - 1) * page_size
        with self._lock, self._connect() as db:
            category = db.execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if not category:
                raise GalleryError("找不到该分类。")
            tag_filter = ""
            params: list[object] = [category_id]
            if tag.strip():
                tag_terms = self._expanded_tag_terms(db, tag)
                tag_conditions = " OR ".join(
                    "t.tag = ? COLLATE NOCASE" for _ in tag_terms
                )
                tag_filter = (
                    " AND EXISTS (SELECT 1 FROM media_tags t "
                    "WHERE t.image_id = images.id AND (" + tag_conditions + "))"
                )
                params.extend(tag_terms)
            if media_type:
                params.append(media_type)
            total = db.execute(
                f"SELECT COUNT(*) FROM images WHERE category_id = ?{tag_filter}{media_filter}",
                params,
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT images.*,
                          (SELECT provider_id FROM media_embeddings WHERE image_id = images.id)
                            AS vector_provider_id
                   FROM images WHERE category_id = ?{tag_filter}{media_filter}
                   ORDER BY id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, offset],
            ).fetchall()
        items = []
        for row in rows:
            path = self.images_dir / row["filename"]
            if not path.is_file():
                continue
            try:
                if defer_video_thumbnails and row["media_type"] == "video":
                    cached_thumbnail = self._gallery_thumbnail_path(path)
                    if cached_thumbnail.is_file():
                        with Image.open(cached_thumbnail) as thumbnail:
                            thumbnail.verify()
                        thumbnail_path = cached_thumbnail
                    else:
                        thumbnail_path = None
                else:
                    thumbnail_path = self._ensure_gallery_thumbnail(
                        path, row["media_type"]
                    )
            except Exception:
                thumbnail_path = None
            items.append(
                {
                    "id": row["id"],
                    "category_id": row["category_id"],
                    "filename": row["filename"],
                    "size_bytes": row["size_bytes"],
                    "width": row["width"],
                    "height": row["height"],
                    "image_format": row["image_format"],
                    "media_type": row["media_type"],
                    "is_nsfw": bool(row["is_nsfw"]),
                    "manual_tags": self._decode_tags(row["manual_tags"]),
                    "ai_tags": self._decode_tags(row["ai_tags"]),
                    "ai_description": row["ai_description"],
                    "description_override": row["description_override"],
                    "description": row["description_override"] or row["ai_description"],
                    "ai_status": row["ai_status"],
                    "ai_error": row["ai_error"],
                    "ai_provider_id": row["ai_provider_id"],
                    "ai_updated_at": row["ai_updated_at"],
                    "embedding_ready": bool(row["vector_provider_id"]),
                    "source": row["source"],
                    "created_at": row["created_at"],
                    "thumbnail": (
                        self._thumbnail_data_url(thumbnail_path)
                        if thumbnail_path is not None
                        else None
                    ),
                }
            )
        return {
            "category": self._category_dict(category, total),
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    @staticmethod
    def _normalize_mirage_settings(settings: dict) -> dict:
        defaults = {
            "maxSize": 1200,
            "scaleInner": 0.3,
            "scaleCover": 0.2,
            "desatInner": 0.0,
            "desatCover": 0.0,
            "weightInner": 0.7,
            "colored": True,
        }
        if not isinstance(settings, dict):
            raise GalleryError("幻影坦克参数格式无效。")

        normalized = {}
        for key in ("scaleInner", "scaleCover", "desatInner", "desatCover", "weightInner"):
            try:
                value = float(settings.get(key, defaults[key]))
            except (TypeError, ValueError):
                value = defaults[key]
            if not math.isfinite(value):
                value = defaults[key]
            normalized[key] = min(1.0, max(0.0, value))

        try:
            max_size_value = float(settings.get("maxSize", defaults["maxSize"]))
            max_size = (
                int(round(max_size_value))
                if math.isfinite(max_size_value)
                else defaults["maxSize"]
            )
        except (TypeError, ValueError, OverflowError):
            max_size = defaults["maxSize"]
        max_size = min(1200, max(240, max_size))
        normalized["maxSize"] = min(
            1200,
            max(240, 240 + round((max_size - 240) / 80) * 80),
        )
        colored = settings.get("colored", defaults["colored"])
        normalized["colored"] = colored if isinstance(colored, bool) else defaults["colored"]
        return normalized

    def get_mirage_settings(self) -> dict:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT setting_value FROM plugin_settings WHERE setting_key = ?",
                ("mirage",),
            ).fetchone()
        if not row:
            return self._normalize_mirage_settings({})
        try:
            settings = json.loads(row["setting_value"])
        except (TypeError, ValueError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        return self._normalize_mirage_settings(settings)

    def save_mirage_settings(self, settings: dict) -> dict:
        normalized = self._normalize_mirage_settings(settings)
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO plugin_settings (setting_key, setting_value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(setting_key) DO UPDATE SET
                       setting_value = excluded.setting_value,
                       updated_at = excluded.updated_at""",
                ("mirage", json.dumps(normalized, ensure_ascii=False), self._now()),
            )
        return normalized

    def get_mirage_chat_sources(
        self, cover_id: int, inner_id: int, *, allow_nsfw: bool = False, allow_pending: bool = False
    ) -> dict:
        """Validate two confirmed gallery image sources for chat generation."""
        try:
            cover_id = int(cover_id)
            inner_id = int(inner_id)
        except (TypeError, ValueError) as exc:
            raise GalleryError("表图和里图编号必须是有效的媒体编号。") from exc
        if cover_id <= 0 or inner_id <= 0:
            raise GalleryError("表图和里图编号必须是正整数。")
        if cover_id == inner_id:
            raise GalleryError("表图和里图需要选择两张不同的图片。")

        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT i.id, i.filename, i.media_type, i.category_id,
                          i.is_nsfw, c.name AS category_name,
                          c.is_nsfw AS category_nsfw
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id IN (?, ?)""",
                (cover_id, inner_id),
            ).fetchall()
        by_id = {int(row["id"]): row for row in rows}
        if len(by_id) != 2:
            raise GalleryError("找不到表图或里图，请检查媒体编号，或确认媒体没有进入回收站。")

        result = {}
        for role, image_id in (("cover", cover_id), ("inner", inner_id)):
            row = by_id[image_id]
            role_name = "表图" if role == "cover" else "里图"
            if row["media_type"] != "image":
                raise GalleryError(f"{role_name}编号 {image_id} 是视频；幻影坦克只支持图片。")
            if row["category_id"] == "pending" and not allow_pending:
                raise GalleryError("待处理分类尚未确认安全范围，不能用于聊天生成；请先将来源图片移入普通分类。")
            if (row["is_nsfw"] or row["category_nsfw"]) and not allow_nsfw:
                raise GalleryError("该来源属于 NSFW 媒体；请使用有 NSFW 权限的管理员账号。")
            media_path = self.images_dir / row["filename"]
            if not media_path.is_file():
                raise GalleryError(f"图库图片编号 {image_id} 的文件不存在。")
            result[role] = {
                "id": image_id,
                "path": media_path,
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
            }
        return result

    @staticmethod
    def _load_mirage_generation_frame(path: Path, max_size: int) -> Image.Image:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    image_format = str(source.format or "").upper()
                    source_pixels = source.width * source.height
                    if image_format not in ALLOWED_FORMATS:
                        raise GalleryError("幻影坦克来源图片格式不受支持。")
                    if (
                        source.width <= 0
                        or source.height <= 0
                        or source_pixels > MAX_IMAGE_PIXELS
                    ):
                        raise GalleryError("幻影坦克来源图片尺寸超过安全处理上限。")
                    try:
                        source.seek(0)
                    except EOFError:
                        pass
                    if source_pixels > MAX_IMAGE_DECODE_PIXELS:
                        if image_format == "JPEG":
                            source.draft("RGB", (max_size, max_size))
                            if source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                                raise GalleryError(
                                    "当前 Pillow 无法安全降采样这张超大 JPEG，请先缩小后再制作。"
                                )
                        elif source_pixels > MAX_IMAGE_DECODE_PIXELS:
                            raise GalleryError(
                                "超大非 JPEG 来源图片超过安全解码上限，请先缩小后再制作。"
                            )
                    frame = ImageOps.exif_transpose(source.copy())
                    rgba = frame.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, "white")
                    rgb.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
                    return rgb
        except GalleryError:
            raise
        except Image.DecompressionBombError as exc:
            raise GalleryError("幻影坦克来源图片像素超过安全处理上限。") from exc
        except Exception as exc:
            raise GalleryError("幻影坦克来源图片读取失败。") from exc

    def create_mirage_png(
        self,
        cover_id: int,
        inner_id: int,
        output_path: str | Path,
        settings: dict | None = None,
        *,
        allow_nsfw: bool = False,
    ) -> dict:
        sources = self.get_mirage_chat_sources(
            cover_id, inner_id, allow_nsfw=allow_nsfw
        )
        return self.create_mirage_png_from_paths(
            sources["cover"]["path"],
            sources["inner"]["path"],
            output_path,
            settings,
        )

    @staticmethod
    def _process_mirage_images(
        inner: Image.Image,
        cover: Image.Image,
        options: dict,
    ) -> Image.Image:
        inner_gray = inner.convert("L")
        cover_gray = cover.convert("L")
        scale_inner = options["scaleInner"]
        scale_cover = 1.0 - options["scaleCover"]
        desat_inner = options["desatInner"]
        desat_cover = options["desatCover"]
        weight_inner = options["weightInner"]

        def evaluate(function, **images):
            return ImageMath.lambda_eval(function, **images)

        if options["colored"]:
            alpha_float = evaluate(
                lambda args: args["min"](
                    args["max"](
                        args["float"](args["inner_gray"]) * scale_inner
                        + (255.0 - args["float"](args["cover_gray"])) * scale_cover,
                        0.0,
                    ),
                    255.0,
                ),
                inner_gray=inner_gray,
                cover_gray=cover_gray,
            )
            inner_prepared = []
            cover_prepared = []
            for channel in range(3):
                inner_channel = inner.getchannel(channel)
                cover_channel = cover.getchannel(channel)
                inner_prepared.append(
                    evaluate(
                        lambda args: args["convert"](
                            args["float"](args["channel"]) * scale_inner * (1.0 - desat_inner)
                            + args["float"](args["gray"]) * scale_inner * desat_inner
                            + 0.5,
                            "L",
                        ),
                        channel=inner_channel,
                        gray=inner_gray,
                    )
                )
                cover_prepared.append(
                    evaluate(
                        lambda args: args["convert"](
                            (
                                255.0
                                - (255.0 - args["float"](args["channel"])) * scale_cover
                            ) * (1.0 - desat_cover)
                            + (
                                255.0
                                - (255.0 - args["float"](args["gray"])) * scale_cover
                            ) * desat_cover
                            + 0.5,
                            "L",
                        ),
                        channel=cover_channel,
                        gray=cover_gray,
                    )
                )

            denominator = evaluate(
                lambda args: args["max"](
                    args["alpha"] / 255.0,
                    1.0 / 255.0,
                ),
                alpha=alpha_float,
            )
            output_channels = []
            for inner_channel, cover_channel in zip(inner_prepared, cover_prepared):
                output_channels.append(
                    evaluate(
                        lambda args: args["convert"](
                            args["min"](
                                args["max"](
                                    (
                                        (
                                            args["float"](args["inner"])
                                            - args["alpha"]
                                            + 255.0
                                            - args["float"](args["cover"])
                                        ) * weight_inner
                                        + args["alpha"]
                                        - 255.0
                                        + args["float"](args["cover"])
                                    ) / args["denominator"],
                                    0.0,
                                ),
                                255.0,
                            ) + 0.5,
                            "L",
                        ),
                        inner=inner_channel,
                        cover=cover_channel,
                        alpha=alpha_float,
                        denominator=denominator,
                    )
                )
            alpha = evaluate(
                lambda args: args["convert"](args["alpha"] + 0.5, "L"),
                alpha=alpha_float,
            )
            result = Image.merge("RGBA", (*output_channels, alpha))
        else:
            inner_luminance = evaluate(
                lambda args: args["float"](args["gray"]) * scale_inner,
                gray=inner_gray,
            )
            cover_luminance = evaluate(
                lambda args: 255.0
                - (255.0 - args["float"](args["gray"])) * scale_cover,
                gray=cover_gray,
            )
            alpha_float = evaluate(
                lambda args: args["min"](
                    args["max"](
                        255.0 + args["inner_luminance"] - args["cover_luminance"],
                        0.0,
                    ),
                    255.0,
                ),
                inner_luminance=inner_luminance,
                cover_luminance=cover_luminance,
            )
            luminance = evaluate(
                lambda args: args["convert"](
                    args["min"](
                        args["max"](
                            args["inner_luminance"] * 255.0 / args["alpha"],
                            0.0,
                        ),
                        255.0,
                    ) + 0.5,
                    "L",
                ),
                inner_luminance=inner_luminance,
                alpha=alpha_float,
            )
            alpha = evaluate(
                lambda args: args["convert"](args["alpha"] + 0.5, "L"),
                alpha=alpha_float,
            )
            result = Image.merge("RGBA", (luminance, luminance, luminance, alpha))

        return result

    def create_mirage_png_from_paths(
        self,
        cover_path: str | Path,
        inner_path: str | Path,
        output_path: str | Path,
        settings: dict | None = None,
    ) -> dict:
        """Render a source-resolution transparent PNG without upscaling either crop."""
        cover_path = Path(cover_path)
        inner_path = Path(inner_path)
        for source_path in (cover_path, inner_path):
            if not source_path.is_file():
                raise GalleryError("找不到表图或里图文件。")
            try:
                source_bytes = source_path.stat().st_size
            except OSError as exc:
                raise GalleryError("表图或里图文件无法读取。") from exc
            if source_bytes > self.max_source_image_bytes:
                limit_mb = self.max_source_image_bytes // (1024 * 1024)
                raise GalleryError(f"单张来源图片不能超过接收上限 {limit_mb} MB。")

        options = self._normalize_mirage_settings(
            settings if isinstance(settings, dict) else self.get_mirage_settings()
        )
        inner_source = self._load_mirage_generation_frame(
            inner_path, MAX_MIRAGE_OUTPUT_EDGE
        )
        cover_source = self._load_mirage_generation_frame(
            cover_path, MAX_MIRAGE_OUTPUT_EDGE
        )
        cover_ratio = cover_source.width / cover_source.height
        inner_ratio = inner_source.width / inner_source.height
        if inner_ratio < cover_ratio:
            inner_crop_width = float(inner_source.width)
            inner_crop_height = inner_crop_width / cover_ratio
        else:
            inner_crop_height = float(inner_source.height)
            inner_crop_width = inner_crop_height * cover_ratio

        scale = min(
            1.0,
            inner_crop_width / cover_source.width,
            inner_crop_height / cover_source.height,
            MAX_MIRAGE_OUTPUT_EDGE / max(cover_source.width, cover_source.height),
            math.sqrt(
                MAX_IMAGE_DECODE_PIXELS
                / (cover_source.width * cover_source.height)
            ),
        )
        base_width = max(1, math.floor(cover_source.width * scale))
        base_height = max(1, math.floor(cover_source.height * scale))
        if base_width > inner_crop_width or base_height > inner_crop_height:
            extra_scale = min(
                inner_crop_width / base_width,
                inner_crop_height / base_height,
            )
            base_width = max(1, math.floor(base_width * extra_scale))
            base_height = max(1, math.floor(base_height * extra_scale))

        output_path = Path(output_path)
        output_scale = 1.0
        for _attempt in range(10):
            width = max(1, math.floor(base_width * output_scale))
            height = max(1, math.floor(base_height * output_scale))
            inner = ImageOps.fit(
                inner_source,
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            cover = cover_source.resize((width, height), Image.Resampling.LANCZOS)
            result = self._process_mirage_images(inner, cover, options)
            try:
                result.save(output_path, format="PNG", compress_level=6)
                size_bytes = output_path.stat().st_size
            except Exception as exc:
                raise GalleryError("幻影坦克 PNG 写入失败。") from exc
            if size_bytes <= self.max_image_bytes:
                return {"width": width, "height": height, "size_bytes": size_bytes}
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            output_scale *= max(
                0.4,
                min(0.9, math.sqrt(self.max_image_bytes / size_bytes) * 0.92),
            )
            del result, inner, cover

        raise GalleryError(
            "幻影坦克成品无法在保持透明 PNG 的前提下压入图片体积上限。"
        )
    def get_mirage_source(self, image_id: int, max_edge: int = 1200) -> dict:
        """Return a bounded, orientation-corrected preview for phantom-tank creation."""
        try:
            image_id = int(image_id)
        except (TypeError, ValueError) as exc:
            raise GalleryError("图片编号无效。") from exc
        if image_id <= 0:
            raise GalleryError("图片编号无效。")
        max_edge = max(256, min(int(max_edge), 1200))
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.*, c.name AS category_name, c.is_nsfw AS category_nsfw
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id = ?""",
                (image_id,),
            ).fetchone()
        if not row:
            raise GalleryError("找不到该图片，或该媒体已在回收站。")
        if row["media_type"] != "image":
            raise GalleryError("幻影坦克制作只支持图片，不能使用视频。")
        path = self.images_dir / row["filename"]
        if not path.is_file():
            raise GalleryError("图片文件不存在。")
        try:
            file_stat = path.stat()
        except OSError as exc:
            raise GalleryError("图片文件无法读取。") from exc
        cache_key = (image_id, file_stat.st_size, file_stat.st_mtime_ns)
        with self._lock:
            cached_preview = self._mirage_preview_cache.get(cache_key)
            if cached_preview is not None:
                self._mirage_preview_cache.move_to_end(cache_key)
        if cached_preview is not None:
            data_url, preview_width, preview_height = cached_preview
            return {
                "id": row["id"],
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                "width": row["width"],
                "height": row["height"],
                "preview_width": preview_width,
                "preview_height": preview_height,
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                "data_url": data_url,
                "max_image_bytes": self.max_image_bytes,
            }

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    image_format = str(source.format or "").upper()
                    source_pixels = source.width * source.height
                    if image_format not in ALLOWED_FORMATS:
                        raise GalleryError("图片格式不受支持。")
                    if (
                        source.width <= 0
                        or source.height <= 0
                        or source_pixels > MAX_IMAGE_PIXELS
                    ):
                        raise GalleryError("图片尺寸超过安全处理上限。")
                    try:
                        source.seek(0)
                    except EOFError:
                        pass
                    if source_pixels > max_edge * max_edge * 4:
                        if image_format == "JPEG":
                            source.draft("RGB", (max_edge, max_edge))
                            if source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                                raise GalleryError(
                                    "当前 Pillow 无法安全降采样这张超大 JPEG；请先缩小后重新导入。"
                                )
                        elif source_pixels > MAX_IMAGE_DECODE_PIXELS:
                            raise GalleryError(
                                "这张非 JPEG 图片的像素数超过安全处理上限；请先缩小后重新导入。"
                            )
                    frame = ImageOps.exif_transpose(source.copy())
                    frame.thumbnail(
                        (max_edge, max_edge),
                        Image.Resampling.LANCZOS,
                    )
                    if frame.mode in ("RGBA", "LA") or "transparency" in frame.info:
                        rgba = frame.convert("RGBA")
                        preview = Image.new("RGB", rgba.size, "white")
                        preview.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        preview = frame.convert("RGB")
                    with BytesIO() as output:
                        preview.save(
                            output,
                            format="JPEG",
                            quality=86,
                            subsampling=0,
                            optimize=False,
                            progressive=False,
                        )
                        encoded = base64.b64encode(output.getvalue()).decode("ascii")
                    data_url = f"data:image/jpeg;base64,{encoded}"
                    preview_width, preview_height = preview.size
        except GalleryError:
            raise
        except Image.DecompressionBombError as exc:
            raise GalleryError("图片像素超过安全处理上限。") from exc
        except Exception as exc:
            raise GalleryError("图片读取或预览生成失败。") from exc

        cache_size = len(data_url)
        if cache_size <= self._mirage_preview_cache_limit:
            with self._lock:
                previous = self._mirage_preview_cache.pop(cache_key, None)
                if previous is not None:
                    self._mirage_preview_cache_bytes -= len(previous[0])
                self._mirage_preview_cache[cache_key] = (
                    data_url,
                    preview_width,
                    preview_height,
                )
                self._mirage_preview_cache_bytes += cache_size
                while (
                    self._mirage_preview_cache_bytes > self._mirage_preview_cache_limit
                    and len(self._mirage_preview_cache) > 1
                ):
                    _, evicted = self._mirage_preview_cache.popitem(last=False)
                    self._mirage_preview_cache_bytes -= len(evicted[0])

        return {
            "id": row["id"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "width": row["width"],
            "height": row["height"],
            "preview_width": preview_width,
            "preview_height": preview_height,
            "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
            "data_url": data_url,
            "max_image_bytes": self.max_image_bytes,
        }

    def get_media_for_evaluation(self, image_id: int, scope: str) -> dict:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("评估范围无效。")
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.*, c.name AS category_name, c.is_nsfw AS category_nsfw
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
        if not row:
            raise GalleryError("找不到该媒体。")
        is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
        if scope == "sfw" and row["category_id"] == "pending":
            raise GalleryError("“待处理”尚未确认安全分类，不会进入 SFW 评估或检索。")
        if (scope == "nsfw") != is_nsfw:
            raise GalleryError("评估范围与媒体的 NSFW 标记不一致。")
        path = self.images_dir / row["filename"]
        if not path.is_file():
            raise GalleryError("媒体文件不存在。")
        return {
            "id": row["id"],
            "path": path,
            "media_type": row["media_type"],
            "scope": scope,
            "manual_tags": self._decode_tags(row["manual_tags"]),
            "ai_description": row["ai_description"],
            "description_override": row["description_override"],
        }

    def evaluation_candidates(
        self, image_ids: list[int], scope: str
    ) -> tuple[list[int], int]:
        ids = sorted({int(value) for value in image_ids})
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("评估范围无效。")
        if not ids or len(ids) > 30:
            raise GalleryError("请选择 1–30 个媒体进行评估。")
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.id, i.is_nsfw, i.ai_description,
                          i.description_override, i.ai_status,
                          c.id AS category_id, c.is_nsfw AS category_nsfw
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id IN ({placeholders})""",
                ids,
            ).fetchall()
        if len(rows) != len(ids):
            raise GalleryError("所选媒体中有编号不存在的项目，请刷新后重试。")
        candidates: list[int] = []
        for row in rows:
            is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
            if (scope == "nsfw") != is_nsfw:
                raise GalleryError("评估范围与媒体的 NSFW 标记不一致。")
            if scope == "sfw" and row["category_id"] == "pending":
                raise GalleryError("“待处理”尚未确认安全分类，不会进入 SFW 评估或检索。")
            has_description = bool(
                str(row["description_override"] or "").strip()
                or str(row["ai_description"] or "").strip()
            )
            if not has_description and row["ai_status"] not in {"processing", "queued"}:
                candidates.append(int(row["id"]))
        return candidates, len(ids) - len(candidates)

    def set_ai_status(
        self,
        image_id: int,
        scope: str,
        status: str,
        error: str = "",
        provider_id: str = "",
    ) -> None:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("评估范围无效。")
        expected_nsfw = int(scope == "nsfw")
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.is_nsfw, c.is_nsfw AS category_nsfw, c.id AS category_id
                   FROM images i JOIN categories c ON c.id = i.category_id WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
            if not row:
                raise GalleryError("找不到该媒体。")
            if (
                int(bool(row["is_nsfw"] or row["category_nsfw"])) != expected_nsfw
                or (scope == "sfw" and row["category_id"] == "pending")
            ):
                raise GalleryError("媒体的 NSFW 标记已变化，请刷新后重试。")
            db.execute(
                """UPDATE images SET ai_status = ?, ai_error = ?,
                   ai_provider_id = CASE WHEN ? <> '' THEN ? ELSE ai_provider_id END
                   WHERE id = ?""",
                (status, str(error)[:500], provider_id, provider_id, int(image_id)),
            )

    def save_ai_evaluation(
        self,
        image_id: int,
        scope: str,
        description: str,
        tags: list[str],
        provider_id: str,
    ) -> None:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("评估范围无效。")
        description = str(description).strip()
        if not description:
            raise GalleryError("模型没有返回有效描述。")
        if len(description) > 3000:
            description = description[:3000]
        normalized_tags = self.normalize_tags(tags)
        expected_nsfw = int(scope == "nsfw")
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.is_nsfw, c.is_nsfw AS category_nsfw, c.id AS category_id
                   FROM images i JOIN categories c ON c.id = i.category_id WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
            if not row:
                raise GalleryError("找不到该媒体。")
            if (
                int(bool(row["is_nsfw"] or row["category_nsfw"])) != expected_nsfw
                or (scope == "sfw" and row["category_id"] == "pending")
            ):
                raise GalleryError("媒体的 NSFW 标记已变化，已丢弃模型结果。")
            db.execute(
                """UPDATE images SET ai_description = ?, ai_tags = ?,
                   ai_status = 'evaluated', ai_error = '', ai_provider_id = ?,
                   ai_updated_at = ? WHERE id = ?""",
                (
                    description,
                    json.dumps(normalized_tags, ensure_ascii=False),
                    str(provider_id),
                    self._now(),
                    int(image_id),
                ),
            )
            self._sync_tag_index(
                db,
                int(image_id),
                self._decode_tags(
                    db.execute(
                        "SELECT manual_tags FROM images WHERE id = ?",
                        (int(image_id),),
                    ).fetchone()[0]
                ),
                normalized_tags,
            )
            db.execute("DELETE FROM media_embeddings WHERE image_id = ?", (int(image_id),))

    def save_embedding(
        self,
        image_id: int,
        scope: str,
        provider_id: str,
        fingerprint: str,
        vector: list[float],
    ) -> None:
        if scope not in {"sfw", "nsfw"} or not vector:
            raise GalleryError("向量或检索范围无效。")
        values = [float(value) for value in vector]
        if len(values) > 8192 or any(not (-1e30 < value < 1e30) for value in values):
            raise GalleryError("Embedding 向量包含无效数值。")
        blob = struct.pack(f"<{len(values)}f", *values)
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.is_nsfw, c.is_nsfw AS category_nsfw, c.id AS category_id
                   FROM images i JOIN categories c ON c.id = i.category_id WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
            if (
                not row
                or int(bool(row["is_nsfw"] or row["category_nsfw"])) != int(scope == "nsfw")
                or (scope == "sfw" and row["category_id"] == "pending")
            ):
                raise GalleryError("媒体的安全范围已变化，已丢弃该向量。")
            db.execute(
                """INSERT INTO media_embeddings
                   (image_id, scope, provider_id, provider_fingerprint, dimension, vector, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(image_id) DO UPDATE SET scope=excluded.scope,
                     provider_id=excluded.provider_id,
                     provider_fingerprint=excluded.provider_fingerprint,
                     dimension=excluded.dimension, vector=excluded.vector,
                     created_at=excluded.created_at""",
                (
                    int(image_id),
                    scope,
                    str(provider_id),
                    fingerprint,
                    len(values),
                    blob,
                    self._now(),
                ),
            )

    def embedding_scope_for_media(self, image_id: int) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.is_nsfw, c.is_nsfw AS category_nsfw, c.id AS category_id
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
        if not row:
            raise GalleryError("找不到该媒体。")
        is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
        return (
            "nsfw"
            if is_nsfw
            else (None if row["category_id"] == "pending" else "sfw")
        )

    def embedding_text_for_media(self, image_id: int, scope: str) -> str:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("语义索引范围无效。")
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.ai_description, i.description_override, i.ai_tags, i.manual_tags,
                          i.is_nsfw, c.is_nsfw AS category_nsfw, c.id AS category_id
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
        if not row:
            raise GalleryError("找不到该媒体。")
        is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
        if (scope == "nsfw") != is_nsfw or (scope == "sfw" and row["category_id"] == "pending"):
            raise GalleryError("媒体的安全范围已变化，无法建立该语义索引。")
        description = str(row["description_override"] or row["ai_description"] or "").strip()
        tags = self.normalize_tags(
            self._decode_tags(row["ai_tags"]) + self._decode_tags(row["manual_tags"])
        )
        searchable_text = "\n".join(part for part in (description, " ".join(tags)) if part)
        if not searchable_text:
            raise GalleryError("媒体还没有可用于语义索引的描述或标签。")
        return searchable_text

    def embedding_rebuild_candidates(self, scope: str) -> list[dict]:
        if scope not in {"sfw", "nsfw"}:
            raise GalleryError("重建范围无效。")
        safety_filter = (
            "(i.is_nsfw = 1 OR c.is_nsfw = 1)"
            if scope == "nsfw"
            else "(i.is_nsfw = 0 AND c.is_nsfw = 0 AND c.id <> 'pending')"
        )
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.id, i.ai_description, i.description_override, i.ai_tags, i.manual_tags
                    FROM images i JOIN categories c ON c.id = i.category_id
                    WHERE {safety_filter}
                    ORDER BY i.id"""
            ).fetchall()
        candidates = []
        for row in rows:
            description = str(row["description_override"] or row["ai_description"] or "").strip()
            tags = self.normalize_tags(
                self._decode_tags(row["ai_tags"]) + self._decode_tags(row["manual_tags"])
            )
            searchable_text = "\n".join(part for part in (description, " ".join(tags)) if part)
            if searchable_text:
                candidates.append(
                    {"image_id": int(row["id"]), "searchable_text": searchable_text}
                )
        return candidates

    def search_embeddings(
        self,
        query_vector: list[float],
        scope: str,
        provider_id: str,
        fingerprint: str,
        limit: int = 30,
        allow_nsfw: bool = True,
        media_type: str | None = None,
    ) -> list[dict]:
        if scope not in {"all", "sfw", "nsfw"} or not query_vector:
            raise GalleryError("检索参数无效。")
        if media_type not in {None, "image", "video"}:
            raise GalleryError("媒体类型无效。")
        limit = max(1, min(int(limit), 60))
        conditions = [
            "e.provider_id = ?",
            "e.provider_fingerprint = ?",
            "(e.scope = 'nsfw' OR i.category_id <> 'pending')",
        ]
        params: list[object] = [provider_id, fingerprint]
        if scope != "all":
            conditions.append("e.scope = ?")
            params.append(scope)
            conditions.append("((i.is_nsfw = 1 OR c.is_nsfw = 1) = ?)")
            params.append(int(scope == "nsfw"))
        if not allow_nsfw:
            conditions.append("i.is_nsfw = 0 AND c.is_nsfw = 0")
        if media_type:
            conditions.append("i.media_type = ?")
            params.append(media_type)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.*, c.name AS category_name, c.is_nsfw AS category_nsfw,
                          e.dimension, e.vector
                   FROM media_embeddings e
                   JOIN images i ON i.id = e.image_id
                   JOIN categories c ON c.id = i.category_id
                   WHERE {' AND '.join(conditions)}""",
                params,
            ).fetchall()
        query = [float(value) for value in query_vector]
        query_norm = sum(value * value for value in query) ** 0.5
        if not query_norm:
            raise GalleryError("检索模型返回了空向量。")
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            dimension = int(row["dimension"])
            if dimension != len(query):
                continue
            stored = struct.unpack(f"<{dimension}f", row["vector"])
            stored_norm = sum(value * value for value in stored) ** 0.5
            if not stored_norm:
                continue
            score = sum(a * b for a, b in zip(query, stored)) / (query_norm * stored_norm)
            ranked.append((score, row))
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        items: list[dict] = []
        for score, row in ranked[:limit]:
            path = self.images_dir / row["filename"]
            if not path.is_file():
                continue
            thumbnail_path = self._ensure_gallery_thumbnail(
                path, row["media_type"]
            )
            items.append(
                {
                    "id": row["id"],
                    "category_id": row["category_id"],
                    "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                    "filename": row["filename"],
                    "size_bytes": row["size_bytes"],
                    "width": row["width"],
                    "height": row["height"],
                    "image_format": row["image_format"],
                    "media_type": row["media_type"],
                    "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                    "source": row["source"],
                    "created_at": row["created_at"],
                    "manual_tags": self._decode_tags(row["manual_tags"]),
                    "ai_tags": self._decode_tags(row["ai_tags"]),
                    "ai_description": row["ai_description"],
                    "description_override": row["description_override"],
                    "description": row["description_override"] or row["ai_description"],
                    "ai_status": row["ai_status"],
                    "ai_error": row["ai_error"],
                    "ai_provider_id": row["ai_provider_id"],
                    "ai_updated_at": row["ai_updated_at"],
                    "embedding_ready": True,
                    "score": round(float(score), 4),
                    "thumbnail": (
                        self._thumbnail_data_url(thumbnail_path)
                        if thumbnail_path is not None
                        else None
                    ),
                }
            )
        return items

    def update_manual_tags(
        self, image_ids: list[int], tags: object, mode: str = "replace"
    ) -> int:
        ids = sorted({int(value) for value in image_ids})
        if not ids or len(ids) > 500:
            raise GalleryError("请选择 1–500 个媒体。")
        incoming = self.normalize_tags(tags)
        if mode not in {"replace", "add", "remove"}:
            raise GalleryError("标签维护模式无效。")
        placeholders = ",".join("?" for _ in ids)
        updated = 0
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT id, manual_tags, ai_tags FROM images WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            for row in rows:
                old_tags = self._decode_tags(row["manual_tags"])
                if mode == "replace":
                    new_tags = incoming
                elif mode == "add":
                    new_tags = self.normalize_tags(old_tags + incoming)
                else:
                    remove = {tag.casefold() for tag in incoming}
                    new_tags = [tag for tag in old_tags if tag.casefold() not in remove]
                db.execute(
                    "UPDATE images SET manual_tags = ? WHERE id = ?",
                    (json.dumps(new_tags, ensure_ascii=False), row["id"]),
                )
                self._sync_tag_index(
                    db,
                    int(row["id"]),
                    new_tags,
                    self._decode_tags(row["ai_tags"]),
                )
                if new_tags != old_tags:
                    db.execute(
                        "DELETE FROM media_embeddings WHERE image_id = ?",
                        (row["id"],),
                    )
                updated += 1
        return updated

    def save_media_details(
        self,
        image_id: int,
        description: str,
        manual_tags: object,
        ai_tags: object | None = None,
        clear_ai: bool = False,
    ) -> dict:
        description = str(description or "").strip()
        if len(description) > 3000:
            raise GalleryError("描述不能超过 3000 个字符。")
        normalized_manual_tags = self.normalize_tags(manual_tags)
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT i.ai_description, i.ai_tags, c.id AS category_id,
                          i.is_nsfw, c.is_nsfw AS category_nsfw
                   FROM images i JOIN categories c ON c.id = i.category_id
                   WHERE i.id = ?""",
                (int(image_id),),
            ).fetchone()
            if not row:
                raise GalleryError("找不到该媒体。")
            normalized_ai_tags = (
                []
                if clear_ai
                else (
                    self.normalize_tags(ai_tags)
                    if ai_tags is not None
                    else self._decode_tags(row["ai_tags"])
                )
            )
            effective_description = (
                description
                if clear_ai
                else (description or str(row["ai_description"] or ""))
            )
            if clear_ai:
                is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
                next_status = "manual_required" if is_nsfw else "not_evaluated"
                db.execute(
                    """UPDATE images SET ai_description = '', ai_tags = '[]',
                       description_override = ?, manual_tags = ?, ai_status = ?,
                       ai_error = '', ai_provider_id = '', ai_updated_at = ''
                       WHERE id = ?""",
                    (
                        description,
                        json.dumps(normalized_manual_tags, ensure_ascii=False),
                        next_status,
                        int(image_id),
                    ),
                )
            else:
                db.execute(
                    """UPDATE images SET description_override = ?, manual_tags = ?,
                       ai_tags = ? WHERE id = ?""",
                    (
                        description,
                        json.dumps(normalized_manual_tags, ensure_ascii=False),
                        json.dumps(normalized_ai_tags, ensure_ascii=False),
                        int(image_id),
                    ),
                )
            self._sync_tag_index(
                db, int(image_id), normalized_manual_tags, normalized_ai_tags
            )
            db.execute("DELETE FROM media_embeddings WHERE image_id = ?", (int(image_id),))
        is_nsfw = bool(row["is_nsfw"] or row["category_nsfw"])
        scope = (
            "nsfw"
            if is_nsfw
            else (None if row["category_id"] == "pending" else "sfw")
        )
        return {
            "image_id": int(image_id),
            "scope": scope,
            "description": effective_description,
            "ai_tags": normalized_ai_tags,
            "manual_tags": normalized_manual_tags,
            "ai_cleared": bool(clear_ai),
            "can_evaluate": bool(scope and not description),
        }

    def extract_video_frames(self, video_path: Path) -> list[Path]:
        video_path = Path(video_path)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            try:
                import imageio_ffmpeg

                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception as exc:
                raise GalleryError("当前环境没有 FFmpeg，无法分析视频内容。") from exc
        duration = 0.0
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            try:
                result = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                duration = max(0.0, float(result.stdout.strip() or 0))
            except Exception:
                duration = 0.0
        if duration > 0:
            times = [max(0.0, min(duration - 0.08, duration * ratio)) for ratio in (0.15, 0.5, 0.85)]
        else:
            times = [0.1, 1.0, 2.5]
        unique_times: list[float] = []
        for value in times:
            if not any(abs(value - seen) < 0.15 for seen in unique_times):
                unique_times.append(value)

        frames: list[Path] = []
        for timestamp in unique_times:
            output = self.staging_dir / f"ai-frame-{uuid.uuid4().hex}.jpg"
            try:
                result = subprocess.run(
                    [
                        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{timestamp:.3f}", "-i", str(video_path),
                        "-map", "0:v:0", "-frames:v", "1", "-vf",
                        "scale=w='min(640,iw)':h=-2", "-an", "-q:v", "6", "-y", str(output),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0 and output.is_file() and output.stat().st_size:
                    frames.append(output)
                else:
                    output.unlink(missing_ok=True)
            except Exception:
                output.unlink(missing_ok=True)
        if not frames:
            thumbnail = self._ensure_video_thumbnail(video_path)
            if thumbnail and thumbnail.is_file():
                output = self.staging_dir / f"ai-frame-{uuid.uuid4().hex}.jpg"
                shutil.copyfile(thumbnail, output)
                frames.append(output)
        if not frames:
            raise GalleryError("无法从视频中截取可供模型评估的画面。")
        return frames

    @staticmethod
    def cleanup_video_frames(frames: list[Path]) -> None:
        for frame in frames:
            try:
                Path(frame).unlink(missing_ok=True)
            except OSError:
                pass

    def _gallery_thumbnail_path(self, media_path: Path) -> Path:
        return self.thumbnails_dir / f"gallery-{media_path.name}.jpg"

    def _ensure_gallery_thumbnail(
        self,
        media_path: Path,
        media_type: str,
        progress_callback=None,
        cancel_check=None,
    ) -> Path | None:
        """Return a small, persistent preview thumbnail for gallery cards."""
        thumbnail_path = self._gallery_thumbnail_path(media_path)
        if thumbnail_path.is_file():
            try:
                with Image.open(thumbnail_path) as thumbnail:
                    thumbnail.verify()
                if progress_callback:
                    progress_callback("video_preview", 100, "视频预览图已存在")
                return thumbnail_path
            except Exception:
                try:
                    thumbnail_path.unlink(missing_ok=True)
                except OSError:
                    return None

        source_path = media_path
        if media_type == "video":
            source_path = self._ensure_video_thumbnail(
                media_path,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            if source_path is None:
                return None
        if not source_path.is_file():
            return None

        temporary_path = self.thumbnails_dir / f".gallery-{uuid.uuid4().hex}.tmp"
        try:
            if progress_callback:
                progress_callback("video_preview", 88, "正在生成卡片缩略图")
            if cancel_check and cancel_check("video_preview"):
                raise ProcessingTaskCancelled("视频预览任务已取消。")
            with Image.open(source_path) as img:
                try:
                    img.seek(0)
                except EOFError:
                    pass
                frame = ImageOps.exif_transpose(img.copy())
                frame.thumbnail((240, 180), Image.Resampling.LANCZOS)
                if frame.mode in ("RGBA", "LA") or "transparency" in frame.info:
                    rgba = frame.convert("RGBA")
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    frame = background
                else:
                    frame = frame.convert("RGB")
                frame.save(temporary_path, format="JPEG", quality=58, optimize=True)
            with Image.open(temporary_path) as thumbnail:
                thumbnail.verify()
            os.replace(temporary_path, thumbnail_path)
            if progress_callback:
                progress_callback("video_preview", 100, "视频预览图已生成")
            return thumbnail_path
        except ProcessingTaskCancelled:
            raise
        except Exception:
            return None
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _thumbnail_data_url(path: Path) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _video_thumbnail_path(self, video_path: Path) -> Path:
        return self.thumbnails_dir / f"{video_path.stem}.jpg"

    def _ensure_video_thumbnail(
        self,
        video_path: Path,
        progress_callback=None,
        cancel_check=None,
    ) -> Path | None:
        thumbnail_path = self._video_thumbnail_path(video_path)
        if video_path.name in self._video_thumbnail_failures:
            return None
        if thumbnail_path.is_file():
            try:
                with Image.open(thumbnail_path) as thumbnail:
                    thumbnail.verify()
                if progress_callback:
                    progress_callback("video_preview", 75, "视频帧预览已存在")
                return thumbnail_path
            except Exception:
                try:
                    thumbnail_path.unlink(missing_ok=True)
                except OSError:
                    return None

        ffmpeg = self._ffmpeg_executable()
        if not ffmpeg:
            self._video_thumbnail_failures.add(video_path.name)
            if progress_callback:
                progress_callback("video_preview", 15, "未找到可用的 FFmpeg")
            return None

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for index, seek_seconds in enumerate(("1", "0")):
            if cancel_check and cancel_check("video_preview"):
                raise ProcessingTaskCancelled("视频预览任务已取消。")
            if progress_callback:
                progress_callback(
                    "video_preview",
                    15 + index * 25,
                    f"正在截取视频帧（尝试 {index + 1}/2）",
                )
            temporary_path = self.thumbnails_dir / f".{uuid.uuid4().hex}.jpg"
            try:
                process = subprocess.Popen(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        seek_seconds,
                        "-i",
                        str(video_path),
                        "-map",
                        "0:v:0",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=w='min(640,iw)':h=-2",
                        "-an",
                        "-q:v",
                        "5",
                        "-y",
                        str(temporary_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                started = time_module.monotonic()
                while process.poll() is None:
                    if cancel_check and cancel_check("video_preview"):
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise ProcessingTaskCancelled("视频预览任务已取消。")
                    if time_module.monotonic() - started > 20:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        break
                    time_module.sleep(0.15)
                if process.returncode != 0 or not temporary_path.is_file():
                    continue
                with Image.open(temporary_path) as thumbnail:
                    thumbnail.verify()
                os.replace(temporary_path, thumbnail_path)
                return thumbnail_path
            except ProcessingTaskCancelled:
                raise
            except Exception:
                continue
            finally:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        self._video_thumbnail_failures.add(video_path.name)
        return None

    def regenerate_video_preview(
        self,
        image_id: int,
        progress_callback=None,
        cancel_check=None,
    ) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT filename, media_type FROM images WHERE id = ?",
                (int(image_id),),
            ).fetchone()
        if not row:
            raise GalleryError("找不到该媒体。")
        if row["media_type"] != "video":
            raise GalleryError("该媒体不是视频，无法重建视频预览图。")
        video_path = self.images_dir / row["filename"]
        if not video_path.is_file():
            raise GalleryError("视频文件不存在。")
        self._video_thumbnail_failures.discard(video_path.name)
        self._video_thumbnail_path(video_path).unlink(missing_ok=True)
        self._gallery_thumbnail_path(video_path).unlink(missing_ok=True)
        result = self._ensure_gallery_thumbnail(
            video_path,
            "video",
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        if result is None:
            raise GalleryError("FFmpeg 未能从视频生成预览图。")
        return True

    def _remove_media_thumbnails(self, filename: str) -> None:
        with self._lock:
            self._video_thumbnail_failures.discard(filename)
            media_path = self.images_dir / filename
            for thumbnail_path in (
                self._video_thumbnail_path(media_path),
                self._gallery_thumbnail_path(media_path),
            ):
                try:
                    thumbnail_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def choose_image(
        self,
        category_id: str,
        image_id: int | None = None,
        allow_nsfw: bool = True,
    ) -> dict | None:
        with self._lock, self._connect() as db:
            nsfw_filter = "" if allow_nsfw else " AND is_nsfw = 0"
            if image_id is None:
                row = db.execute(
                    f"""SELECT * FROM images WHERE category_id = ?{nsfw_filter}
                       ORDER BY RANDOM() LIMIT 1""",
                    (category_id,),
                ).fetchone()
            else:
                row = db.execute(
                    f"SELECT * FROM images WHERE category_id = ? AND id = ?{nsfw_filter}",
                    (category_id, int(image_id)),
                ).fetchone()
        if not row:
            return None
        path = self.images_dir / row["filename"]
        if not path.is_file():
            return None
        return {
            "id": row["id"],
            "category_id": row["category_id"],
            "path": path,
            "created_at": row["created_at"],
            "is_nsfw": bool(row["is_nsfw"]),
            "media_type": row["media_type"],
        }

    def move_images(self, image_ids: list[int], target_category_id: str) -> dict:
        ids = sorted({int(value) for value in image_ids})
        if not ids:
            raise GalleryError("请选择要移动的媒体。")
        if len(ids) > 500:
            raise GalleryError("单次最多移动 500 个媒体。")

        placeholders = ",".join("?" for _ in ids)
        moved = 0
        skipped_duplicates = 0
        already_in_target = 0
        nsfw_marks_cleared = 0
        with self._lock, self._connect() as db:
            target = db.execute(
                "SELECT id, is_nsfw FROM categories WHERE id = ?",
                (target_category_id,),
            ).fetchone()
            if not target:
                raise GalleryError("找不到目标分类。")
            target_hashes = {
                row["sha256"]
                for row in db.execute(
                    "SELECT sha256 FROM images WHERE category_id = ?",
                    (target_category_id,),
                )
            }
            rows = db.execute(
                f"""SELECT i.id, i.category_id, i.sha256, i.is_nsfw,
                          c.is_nsfw AS source_category_nsfw
                    FROM images i JOIN categories c ON c.id = i.category_id
                    WHERE i.id IN ({placeholders}) ORDER BY i.id""",
                ids,
            ).fetchall()
            for row in rows:
                if row["category_id"] == target_category_id:
                    already_in_target += 1
                    continue
                if row["sha256"] in target_hashes:
                    skipped_duplicates += 1
                    continue
                source_is_nsfw = bool(row["is_nsfw"] or row["source_category_nsfw"])
                if target["is_nsfw"] and not source_is_nsfw:
                    db.execute(
                        """UPDATE images SET category_id = ?, is_nsfw = 1,
                           ai_tags = '[]', ai_description = '', description_override = '',
                           ai_status = 'manual_required', ai_error = '',
                           ai_provider_id = '', ai_updated_at = ''
                           WHERE id = ?""",
                        (target_category_id, row["id"]),
                    )
                    db.execute(
                        "DELETE FROM media_embeddings WHERE image_id = ?",
                        (row["id"],),
                    )
                    db.execute(
                        "DELETE FROM media_tags WHERE image_id = ? AND source = 'ai'",
                        (row["id"],),
                    )
                elif target_category_id == "pending" and not source_is_nsfw:
                    db.execute(
                        """UPDATE images SET category_id = ?, ai_tags = '[]',
                           ai_description = '', description_override = '', ai_status = 'not_evaluated',
                           ai_error = '', ai_provider_id = '', ai_updated_at = ''
                           WHERE id = ?""",
                        (target_category_id, row["id"]),
                    )
                    db.execute(
                        "DELETE FROM media_embeddings WHERE image_id = ?",
                        (row["id"],),
                    )
                    db.execute(
                        "DELETE FROM media_tags WHERE image_id = ? AND source = 'ai'",
                        (row["id"],),
                    )
                elif target_category_id == "pending":
                    db.execute(
                        "UPDATE images SET category_id = ?, is_nsfw = 1 WHERE id = ?",
                        (target_category_id, row["id"]),
                    )
                else:
                    if not target["is_nsfw"] and source_is_nsfw:
                        nsfw_marks_cleared += 1
                    db.execute(
                        "UPDATE images SET category_id = ?, is_nsfw = ? WHERE id = ?",
                        (target_category_id, int(bool(target["is_nsfw"])), row["id"]),
                    )
                target_hashes.add(row["sha256"])
                moved += 1
        return {
            "moved": moved,
            "skipped_duplicates": skipped_duplicates,
            "already_in_target": already_in_target,
            "nsfw_marks_cleared": nsfw_marks_cleared,
            "not_found": len(ids) - moved - skipped_duplicates - already_in_target,
        }

    def sfw_media_needing_evaluation(
        self, image_ids: list[int], target_category_id: str
    ) -> list[int]:
        ids = sorted({int(value) for value in image_ids})
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.id FROM images i
                    JOIN categories c ON c.id = i.category_id
                    WHERE i.id IN ({placeholders}) AND i.category_id = ?
                      AND i.is_nsfw = 0 AND c.is_nsfw = 0
                      AND i.ai_status = 'not_evaluated'""",
                [*ids, target_category_id],
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def choose_image_by_tag(
        self, tag: str, allow_nsfw: bool = True
    ) -> dict | None:
        tag = " ".join(str(tag or "").strip().split())
        if not tag or len(tag) > 32:
            raise GalleryError("请输入 1–32 个字符的标签关键词。")
        nsfw_filter = "" if allow_nsfw else " AND i.is_nsfw = 0 AND c.is_nsfw = 0"
        with self._lock, self._connect() as db:
            tag_terms = self._expanded_tag_terms(db, tag)
            tag_conditions = " OR ".join(
                "INSTR(LOWER(t.tag), LOWER(?)) > 0" for _ in tag_terms
            )
            row = db.execute(
                f"""SELECT i.*, c.name AS category_name
                    FROM images i JOIN categories c ON c.id = i.category_id
                    WHERE EXISTS (
                        SELECT 1 FROM media_tags t
                        WHERE t.image_id = i.id AND ({tag_conditions})
                    ){nsfw_filter}
                    ORDER BY RANDOM() LIMIT 1""",
                tag_terms,
            ).fetchone()
        if not row:
            return None
        path = self.images_dir / row["filename"]
        if not path.is_file():
            return None
        return {
            "id": row["id"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "path": path,
            "is_nsfw": bool(row["is_nsfw"]),
            "media_type": row["media_type"],
        }

    def delete_images(self, image_ids: list[int]) -> int:
        ids = sorted({int(value) for value in image_ids})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        trashed_at = self._now()
        columns = (
            "original_id, category_id, category_name, filename, sha256, size_bytes, "
            "width, height, image_format, source, created_at, is_nsfw, media_type, "
            "manual_tags, ai_tags, ai_description, description_override, ai_status, "
            "ai_error, ai_provider_id, ai_updated_at, trashed_at, embedding_scope, "
            "embedding_provider_id, embedding_fingerprint, embedding_dimension, "
            "embedding_vector, embedding_created_at, phash"
        )
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT i.*, c.name AS category_name,
                          COALESCE(e.scope, '') AS embedding_scope,
                          COALESCE(e.provider_id, '') AS embedding_provider_id,
                          COALESCE(e.provider_fingerprint, '') AS embedding_fingerprint,
                          COALESCE(e.dimension, 0) AS embedding_dimension,
                          e.vector AS embedding_vector,
                          COALESCE(e.created_at, '') AS embedding_created_at
                   FROM images i
                   JOIN categories c ON c.id = i.category_id
                   LEFT JOIN media_embeddings e ON e.image_id = i.id
                   WHERE i.id IN ({placeholders})""",
                ids,
            ).fetchall()
            for row in rows:
                values = (
                    row["id"], row["category_id"], row["category_name"],
                    row["filename"], row["sha256"], row["size_bytes"],
                    row["width"], row["height"], row["image_format"],
                    row["source"], row["created_at"], row["is_nsfw"],
                    row["media_type"], row["manual_tags"], row["ai_tags"],
                    row["ai_description"], row["description_override"],
                    row["ai_status"], row["ai_error"], row["ai_provider_id"],
                    row["ai_updated_at"], trashed_at, row["embedding_scope"],
                    row["embedding_provider_id"], row["embedding_fingerprint"],
                    row["embedding_dimension"], row["embedding_vector"],
                    row["embedding_created_at"], row["phash"],
                )
                values_sql = ", ".join("?" for _ in values)
                db.execute(
                    f"INSERT INTO media_trash ({columns}) VALUES ({values_sql})",
                    values,
                )
                db.execute("DELETE FROM images WHERE id = ?", (row["id"],))
        return len(rows)

    def list_trash(self, page: int = 1, page_size: int = 30) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), PAGE_SIZE_MAX))
        offset = (page - 1) * page_size
        with self._lock, self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM media_trash").fetchone()[0])
            rows = db.execute(
                """SELECT * FROM media_trash
                   ORDER BY trashed_at DESC, trash_id DESC LIMIT ? OFFSET ?""",
                (page_size, offset),
            ).fetchall()
        items = []
        for row in rows:
            path = self.images_dir / row["filename"]
            try:
                thumbnail_path = self._ensure_gallery_thumbnail(
                    path, row["media_type"]
                ) if path.is_file() else None
            except Exception:
                thumbnail_path = None
            items.append(
                {
                    "id": row["original_id"],
                    "category_id": row["category_id"],
                    "category_name": row["category_name"],
                "is_nsfw": bool(row["is_nsfw"] or row["category_nsfw"]),
                    "filename": row["filename"],
                    "size_bytes": row["size_bytes"],
                    "width": row["width"],
                    "height": row["height"],
                    "image_format": row["image_format"],
                    "media_type": row["media_type"],
                    "is_nsfw": bool(row["is_nsfw"]),
                    "manual_tags": self._decode_tags(row["manual_tags"]),
                    "ai_tags": self._decode_tags(row["ai_tags"]),
                    "ai_description": row["ai_description"],
                    "description_override": row["description_override"],
                    "description": row["description_override"] or row["ai_description"],
                    "ai_status": row["ai_status"],
                    "ai_error": row["ai_error"],
                    "embedding_ready": bool(row["embedding_provider_id"] and row["embedding_vector"]),
                    "trashed_at": row["trashed_at"],
                    "thumbnail": (
                        self._thumbnail_data_url(thumbnail_path)
                        if thumbnail_path is not None
                        else None
                    ),
                }
            )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    def restore_images(self, image_ids: list[int]) -> dict:
        ids = sorted({int(value) for value in image_ids})
        if not ids or len(ids) > 500:
            raise GalleryError("请选择 1–500 个回收站媒体。")
        placeholders = ",".join("?" for _ in ids)
        restored_ids: list[int] = []
        skipped_duplicates = 0
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM media_trash WHERE original_id IN ({placeholders})", ids
            ).fetchall()
            for row in rows:
                target = db.execute(
                    "SELECT id, is_nsfw FROM categories WHERE id = ?",
                    (row["category_id"],),
                ).fetchone()
                if not target:
                    target = db.execute(
                        "SELECT id, is_nsfw FROM categories WHERE id = 'pending'"
                    ).fetchone()
                if not target:
                    raise GalleryError("找不到可恢复媒体的目标分类。")
                target_category_id = target["id"]
                duplicate = db.execute(
                    "SELECT id FROM images WHERE category_id = ? AND sha256 = ?",
                    (target_category_id, row["sha256"]),
                ).fetchone()
                if duplicate:
                    skipped_duplicates += 1
                    continue
                if not (self.images_dir / row["filename"]).is_file():
                    raise GalleryError(
                        f"媒体编号 {row['original_id']} 的回收站文件缺失，未还原。"
                    )

                was_nsfw = bool(row["is_nsfw"])
                target_is_nsfw = bool(target["is_nsfw"])
                restored_is_nsfw = was_nsfw or target_is_nsfw
                clear_ai = (target_is_nsfw and not was_nsfw) or (
                    target_category_id == "pending" and not was_nsfw
                )
                manual_tags = self._decode_tags(row["manual_tags"])
                ai_tags = [] if clear_ai else self._decode_tags(row["ai_tags"])
                ai_description = "" if clear_ai else row["ai_description"]
                description_override = "" if clear_ai else row["description_override"]
                ai_error = "" if clear_ai else row["ai_error"]
                ai_provider_id = "" if clear_ai else row["ai_provider_id"]
                ai_updated_at = "" if clear_ai else row["ai_updated_at"]
                if restored_is_nsfw and (
                    clear_ai
                    or row["ai_status"] in {"processing", "queued", "pending", "not_evaluated"}
                ):
                    ai_status = "manual_required"
                elif target_category_id == "pending" and not restored_is_nsfw:
                    ai_status = "not_evaluated"
                elif row["ai_status"] in {"processing", "queued"}:
                    ai_status = "not_evaluated"
                else:
                    ai_status = row["ai_status"]

                db.execute(
                    """INSERT INTO images (
                        id, category_id, filename, sha256, size_bytes, width, height,
                        image_format, source, created_at, is_nsfw, media_type,
                        manual_tags, ai_tags, ai_description, description_override,
                        ai_status, ai_error, ai_provider_id, ai_updated_at, phash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["original_id"], target_category_id, row["filename"],
                        row["sha256"], row["size_bytes"], row["width"], row["height"],
                        row["image_format"], row["source"], row["created_at"],
                        int(restored_is_nsfw), row["media_type"],
                        json.dumps(manual_tags, ensure_ascii=False),
                        json.dumps(ai_tags, ensure_ascii=False), ai_description,
                        description_override, ai_status, ai_error, ai_provider_id,
                        ai_updated_at, row["phash"],
                    ),
                )
                self._sync_tag_index(db, int(row["original_id"]), manual_tags, ai_tags)
                embedding_scope = str(row["embedding_scope"] or "")
                expected_scope = "nsfw" if restored_is_nsfw else "sfw"
                if (
                    not clear_ai
                    and embedding_scope == expected_scope
                    and row["embedding_vector"] is not None
                    and int(row["embedding_dimension"] or 0) > 0
                ):
                    db.execute(
                        """INSERT OR REPLACE INTO media_embeddings
                           (image_id, scope, provider_id, provider_fingerprint,
                            dimension, vector, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["original_id"], embedding_scope,
                            row["embedding_provider_id"], row["embedding_fingerprint"],
                            row["embedding_dimension"], row["embedding_vector"],
                            row["embedding_created_at"] or self._now(),
                        ),
                    )
                db.execute(
                    "DELETE FROM media_trash WHERE original_id = ?",
                    (row["original_id"],),
                )
                restored_ids.append(int(row["original_id"]))

        return {
            "restored": len(restored_ids),
            "skipped_duplicates": skipped_duplicates,
            "not_found": len(ids) - len(restored_ids) - skipped_duplicates,
            "restored_ids": restored_ids,
        }

    def purge_trash_images(self, image_ids: list[int]) -> int:
        ids = sorted({int(value) for value in image_ids})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT filename FROM media_trash WHERE original_id IN ({placeholders})",
                ids,
            ).fetchall()
            db.execute(
                f"DELETE FROM media_trash WHERE original_id IN ({placeholders})", ids
            )
        self._remove_trashed_files(rows)
        return len(rows)

    def empty_trash(self) -> int:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT filename FROM media_trash").fetchall()
            db.execute("DELETE FROM media_trash")
        self._remove_trashed_files(rows)
        return len(rows)

    def _remove_trashed_files(self, rows: list[sqlite3.Row]) -> None:
        for row in rows:
            try:
                (self.images_dir / row["filename"]).unlink(missing_ok=True)
            except OSError:
                pass
            self._remove_media_thumbnails(row["filename"])

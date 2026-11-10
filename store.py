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
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, features


DEFAULT_CATEGORIES = (
    ("pending", "待处理", False),
    ("cos", "cos人像", False),
    ("scenery", "风景", False),
    ("meme", "梗图", False),
    ("nsfw", "NSFW", True),
)
ALLOWED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "BMP"}
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
MAX_IMAGE_DECODE_PIXELS = 40_000_000
MAX_ANIMATED_IMAGE_PIXELS = 40_000_000
PAGE_SIZE_MAX = 60


class GalleryError(ValueError):
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
                    UNIQUE(category_id, sha256)
                );
                CREATE TABLE IF NOT EXISTS media_tags (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    source TEXT NOT NULL CHECK (source IN ('manual', 'ai')),
                    PRIMARY KEY(image_id, tag, source)
                );
                CREATE INDEX IF NOT EXISTS idx_media_tags_tag ON media_tags(tag);
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
                        raise GalleryError("仅支持 JPG、PNG、GIF、WebP 和 BMP 图片。")
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

    def _compress_image_to_target(self, source_path: Path, target_bytes: int) -> Path:
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
                    for frame in ImageSequence.Iterator(source):
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

            for scale in scales:
                if scale < previous_scale:
                    width = max(1, round(base_width * scale))
                    height = max(1, round(base_height * scale))
                    resized_frames: list[Image.Image] = []
                    for frame in current_frames:
                        resized_frames.append(
                            frame.resize((width, height), Image.Resampling.LANCZOS)
                        )
                        frame.close()
                    current_frames = resized_frames
                    previous_scale = scale

                for quality in qualities:
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
        self, source_path: Path, target_bytes: int
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
            for _ in range(8):
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
                try:
                    result = subprocess.run(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=max(1, remaining_seconds),
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise GalleryError(
                        "视频自动压缩超过 30 分钟，未入库。"
                    ) from exc
                if result.returncode != 0 or not output_path.is_file():
                    error_text = str(result.stderr or "").lower()
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
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def add_media(
        self,
        source_path: str | Path,
        category_id: str,
        media_type: str,
        source: str,
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
        try:
            shutil.copyfile(source_path, staging_path)
            source_size = staging_path.stat().st_size
            if source_size > source_limit_bytes:
                limit_mb = source_limit_bytes // (1024 * 1024)
                media_label = "视频" if media_type == "video" else "图片"
                raise GalleryError(
                    f"{media_label}原始文件不能超过接收上限 {limit_mb} MB。"
                )

            if media_type == "video":
                self._inspect_video(staging_path, self.max_source_video_bytes)
                if source_size > target_bytes:
                    compressed_path = self._compress_video_to_target(
                        staging_path, target_bytes
                    )
                    prepared_path = compressed_path
                media_format, width, height, size = self._inspect_video(prepared_path)
                suffix = VIDEO_SUFFIXES[media_format]
            else:
                self._inspect_image(staging_path, self.max_source_image_bytes)
                if source_size > target_bytes:
                    compressed_path = self._compress_image_to_target(
                        staging_path, target_bytes
                    )
                    prepared_path = compressed_path
                media_format, width, height, size = self._inspect_image(prepared_path)
                suffix = FORMAT_SUFFIXES[media_format]
            compressed = compressed_path is not None
            digest = self._hash_file(prepared_path)
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
                        "original_size_bytes": source_size,
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
                            image_format, source, created_at, is_nsfw, media_type)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            try:
                self._ensure_gallery_thumbnail(final_path, media_type)
            except Exception:
                # Thumbnail creation must not invalidate an otherwise successful import.
                pass
            return {
                "id": image_id,
                "duplicate": False,
                "filename": filename,
                "size_bytes": size,
                "original_size_bytes": source_size,
                "compressed": compressed,
                "width": width,
                "height": height,
                "media_type": media_type,
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

    def list_images(
        self,
        category_id: str,
        page: int = 1,
        page_size: int = 30,
        tag: str = "",
    ) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), PAGE_SIZE_MAX))
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
                tag_filter = " AND EXISTS (SELECT 1 FROM media_tags t WHERE t.image_id = images.id AND t.tag = ? COLLATE NOCASE)"
                params.append(tag.strip())
            total = db.execute(
                f"SELECT COUNT(*) FROM images WHERE category_id = ?{tag_filter}",
                params,
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT images.*,
                          (SELECT provider_id FROM media_embeddings WHERE image_id = images.id)
                            AS vector_provider_id
                   FROM images WHERE category_id = ?{tag_filter}
                   ORDER BY id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, offset],
            ).fetchall()
        items = []
        for row in rows:
            path = self.images_dir / row["filename"]
            if not path.is_file():
                continue
            try:
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
                f"""SELECT i.id, i.ai_description, i.description_override, i.ai_tags
                    FROM images i JOIN categories c ON c.id = i.category_id
                    WHERE {safety_filter}
                    ORDER BY i.id"""
            ).fetchall()
        candidates = []
        for row in rows:
            description = str(row["description_override"] or row["ai_description"] or "").strip()
            tags = self._decode_tags(row["ai_tags"])
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
        self, media_path: Path, media_type: str
    ) -> Path | None:
        """Return a small, persistent preview thumbnail for gallery cards."""
        thumbnail_path = self._gallery_thumbnail_path(media_path)
        if thumbnail_path.is_file():
            try:
                with Image.open(thumbnail_path) as thumbnail:
                    thumbnail.verify()
                return thumbnail_path
            except Exception:
                try:
                    thumbnail_path.unlink(missing_ok=True)
                except OSError:
                    return None

        source_path = media_path
        if media_type == "video":
            source_path = self._ensure_video_thumbnail(media_path)
            if source_path is None:
                return None
        if not source_path.is_file():
            return None

        temporary_path = self.thumbnails_dir / f".gallery-{uuid.uuid4().hex}.tmp"
        try:
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
            return thumbnail_path
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

    def _ensure_video_thumbnail(self, video_path: Path) -> Path | None:
        thumbnail_path = self._video_thumbnail_path(video_path)
        with self._lock:
            if video_path.name in self._video_thumbnail_failures:
                return None
            if thumbnail_path.is_file():
                try:
                    with Image.open(thumbnail_path) as thumbnail:
                        thumbnail.verify()
                    return thumbnail_path
                except Exception:
                    try:
                        thumbnail_path.unlink(missing_ok=True)
                    except OSError:
                        return None

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                try:
                    import imageio_ffmpeg

                    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    self._video_thumbnail_failures.add(video_path.name)
                    return None

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for seek_seconds in ("1", "0"):
                temporary_path = self.thumbnails_dir / f".{uuid.uuid4().hex}.jpg"
                try:
                    result = subprocess.run(
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
                        timeout=20,
                        check=False,
                        creationflags=creationflags,
                    )
                    if result.returncode != 0 or not temporary_path.is_file():
                        continue
                    with Image.open(temporary_path) as thumbnail:
                        thumbnail.verify()
                    os.replace(temporary_path, thumbnail_path)
                    return thumbnail_path
                except Exception:
                    continue
                finally:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            self._video_thumbnail_failures.add(video_path.name)
        return None

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
            row = db.execute(
                f"""SELECT i.*, c.name AS category_name
                    FROM images i JOIN categories c ON c.id = i.category_id
                    WHERE EXISTS (
                        SELECT 1 FROM media_tags t
                        WHERE t.image_id = i.id
                          AND INSTR(LOWER(t.tag), LOWER(?)) > 0
                    ){nsfw_filter}
                    ORDER BY RANDOM() LIMIT 1""",
                (tag,),
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
            "embedding_vector, embedding_created_at"
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
            values_sql = ", ".join("?" for _ in range(28))
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
                    row["embedding_created_at"],
                )
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
                        ai_status, ai_error, ai_provider_id, ai_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["original_id"], target_category_id, row["filename"],
                        row["sha256"], row["size_bytes"], row["width"], row["height"],
                        row["image_format"], row["source"], row["created_at"],
                        int(restored_is_nsfw), row["media_type"],
                        json.dumps(manual_tags, ensure_ascii=False),
                        json.dumps(ai_tags, ensure_ascii=False), ai_description,
                        description_override, ai_status, ai_error, ai_provider_id,
                        ai_updated_at,
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

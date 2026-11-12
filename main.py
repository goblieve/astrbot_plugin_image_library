from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import time as time_module
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain, Reply, Video
from astrbot.api.star import Context, Star
from astrbot.api.web import PluginUploadFile, error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .ai import (
    DEFAULT_NSFW_EVALUATION_PROMPT,
    DEFAULT_SFW_EVALUATION_PROMPT,
    MediaAI,
    create_embedding,
    embedding_fingerprint,
    evaluation_prompt_version,
)
from .store import GalleryError, GalleryStore, ProcessingTaskCancelled


PLUGIN_NAME = "astrbot_plugin_image_library"
WEB_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
WEB_UPLOAD_SESSION_TTL_SECONDS = 3600
WEB_UPLOAD_JOB_TTL_SECONDS = 3600
MIRAGE_REFERENCE_TTL_SECONDS = 600


@filter.command_group("图集", alias={"图库"})
def image_library_group():
    pass


class ImageLibraryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        max_image_size_mb = config.get("max_image_size_mb", 20)
        max_video_size_mb = config.get("max_video_size_mb", 100)
        compress_oversized_media = config.get("compress_oversized_media", True)
        max_source_image_size_mb = config.get("max_source_image_size_mb", 200)
        max_source_video_size_mb = config.get("max_source_video_size_mb", 500)
        self.store = GalleryStore(
            self.data_dir,
            max_image_size_mb=max_image_size_mb,
            max_video_size_mb=max_video_size_mb,
            compress_oversized_media=compress_oversized_media,
            max_source_image_size_mb=max_source_image_size_mb,
            max_source_video_size_mb=max_source_video_size_mb,
        )
        self.store.mark_interrupted_processing_tasks()
        self.sfw_evaluation_provider_id = str(
            config.get("sfw_evaluation_provider_id", "") or ""
        ).strip()
        self.nsfw_evaluation_provider_id = str(
            config.get("nsfw_evaluation_provider_id", "") or ""
        ).strip()
        self.sfw_evaluation_prompt = str(
            config.get("sfw_evaluation_prompt", DEFAULT_SFW_EVALUATION_PROMPT) or ""
        )
        self.nsfw_evaluation_prompt = str(
            config.get("nsfw_evaluation_prompt", DEFAULT_NSFW_EVALUATION_PROMPT) or ""
        )
        self.embedding_provider_id = str(
            config.get("embedding_provider_id", "") or ""
        ).strip()
        self.media_ai = MediaAI(
            self.context,
            self.store,
            logger,
            self.sfw_evaluation_prompt,
            self.nsfw_evaluation_prompt,
        )
        self._evaluation_semaphore = asyncio.Semaphore(1)
        self._web_upload_semaphore = asyncio.Semaphore(1)
        self._web_upload_sessions: dict[str, dict] = {}
        self._web_upload_jobs: dict[str, dict] = {}
        self._web_upload_tasks: set[asyncio.Task] = set()
        self._web_upload_stopping = False
        self._ai_tasks: set[asyncio.Task] = set()
        self._ai_queued_ids: set[tuple[str, int]] = set()
        self._processing_tasks: dict[str, asyncio.Task] = {}
        self._processing_task_keys: dict[tuple[str, int], str] = {}
        self._embedding_reschedule_requests: dict[tuple[str, int], tuple[str, str]] = {}
        self._embedding_semaphore = asyncio.Semaphore(1)
        self._video_preview_semaphore = asyncio.Semaphore(1)
        self._trash_cleanup_task: asyncio.Task | None = None
        self._mirage_pending_cleanup_task: asyncio.Task | None = None
        self._mirage_pending_covers: dict[str, dict] = {}
        self._embedding_job: dict | None = None
        self._embedding_job_task: asyncio.Task | None = None
        self._duplicate_job: dict | None = None
        self._duplicate_job_task: asyncio.Task | None = None
        self._duplicate_scan_results: dict | None = None
        self._register_web_apis()
        logger.info(f"{PLUGIN_NAME} 已就绪，数据目录：{self.data_dir}")

    def _register_web_apis(self) -> None:
        routes = (
            (f"/{PLUGIN_NAME}/categories", self.web_categories, ["GET"], "List media categories"),
            (f"/{PLUGIN_NAME}/categories/create", self.web_create_category, ["POST"], "Create media category"),
            (f"/{PLUGIN_NAME}/categories/delete", self.web_delete_category, ["POST"], "Delete category and move its media to pending"),
            (f"/{PLUGIN_NAME}/categories/<category_id>/upload", self.web_upload_image, ["POST"], "Upload an image or video"),
            (f"/{PLUGIN_NAME}/categories/<category_id>/upload/start", self.web_upload_start, ["POST"], "Start a chunked media upload"),
            (f"/{PLUGIN_NAME}/categories/<category_id>/upload/chunk/<upload_id>/<index>", self.web_upload_chunk, ["POST"], "Upload a media chunk"),
            (f"/{PLUGIN_NAME}/categories/<category_id>/upload/complete", self.web_upload_complete, ["POST"], "Complete a chunked media upload"),
            (f"/{PLUGIN_NAME}/upload/cancel", self.web_upload_cancel, ["POST"], "Cancel a chunked media upload"),
            (f"/{PLUGIN_NAME}/upload/status", self.web_upload_status, ["GET"], "Read media import status"),
            (f"/{PLUGIN_NAME}/images", self.web_images, ["GET"], "List media in a category"),
            (f"/{PLUGIN_NAME}/mirage/source", self.web_mirage_source, ["POST"], "Load a library image for phantom-tank creation"),
            (f"/{PLUGIN_NAME}/mirage/settings", self.web_mirage_settings, ["GET"], "Read phantom-tank settings"),
            (f"/{PLUGIN_NAME}/mirage/settings/save", self.web_save_mirage_settings, ["POST"], "Save phantom-tank settings"),
            (f"/{PLUGIN_NAME}/mirage/save", self.web_save_mirage, ["POST"], "Generate and store a phantom-tank image"),
            (f"/{PLUGIN_NAME}/images/delete", self.web_delete_images, ["POST"], "Move selected media to trash"),
            (f"/{PLUGIN_NAME}/trash", self.web_trash, ["GET"], "List trashed media"),
            (f"/{PLUGIN_NAME}/trash/restore", self.web_restore_trash, ["POST"], "Restore trashed media"),
            (f"/{PLUGIN_NAME}/trash/delete", self.web_purge_trash_images, ["POST"], "Permanently delete trashed media"),
            (f"/{PLUGIN_NAME}/trash/empty", self.web_empty_trash, ["POST"], "Empty media trash"),
            (f"/{PLUGIN_NAME}/images/move", self.web_move_images, ["POST"], "Move selected media to another category"),
            (f"/{PLUGIN_NAME}/images/tags", self.web_update_tags, ["POST"], "Maintain media tags"),
            (f"/{PLUGIN_NAME}/tags/taxonomy", self.web_tag_taxonomy, ["GET"], "List tag aliases and hierarchy"),
            (f"/{PLUGIN_NAME}/tags/aliases/save", self.web_save_tag_alias, ["POST"], "Create or update a tag alias"),
            (f"/{PLUGIN_NAME}/tags/aliases/delete", self.web_delete_tag_alias, ["POST"], "Delete a tag alias"),
            (f"/{PLUGIN_NAME}/tags/hierarchy/save", self.web_save_tag_parent, ["POST"], "Create or update a tag parent"),
            (f"/{PLUGIN_NAME}/tags/hierarchy/delete", self.web_delete_tag_parent, ["POST"], "Delete a tag parent"),
            (f"/{PLUGIN_NAME}/tags/normalize/preview", self.web_preview_tag_normalization, ["POST"], "Preview explicit tag normalization"),
            (f"/{PLUGIN_NAME}/tags/normalize/apply", self.web_apply_tag_normalization, ["POST"], "Apply confirmed tag normalization"),
            (f"/{PLUGIN_NAME}/images/details", self.web_update_media_details, ["POST"], "Edit media description and tags"),
            (f"/{PLUGIN_NAME}/duplicates/scan", self.web_duplicates_scan, ["POST"], "Scan cross-category exact duplicates and similar images"),
            (f"/{PLUGIN_NAME}/duplicates/status", self.web_duplicates_status, ["GET"], "Read duplicate scan progress"),
            (f"/{PLUGIN_NAME}/duplicates/results", self.web_duplicates_results, ["GET"], "List duplicate scan results"),
            (f"/{PLUGIN_NAME}/ai/providers", self.web_ai_providers, ["GET"], "List available AI providers"),
            (f"/{PLUGIN_NAME}/tasks", self.web_processing_tasks, ["GET"], "List media processing tasks"),
            (f"/{PLUGIN_NAME}/tasks/action", self.web_processing_task_action, ["POST"], "Retry or cancel a media processing task"),
            (f"/{PLUGIN_NAME}/tasks/reassess", self.web_reassess_stale_media, ["POST"], "Re-evaluate media with stale prompt or model versions"),
            (f"/{PLUGIN_NAME}/ai/evaluate", self.web_ai_evaluate, ["POST"], "Evaluate selected media"),
            (f"/{PLUGIN_NAME}/ai/search", self.web_ai_search, ["POST"], "Search media by semantic similarity"),
            (f"/{PLUGIN_NAME}/ai/reindex", self.web_ai_reindex, ["POST"], "Rebuild semantic embeddings by safety scope"),
            (f"/{PLUGIN_NAME}/ai/reindex/status", self.web_ai_reindex_status, ["GET"], "Read semantic reindex progress"),
        )
        for route, handler, methods, description in routes:
            self.context.register_web_api(route, handler, methods, description)

    @staticmethod
    def _config_list(config: dict, key: str) -> set[str]:
        raw = config.get(key, [])
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def _may_view_nsfw(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        if str(event.get_sender_id()) in self._config_list(
            self.config, "nsfw_allowed_users"
        ):
            return True
        group_id = event.get_group_id()
        return bool(
            group_id
            and str(group_id)
            in self._config_list(self.config, "nsfw_allowed_groups")
        )

    def _schedule_ai_evaluation(
        self,
        image_id: int,
        scope: str,
        provider_id: str = "",
        *,
        force: bool = False,
        batch_id: str = "",
        retry_of: str = "",
    ) -> str | None:
        key = (scope, int(image_id))
        existing_id = self._processing_task_keys.get(("ai_evaluation", int(image_id)))
        existing = self._processing_tasks.get(existing_id or "")
        if existing_id and existing and not existing.done():
            return None if force or batch_id else existing_id
        self._ai_queued_ids.add(key)
        chosen_provider_id = provider_id or (
            self.nsfw_evaluation_provider_id
            if scope == "nsfw"
            else self.sfw_evaluation_provider_id
        )
        prompt = self.media_ai.nsfw_evaluation_prompt if scope == "nsfw" else self.media_ai.sfw_evaluation_prompt
        task_id = self.store.create_processing_task(
            "ai_evaluation",
            media_id=int(image_id),
            scope=scope,
            model_id=chosen_provider_id,
            prompt_version=evaluation_prompt_version(prompt),
            batch_id=batch_id,
            retry_of=retry_of,
            metadata={"force": bool(force)},
            message="等待视觉评估模型",
        )
        task = asyncio.create_task(
            self._run_ai_evaluation(task_id, image_id, scope, chosen_provider_id, force),
            name=f"{PLUGIN_NAME}-ai-{scope}-{image_id}-{task_id[:8]}",
        )
        self._ai_tasks.add(task)
        self._processing_tasks[task_id] = task
        self._processing_task_keys[("ai_evaluation", int(image_id))] = task_id
        task.add_done_callback(
            lambda completed, processing_id=task_id, processing_key=("ai_evaluation", int(image_id)), ai_key=key:
                self._finish_processing_task(completed, processing_id, processing_key, ai_key)
        )
        return task_id

    def _finish_processing_task(
        self,
        task: asyncio.Task,
        task_id: str,
        processing_key: tuple[str, int] | None = None,
        ai_key: tuple[str, int] | None = None,
    ) -> None:
        self._processing_tasks.pop(task_id, None)
        if processing_key is not None:
            if self._processing_task_keys.get(processing_key) == task_id:
                self._processing_task_keys.pop(processing_key, None)
        if ai_key is not None:
            self._ai_tasks.discard(task)
            self._ai_queued_ids.discard(ai_key)
        try:
            row = self.store.get_processing_task(task_id)
        except Exception:
            row = None
        if row and row.get("status") in {"queued", "running"}:
            try:
                self.store.update_processing_task(
                    task_id,
                    status="failed",
                    error="任务意外退出。",
                    message="任务意外退出，可从任务中心重试。",
                )
                row["status"] = "failed"
            except Exception:
                pass
        if processing_key and processing_key[0] == "semantic_index":
            pending = self._embedding_reschedule_requests.pop(processing_key, None)
            current_id = self._processing_task_keys.get(processing_key)
            if (
                pending
                and current_id != task_id
                and (not row or row.get("status") != "cancelled")
            ):
                try:
                    self._schedule_embedding_task(
                        processing_key[1],
                        pending[0],
                        pending[1],
                    )
                except Exception as exc:
                    logger.warning(
                        f"媒体 {processing_key[1]} 的语义索引自动补建失败：{exc}"
                    )

    async def _run_ai_evaluation(
        self,
        task_id: str,
        image_id: int,
        scope: str,
        provider_id: str = "",
        force: bool = False,
    ) -> None:
        try:
            async with self._evaluation_semaphore:
                self.store.update_processing_task(
                    task_id,
                    status="running",
                    progress=5,
                    message="正在请求视觉模型",
                )
                result = await self.media_ai.evaluate(
                    image_id,
                    scope,
                    provider_id,
                    force=force,
                )
                if result.get("skipped"):
                    self.store.update_processing_task(
                        task_id,
                        status="skipped",
                        progress=100,
                        message="媒体已有描述或手动描述，已跳过",
                    )
                    return
                self.store.update_processing_task(
                    task_id,
                    status="succeeded",
                    progress=100,
                    message="描述和 AI 标签已保存",
                )
                if self.embedding_provider_id:
                    self._schedule_embedding_task(
                        image_id,
                        scope,
                        self.embedding_provider_id,
                    )
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(
                    self.store.set_ai_status,
                    image_id,
                    scope,
                    "failed",
                    "评估任务已取消，可从任务中心重试。",
                    provider_id,
                )
            except Exception:
                pass
            try:
                self.store.update_processing_task(
                    task_id,
                    status="cancelled",
                    error="任务已取消。",
                    message="已取消",
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.warning(f"图集媒体 {image_id} 的 {scope.upper()} 评估失败：{exc}")
            try:
                await asyncio.to_thread(
                    self.store.set_ai_status,
                    image_id,
                    scope,
                    "failed",
                    str(exc),
                    provider_id,
                )
            except Exception:
                pass
            self.store.update_processing_task(
                task_id,
                status="failed",
                error=str(exc),
                message="视觉评估失败，可从任务中心重试",
            )

    def _schedule_embedding_task(
        self,
        image_id: int,
        scope: str,
        provider_id: str,
        *,
        batch_id: str = "",
        retry_of: str = "",
    ) -> str | None:
        key = ("semantic_index", int(image_id))
        existing_id = self._processing_task_keys.get(key)
        existing = self._processing_tasks.get(existing_id or "")
        if existing_id and existing and not existing.done():
            if batch_id:
                return None
            self._embedding_reschedule_requests[key] = (scope, provider_id)
            return existing_id
        task_id = self.store.create_processing_task(
            "semantic_index",
            media_id=int(image_id),
            scope=scope,
            model_id=provider_id,
            batch_id=batch_id,
            retry_of=retry_of,
            metadata={},
            message="等待 Embedding 服务",
        )
        task = asyncio.create_task(
            self._run_embedding_task(
                task_id,
                int(image_id),
                scope,
                provider_id,
            ),
            name=f"{PLUGIN_NAME}-embedding-{scope}-{image_id}-{task_id[:8]}",
        )
        self._processing_tasks[task_id] = task
        self._processing_task_keys[key] = task_id
        task.add_done_callback(
            lambda completed, processing_id=task_id, processing_key=key:
                self._finish_processing_task(completed, processing_id, processing_key)
        )
        return task_id

    async def _run_embedding_task(
        self,
        task_id: str,
        image_id: int,
        scope: str,
        provider_id: str,
    ) -> None:
        try:
            async with self._embedding_semaphore:
                self.store.update_processing_task(
                    task_id,
                    status="running",
                    progress=10,
                    message="正在读取媒体描述并连接 Embedding 服务",
                )
                if self.store.processing_task_cancel_requested(task_id):
                    raise asyncio.CancelledError()
                searchable_text = await asyncio.to_thread(
                    self.store.embedding_text_for_media,
                    image_id,
                    scope,
                )
                provider = self.context.get_provider_by_id(provider_id)
                if not provider:
                    raise GalleryError("Embedding 提供商当前不可用。")
                self.store.update_processing_task(
                    task_id, progress=35, message="正在生成语义向量"
                )
                vector = await create_embedding(provider, searchable_text)
                if self.store.processing_task_cancel_requested(task_id):
                    raise asyncio.CancelledError()
                latest_text = await asyncio.to_thread(
                    self.store.embedding_text_for_media,
                    image_id,
                    scope,
                )
                if latest_text != searchable_text:
                    raise GalleryError("媒体描述或标签在建索引期间发生变化，请重试该索引任务。")
                fingerprint = embedding_fingerprint(provider, provider_id)
                await asyncio.to_thread(
                    self.store.save_embedding,
                    image_id,
                    scope,
                    provider_id,
                    fingerprint,
                    vector,
                )
                self.store.update_processing_task(
                    task_id,
                    status="succeeded",
                    progress=100,
                    message="语义索引已建立",
                )
        except asyncio.CancelledError:
            self.store.update_processing_task(
                task_id,
                status="cancelled",
                error="语义索引任务已取消。",
                message="已取消",
            )
            raise
        except Exception as exc:
            logger.warning(f"语义索引失败（媒体 {image_id}）：{exc}")
            self.store.update_processing_task(
                task_id,
                status="failed",
                error=str(exc),
                message="语义索引失败，可从任务中心重试",
            )

    async def _run_embedding_batch(self, job: dict, tasks: list[asyncio.Task]) -> None:
        try:
            # A task-center cancellation applies to one media item. Do not let
            # gather propagate that child's CancelledError and cancel the rest
            # of the reindex batch.
            await asyncio.gather(*tasks, return_exceptions=True)
            summary = self.store.processing_task_batch_summary(job["job_id"])
            job.update(summary)
            job["status"] = "completed"
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            job["status"] = "cancelled"
            raise

    async def initialize(self):
        self._cleanup_expired_mirage_covers(remove_all=True)
        self._trash_cleanup_task = asyncio.create_task(
            self._trash_cleanup_loop(), name=f"{PLUGIN_NAME}-trash-cleanup"
        )
        self._mirage_pending_cleanup_task = asyncio.create_task(
            self._mirage_pending_cleanup_loop(),
            name=f"{PLUGIN_NAME}-mirage-reference-cleanup",
        )

    async def _trash_cleanup_loop(self):
        while True:
            now = datetime.now().astimezone()
            next_midnight = datetime.combine(
                now.date() + timedelta(days=1), time.min
            ).astimezone()
            await asyncio.sleep(max(1.0, (next_midnight - now).total_seconds()))
            while True:
                try:
                    removed = await asyncio.to_thread(self.store.empty_trash)
                    if removed:
                        logger.info(f"回收站每日清理完成，永久删除 {removed} 个媒体。")
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception(f"回收站每日清理失败，将在 60 秒后重试：{exc}")
                    await asyncio.sleep(60)

    async def _mirage_pending_cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            self._cleanup_expired_mirage_covers()

    def _cleanup_expired_mirage_covers(self, *, remove_all: bool = False):
        now = time_module.time()
        for key, pending in list(self._mirage_pending_covers.items()):
            if remove_all or now - float(pending.get("created_at", 0)) > MIRAGE_REFERENCE_TTL_SECONDS:
                self._clear_mirage_pending_cover(key)
        if remove_all:
            for path in self.store.staging_dir.glob("mirage-pending-cover-*.source"):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _clear_mirage_pending_cover(self, key: str):
        pending = self._mirage_pending_covers.pop(key, None)
        if not pending:
            return
        try:
            Path(pending["path"]).unlink(missing_ok=True)
        except (KeyError, OSError, TypeError):
            pass

    def _mirage_pending_key(self, event: AstrMessageEvent) -> str:
        return "|".join(
            (
                str(event.get_platform_name() or ""),
                str(event.get_session_id() or ""),
                str(event.get_sender_id() or ""),
            )
        )

    async def _quoted_mirage_images(self, event: AstrMessageEvent) -> list[Image]:
        media_items: list[Image] = []

        def collect(components):
            for component in components or []:
                if isinstance(component, Image):
                    media_items.append(component)
                elif isinstance(component, Reply):
                    collect(component.chain or [])

        collect(event.get_messages())
        if not media_items and event.get_platform_name() == "weixin_oc":
            message_obj = getattr(event, "message_obj", None)
            ref_msg = getattr(message_obj, "ref_msg", None)
            platform = getattr(event, "platform", None)
            reply_resolver = getattr(platform, "_build_reply_component_from_ref", None)
            if isinstance(ref_msg, dict) and callable(reply_resolver):
                try:
                    recovered_reply, _ = await reply_resolver(
                        session_id=event.get_session_id(),
                        ref_msg=ref_msg,
                    )
                    if recovered_reply is not None:
                        collect([recovered_reply])
                except Exception as exc:
                    logger.warning(f"微信幻影坦克引用图片解析失败：{exc}")
        return media_items

    async def _resolve_mirage_chat_image(self, image: Image) -> Path:
        try:
            image_path = Path(await image.convert_to_file_path())
            file_size = image_path.stat().st_size
        except Exception as exc:
            raise GalleryError("引用图片无法下载或读取。") from exc
        if not image_path.is_file():
            raise GalleryError("引用图片文件不存在。")
        if file_size > self.store.max_source_image_bytes:
            limit_mb = self.store.max_source_image_bytes // (1024 * 1024)
            raise GalleryError(f"引用图片超过接收上限 {limit_mb} MB。")
        return image_path

    async def _remember_mirage_cover(self, key: str, source_path: Path):
        self._cleanup_expired_mirage_covers()
        destination = self.store.staging_dir / (
            f"mirage-pending-cover-{uuid.uuid4().hex}.source"
        )
        try:
            await asyncio.to_thread(shutil.copyfile, source_path, destination)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise GalleryError("无法暂存表图，请检查插件临时目录空间。") from exc

        if key not in self._mirage_pending_covers and len(self._mirage_pending_covers) >= 100:
            oldest_key = min(
                self._mirage_pending_covers,
                key=lambda item: self._mirage_pending_covers[item].get("created_at", 0),
            )
            self._clear_mirage_pending_cover(oldest_key)
        self._clear_mirage_pending_cover(key)
        self._mirage_pending_covers[key] = {
            "path": str(destination),
            "created_at": time_module.time(),
        }

    async def _generate_and_store_mirage(
        self,
        cover_path: Path,
        inner_path: Path,
        display_name: str,
    ) -> dict:
        target = await asyncio.to_thread(
            self.store.ensure_nsfw_category, "幻影坦克"
        )
        settings = await asyncio.to_thread(self.store.get_mirage_settings)
        output_path = self.store.staging_dir / f"{uuid.uuid4().hex}.png"
        try:
            await asyncio.to_thread(
                self.store.create_mirage_png_from_paths,
                cover_path,
                inner_path,
                output_path,
                settings,
            )
            return await self._ingest_media_with_tasks(
                output_path,
                target["id"],
                "image",
                "chat",
                display_name=display_name,
            )
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def terminate(self):
        self._web_upload_stopping = True
        try:
            await asyncio.to_thread(
                self.store.request_cancel_all_active_processing_tasks
            )
        except Exception:
            pass
        for upload_id, session in list(self._web_upload_sessions.items()):
            self._clear_web_upload_session(upload_id, session)
        self._web_upload_sessions.clear()
        tasks = set(self._processing_tasks.values())
        if self._trash_cleanup_task:
            tasks.add(self._trash_cleanup_task)
        if self._mirage_pending_cleanup_task:
            tasks.add(self._mirage_pending_cleanup_task)
        if self._embedding_job_task:
            tasks.add(self._embedding_job_task)
        if self._duplicate_job_task:
            tasks.add(self._duplicate_job_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cleanup_expired_mirage_covers(remove_all=True)

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @image_library_group.command("帮助")
    async def command_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "图片收藏指令：\n"
            "/收藏 [分类]（省略分类时放入待处理；附上图片/视频或回复含媒体的消息；仅 AstrBot 管理员）\n"
            "分类不存在时会自动创建。\n"
            "/幻影 <表图编号> <里图编号>（管理员；成品保存到 NSFW「幻影坦克」分类）\n"
            "也可分两次引用图片：先引用表图发送 /幻影，再引用里图发送 /幻影。\n"
            "/看 <分类> [媒体编号]（不填编号时随机查看）\n"
            "/搜图 <标签关键词>（模糊匹配标签/别名；搜父标签时包含子标签，并随机返回图片或视频）\n"
            "/语义搜索 <画面描述>（按语义匹配并随机返回一张图片）\n"
            "/分类（查看可用分类）\n"
            "/图集 删除 <媒体编号>（移入回收站，仅管理员）\n"
            "/图集 帮助\n"
            "支持 JPG、MPO、PNG、GIF、WebP、BMP、MP4、MOV、3GP、AVI、MKV、WebM。\n"
            "MPO 会提取主画面并转换为普通 JPEG。\n"
            "WebUI 可批量导入、移动、回收站管理和管理媒体分类：插件 → QQ/个人微信图片与视频图集。"
        )

    async def _resolve_video_path(
        self, event: AstrMessageEvent, video: Video
    ) -> str:
        try:
            return await video.convert_to_file_path()
        except Exception as original_error:
            bot = getattr(event, "bot", None)
            file_ref = video.file or video.url
            if not bot or not file_ref:
                raise

            try:
                result = await bot.call_action(
                    action="get_file",
                    file=file_ref,
                    type="video",
                )
                data = result.get("data", result) if isinstance(result, dict) else {}
                if isinstance(data, dict):
                    for key in ("path", "file", "url"):
                        candidate = data.get(key)
                        if not isinstance(candidate, str) or not candidate or candidate == file_ref:
                            continue
                        try:
                            return await Video(file=candidate).convert_to_file_path()
                        except Exception:
                            continue
            except Exception as recovery_error:
                logger.debug(f"NapCat get_file 视频回退失败: {recovery_error}")
            raise original_error

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("收藏", alias={"存"})
    async def command_save(
        self, event: AstrMessageEvent, category: str | None = None
    ):
        category = str(category or "").strip() or "待处理"
        media_items = []
        seen = set()

        def collect_media(components):
            for component in components or []:
                if isinstance(component, (Image, Video)):
                    identity = (
                        type(component).__name__,
                        component.file
                        or component.url
                        or component.path
                        or repr(component),
                    )
                    if identity not in seen:
                        seen.add(identity)
                        media_items.append(component)
                elif isinstance(component, Reply):
                    collect_media(component.chain or [])

        collect_media(event.get_messages())

        # Weixin OC may retain the original ref_msg on AstrBotMessage even when
        # command dispatch does not expose the Reply component in the message chain.
        # Ask the adapter to resolve that reference as a fallback.
        if not media_items and event.get_platform_name() == "weixin_oc":
            message_obj = getattr(event, "message_obj", None)
            ref_msg = getattr(message_obj, "ref_msg", None)
            platform = getattr(event, "platform", None)
            reply_resolver = getattr(
                platform, "_build_reply_component_from_ref", None
            )
            if isinstance(ref_msg, dict) and callable(reply_resolver):
                try:
                    recovered_reply, _ = await reply_resolver(
                        session_id=event.get_session_id(),
                        ref_msg=ref_msg,
                    )
                    if recovered_reply is not None:
                        collect_media([recovered_reply])
                except Exception as exc:
                    logger.warning(f"微信引用媒体后备解析失败：{exc}")

        if not media_items:
            yield event.plain_result("没有找到图片或视频。请附上媒体，或回复一条含媒体的消息后发送此指令。")
            return
        if len(media_items) > 20:
            yield event.plain_result("单次最多收藏 20 个媒体文件，请分批操作。")
            return

        existing_category = await asyncio.to_thread(
            self.store.category_by_name, category
        )
        try:
            target = await asyncio.to_thread(
                self.store.get_or_create_category, category
            )
        except GalleryError as exc:
            yield event.plain_result(f"无法使用分类“{category}”：{exc}")
            return

        saved_images = 0
        saved_videos = 0
        duplicates = 0
        compressed_media = 0
        errors = []
        for media in media_items:
            media_type = "video" if isinstance(media, Video) else "image"
            try:
                local_path = (
                    await self._resolve_video_path(event, media)
                    if media_type == "video"
                    else await media.convert_to_file_path()
                )
                result = await self._ingest_media_with_tasks(
                    local_path, target["id"], media_type, "chat"
                )
                if result["duplicate"]:
                    duplicates += 1
                else:
                    if result.get("compressed"):
                        compressed_media += 1
                    if media_type == "video":
                        saved_videos += 1
                    else:
                        saved_images += 1
            except GalleryError as exc:
                errors.append(str(exc))
            except Exception as exc:
                logger.warning(f"收藏媒体失败: {exc}")
                errors.append("有媒体无法下载或读取")

        message = (
            f"已收藏图片 {saved_images} 张、视频 {saved_videos} 个到「{target['name']}」；"
            f"重复跳过 {duplicates} 个。"
        )
        if not existing_category:
            message = f"分类不存在，已新建「{target['name']}」。\n" + message
        if compressed_media:
            message += f"\n其中 {compressed_media} 个超限文件已自动压缩到配置上限以内。"
        if errors:
            message += f"\n失败 {len(errors)} 个：" + "；".join(dict.fromkeys(errors[:3]))
        yield event.plain_result(message)

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("幻影")
    async def command_make_mirage(
        self,
        event: AstrMessageEvent,
        cover_id: int | None = None,
        inner_id: int | None = None,
    ):
        if not self._may_view_nsfw(event):
            yield event.plain_result("该指令会将成品保存到 NSFW 分类，仅允许具有 NSFW 权限的管理员使用。")
            return

        pending_key = self._mirage_pending_key(event)
        self._cleanup_expired_mirage_covers()
        has_ids = cover_id is not None or inner_id is not None
        if has_ids:
            if cover_id is None or inner_id is None:
                yield event.plain_result("指令格式：/幻影 <表图编号> <里图编号>。")
                return
            try:
                sources = await asyncio.to_thread(
                    self.store.get_mirage_chat_sources,
                    cover_id,
                    inner_id,
                    allow_nsfw=True,
                )
                result = await self._generate_and_store_mirage(
                    sources["cover"]["path"],
                    sources["inner"]["path"],
                    f"幻影坦克_表图{cover_id}_里图{inner_id}.png",
                )
            except GalleryError as exc:
                yield event.plain_result(f"幻影坦克生成失败：{exc}")
                return
            except Exception as exc:
                logger.warning(f"聊天幻影坦克生成失败：{exc}")
                yield event.plain_result("幻影坦克生成失败，请检查插件日志。")
                return
            self._clear_mirage_pending_cover(pending_key)
        else:
            media_items = await self._quoted_mirage_images(event)
            if len(media_items) > 1:
                yield event.plain_result("请每次只引用一张图片；第一张作为表图，第二张作为里图。")
                return
            if not media_items:
                if pending_key in self._mirage_pending_covers:
                    yield event.plain_result("请指定里图。请引用里图图片并再次发送 /幻影。")
                else:
                    yield event.plain_result(
                        "用法：/幻影 <表图编号> <里图编号>；或先引用表图发送 /幻影，再引用里图发送 /幻影。"
                    )
                return

            try:
                image_path = await self._resolve_mirage_chat_image(media_items[0])
            except GalleryError as exc:
                yield event.plain_result(f"无法使用引用图片：{exc}")
                return
            pending = self._mirage_pending_covers.get(pending_key)
            if not pending:
                try:
                    await self._remember_mirage_cover(pending_key, image_path)
                except GalleryError as exc:
                    yield event.plain_result(str(exc))
                    return
                yield event.plain_result("请指定里图。请引用里图图片并再次发送 /幻影。")
                return

            cover_path = Path(pending["path"])
            try:
                result = await self._generate_and_store_mirage(
                    cover_path,
                    image_path,
                    "幻影坦克_引用生成.png",
                )
            except GalleryError as exc:
                self._clear_mirage_pending_cover(pending_key)
                yield event.plain_result(f"幻影坦克生成失败：{exc}")
                return
            except Exception as exc:
                self._clear_mirage_pending_cover(pending_key)
                logger.warning(f"聊天引用图片生成幻影坦克失败：{exc}")
                yield event.plain_result("幻影坦克生成失败，请检查插件日志。")
                return
            self._clear_mirage_pending_cover(pending_key)

        media_label = (
            "成品已存在，使用图库中的重复项"
            if result.get("duplicate")
            else "已生成并保存"
        )
        saved_path = self.store.images_dir / result["filename"]
        yield event.chain_result(
            [
                Plain(
                    f"{media_label}到 NSFW「幻影坦克」分类（媒体编号 {result['id']}）。"
                ),
                Image.fromFileSystem(str(saved_path)),
            ]
        )

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.command("分类")
    async def command_categories(self, event: AstrMessageEvent):
        may_view_nsfw = self._may_view_nsfw(event)
        categories = await asyncio.to_thread(
            self.store.categories, include_nsfw=may_view_nsfw
        )
        lines = [f"{item['name']}：{item['image_count']} 个媒体" for item in categories if may_view_nsfw or not item["is_nsfw"]]
        yield event.plain_result("图集分类：\n" + ("\n".join(lines) or "暂无可见分类。"))

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.command("看", alias={"查看"})
    async def command_view(
        self,
        event: AstrMessageEvent,
        category: str,
        image_id: int | None = None,
    ):
        target = await asyncio.to_thread(self.store.category_by_name, category)
        if not target:
            yield event.plain_result(f"没有“{category}”分类，请用 /图集 分类 查看分类名。")
            return
        if target["is_nsfw"] and not self._may_view_nsfw(event):
            yield event.plain_result("你没有查看该分类的权限。")
            return
        image = await asyncio.to_thread(
            self.store.choose_image,
            target["id"],
            image_id,
            self._may_view_nsfw(event),
        )
        if not image:
            if image_id is not None:
                yield event.plain_result(f"在「{target['name']}」中找不到媒体编号 {image_id}。")
            else:
                yield event.plain_result(f"「{target['name']}」分类还没有媒体。")
            return
        component = (
            Video.fromFileSystem(str(image["path"]))
            if image["media_type"] == "video"
            else Image.fromFileSystem(str(image["path"]))
        )
        media_label = "视频" if image["media_type"] == "video" else "图片"
        yield event.chain_result(
            [
                Plain(f"「{target['name']}」· {media_label}编号 {image['id']}"),
                component,
            ]
        )

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.command("搜图", alias={"找标签"})
    async def command_search_tag(self, event: AstrMessageEvent, tag: str):
        allow_nsfw = self._may_view_nsfw(event)
        try:
            image = await asyncio.to_thread(
                self.store.choose_image_by_tag, tag, allow_nsfw
            )
        except GalleryError as exc:
            yield event.plain_result(str(exc))
            return
        if not image:
            yield event.plain_result("没有找到你有权限查看且带有此标签的媒体。")
            return
        component = (
            Video.fromFileSystem(str(image["path"]))
            if image["media_type"] == "video"
            else Image.fromFileSystem(str(image["path"]))
        )
        media_label = "视频" if image["media_type"] == "video" else "图片"
        yield event.chain_result(
            [
                Plain(
                    f"标签「{tag}」·「{image['category_name']}」· "
                    f"{media_label}编号 {image['id']}"
                ),
                component,
            ]
        )

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.command("语义搜索", alias={"语义搜"})
    async def command_search_semantic(self, event: AstrMessageEvent, query: str):
        query = str(query or "").strip()
        if not query or len(query) > 500:
            yield event.plain_result("请输入 1–500 个字符的画面描述。")
            return
        provider_id = self.embedding_provider_id
        if not provider_id:
            yield event.plain_result("尚未配置语义搜索 Embedding 模型。")
            return
        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            yield event.plain_result("语义搜索 Embedding 模型当前不可用。")
            return
        try:
            vector = await create_embedding(provider, query)
            fingerprint = embedding_fingerprint(provider, provider_id)
            items = await asyncio.to_thread(
                self.store.search_embeddings,
                vector,
                "all",
                provider_id,
                fingerprint,
                30,
                allow_nsfw=self._may_view_nsfw(event),
                media_type="image",
            )
        except GalleryError as exc:
            yield event.plain_result(str(exc))
            return
        except Exception as exc:
            logger.warning(f"聊天图集语义搜索失败：{exc}")
            yield event.plain_result("语义搜索失败，请检查 Embedding 模型和服务日志。")
            return
        if not items:
            yield event.plain_result("没有找到你有权限查看且已建立语义索引的图片。")
            return
        image = random.choice(items)
        yield event.chain_result(
            [
                Plain(f"语义搜索「{query}」·「{image['category_name']}」· 图片编号 {image['id']}"),
                Image.fromFileSystem(str(self.store.images_dir / image["filename"])),
            ]
        )

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    @image_library_group.command("删除", alias={"删"})
    async def command_delete_media(self, event: AstrMessageEvent, image_id: int):
        try:
            moved = await asyncio.to_thread(self.store.delete_images, [image_id])
        except (TypeError, ValueError, GalleryError) as exc:
            yield event.plain_result(f"无法删除媒体：{exc}")
            return
        if not moved:
            yield event.plain_result(f"找不到媒体编号 {image_id}。")
            return
        yield event.plain_result(
            f"媒体编号 {image_id} 已移入回收站，将在每日 0 点自动清空。"
        )

    async def web_categories(self):
        return json_response(await asyncio.to_thread(self.store.categories))

    async def web_create_category(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("分类参数格式无效。", status_code=400)
        is_nsfw = payload.get("is_nsfw", False)
        if not isinstance(is_nsfw, bool):
            return error_response("NSFW 标记必须是布尔值。", status_code=400)
        try:
            category = await asyncio.to_thread(
                self.store.create_category,
                payload.get("name", ""),
                is_nsfw,
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(category)

    async def web_delete_category(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("分类参数格式无效。", status_code=400)
        category_id = str(payload.get("category_id", ""))
        try:
            result = await asyncio.to_thread(self.store.delete_category, category_id)
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(result)

    async def web_mirage_source(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("图片参数格式无效。", status_code=400)
        try:
            result = await asyncio.to_thread(
                self.store.get_mirage_source,
                payload.get("image_id", 0),
            )
        except (GalleryError, TypeError, ValueError) as exc:
            return error_response(str(exc), status_code=400)
        return json_response(result)

    async def web_mirage_settings(self):
        return json_response(
            await asyncio.to_thread(self.store.get_mirage_settings)
        )

    async def web_save_mirage(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("幻影坦克参数格式无效。", status_code=400)
        try:
            cover_id = int(payload.get("cover_id", 0))
            inner_id = int(payload.get("inner_id", 0))
            category_id = str(payload.get("category_id") or "").strip()
            settings = payload.get("settings")
            if cover_id <= 0 or inner_id <= 0 or not category_id:
                raise ValueError("请提供有效的表图、里图和目标分类。")
            if not isinstance(settings, dict):
                raise ValueError("幻影坦克参数格式无效。")
            sources = await asyncio.to_thread(
                self.store.get_mirage_chat_sources,
                cover_id,
                inner_id,
                allow_nsfw=True,
                allow_pending=True,
            )
            category = await asyncio.to_thread(
                self.store.category_by_id,
                category_id,
            )
            if not category:
                raise GalleryError("找不到目标分类。")
            source_is_nsfw = bool(
                sources["cover"]["is_nsfw"] or sources["inner"]["is_nsfw"]
            )
            if source_is_nsfw and not category.get("is_nsfw"):
                raise GalleryError("NSFW 来源的成品只能保存到 NSFW 分类。")

            output_path = self.store.staging_dir / f"{uuid.uuid4().hex}.png"
            try:
                dimensions = await asyncio.to_thread(
                    self.store.create_mirage_png_from_paths,
                    sources["cover"]["path"],
                    sources["inner"]["path"],
                    output_path,
                    settings,
                )
                result = await self._ingest_media_with_tasks(
                    output_path,
                    category_id,
                    "image",
                    "web",
                    display_name=f"幻影坦克_表图{cover_id}_里图{inner_id}.png",
                )
                result["mirage_width"] = dimensions["width"]
                result["mirage_height"] = dimensions["height"]
                return json_response(result)
            finally:
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.warning(f"管理页幻影坦克生成失败：{exc}")
            return error_response("幻影坦克生成失败，请检查插件日志。", status_code=500)
    async def web_save_mirage_settings(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("幻影坦克参数格式无效。", status_code=400)
        try:
            settings = await asyncio.to_thread(
                self.store.save_mirage_settings,
                payload,
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(settings)

    async def web_images(self):
        category_id = str(request.query.get("category_id", ""))
        try:
            page = request.query.get("page", 1, type=int)
            page_size = request.query.get("page_size", 30, type=int)
            tag = str(request.query.get("tag", ""))[:32]
            media_type = str(request.query.get("media_type", "")).strip().lower()
            data = await asyncio.to_thread(
                self.store.list_images,
                category_id,
                page,
                page_size,
                tag,
                defer_video_thumbnails=True,
                media_type=media_type,
            )
        except (GalleryError, TypeError, ValueError) as exc:
            return error_response(str(exc), status_code=400)
        for item in data["items"]:
            if item["media_type"] == "video" and not item.get("thumbnail"):
                self._schedule_video_preview_task(item["id"])
        return json_response(data)

    @staticmethod
    def _web_media_type(filename: str, content_type: str = "", declared: str = "") -> str:
        suffix = Path(str(filename).replace("\\", "/")).suffix.lower()
        video_suffixes = {".mp4", ".mov", ".3gp", ".avi", ".mkv", ".webm"}
        if str(declared).lower() == "video" or str(content_type).lower().startswith("video/") or suffix in video_suffixes:
            return "video"
        return "image"

    async def _ingest_media_with_tasks(
        self,
        source_path: str | Path,
        category_id: str,
        media_type: str,
        source: str,
        *,
        force_compression_task: bool = False,
        display_name: str = "",
        retry_of: str = "",
    ) -> dict:
        source_path = Path(source_path)
        media_type = str(media_type).lower()
        target_bytes = self.store.max_video_bytes if media_type == "video" else self.store.max_image_bytes
        needs_compression_task = force_compression_task
        try:
            needs_compression_task = needs_compression_task or source_path.stat().st_size > target_bytes
        except OSError:
            pass
        task_ids: dict[str, str] = {}
        metadata = {
            "category_id": category_id,
            "media_type": media_type,
            "file_name": str(display_name or source_path.name)[:255],
        }
        if needs_compression_task:
            task_ids["compression"] = self.store.create_processing_task(
                "compression",
                retry_of=retry_of,
                source_path=str(source_path),
                metadata=metadata,
                message="等待媒体压缩与入库",
            )
        if media_type == "video":
            task_ids["video_preview"] = self.store.create_processing_task(
                "video_preview",
                metadata=metadata,
                message="等待视频预览图生成",
            )

        def progress_callback(task_type: str, progress: int, message: str) -> None:
            task_id = task_ids.get(task_type)
            if task_id:
                self.store.update_processing_task(
                    task_id,
                    status="running",
                    progress=min(99, max(0, int(progress))),
                    message=message,
                )

        def cancel_check(task_type: str) -> bool:
            task_id = task_ids.get(task_type)
            return bool(task_id and self.store.processing_task_cancel_requested(task_id))

        try:
            result = await asyncio.to_thread(
                self.store.add_media,
                source_path,
                category_id,
                media_type,
                source,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            compression_task = task_ids.get("compression")
            if compression_task:
                self.store.update_processing_task(
                    compression_task,
                    status="succeeded",
                    progress=100,
                    media_id=result["id"],
                    source_path="",
                    message=(
                        "压缩已完成；目标分类已有重复媒体，已跳过入库"
                        if result.get("duplicate")
                        else (
                            f"压缩完成：{self._format_task_size(result.get('original_size_bytes', 0))} → "
                            f"{self._format_task_size(result.get('size_bytes', 0))}"
                            if result.get("compressed")
                            else "当前配置下无需压缩，媒体已入库"
                        )
                    ),
                )
            preview_task = task_ids.get("video_preview")
            if preview_task:
                if result.get("duplicate"):
                    self.store.update_processing_task(
                        preview_task,
                        status="skipped",
                        progress=100,
                        media_id=result["id"],
                        message="目标分类已有该视频，跳过重复预览生成",
                    )
                elif result.get("thumbnail_cancelled"):
                    self.store.update_processing_task(
                        preview_task,
                        status="cancelled",
                        media_id=result["id"],
                        error=result.get("thumbnail_error") or "视频预览生成已取消。",
                        message="已取消视频预览生成",
                    )
                elif result.get("thumbnail_ready"):
                    self.store.update_processing_task(
                        preview_task,
                        status="succeeded",
                        progress=100,
                        media_id=result["id"],
                        message="视频预览图已生成",
                    )
                else:
                    self.store.update_processing_task(
                        preview_task,
                        status="failed",
                        media_id=result["id"],
                        error=result.get("thumbnail_error") or "视频预览图生成失败。",
                        message="视频已入库，但预览图生成失败；可重试",
                    )

            category = await asyncio.to_thread(self.store.category_by_id, category_id)
            if (
                not result.get("duplicate")
                and not self._web_upload_stopping
                and category
                and not category["is_nsfw"]
                and category["id"] != "pending"
            ):
                self._schedule_ai_evaluation(result["id"], "sfw")
            return result
        except ProcessingTaskCancelled as exc:
            await self._preserve_failed_ingest_source(source_path, task_ids, media_type)
            compression_task = task_ids.get("compression")
            if compression_task:
                self.store.update_processing_task(
                    compression_task,
                    status="cancelled",
                    error=str(exc),
                    message="压缩任务已取消；可稍后重试",
                )
            preview_task = task_ids.get("video_preview")
            if preview_task:
                self.store.update_processing_task(
                    preview_task,
                    status="skipped",
                    error="媒体未完成入库，未生成预览图。",
                    message="媒体未完成入库，跳过预览生成",
                )
            raise
        except Exception as exc:
            await self._preserve_failed_ingest_source(source_path, task_ids, media_type)
            compression_task = task_ids.get("compression")
            if compression_task:
                self.store.update_processing_task(
                    compression_task,
                    status="failed",
                    error=str(exc),
                    message="压缩或入库失败，可从任务中心重试",
                )
            preview_task = task_ids.get("video_preview")
            if preview_task:
                self.store.update_processing_task(
                    preview_task,
                    status="skipped",
                    error="媒体未完成入库，未生成预览图。",
                    message="媒体未完成入库，跳过预览生成",
                )
            raise

    @staticmethod
    def _format_task_size(size_bytes: int) -> str:
        size = max(0, int(size_bytes or 0))
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    async def _preserve_failed_ingest_source(
        self,
        source_path: Path,
        task_ids: dict[str, str],
        media_type: str,
    ) -> None:
        task_id = task_ids.get("compression")
        if not task_id or not source_path.is_file():
            return
        try:
            source_limit = (
                self.store.max_source_video_bytes
                if media_type == "video"
                else self.store.max_source_image_bytes
            )
            if source_path.stat().st_size > source_limit:
                self.store.update_processing_task(
                    task_id,
                    error="源文件超过接收上限，未保留副本，无法重试。",
                    message="原始文件超过接收上限；未保留重试副本",
                    source_path="",
                )
                return
        except OSError:
            return
        suffix = source_path.suffix[:12] or ".upload"
        retry_path = self.store.staging_dir / f"retry-{task_id}{suffix}"
        try:
            await asyncio.to_thread(shutil.copyfile, source_path, retry_path)
            self.store.update_processing_task(task_id, source_path=str(retry_path))
        except Exception as exc:
            self.store.update_processing_task(
                task_id,
                error=f"原始文件未能保留，无法重试：{exc}",
                message="任务失败，重试源文件保留失败",
            )

    def _prune_web_upload_state(self) -> None:
        now = time_module.monotonic()
        for upload_id, session in list(self._web_upload_sessions.items()):
            if now - session["updated_at"] > WEB_UPLOAD_SESSION_TTL_SECONDS:
                self._web_upload_sessions.pop(upload_id, None)
                self._clear_web_upload_session(upload_id, session)
        for job_id, job in list(self._web_upload_jobs.items()):
            if (
                job["status"] != "processing"
                and now - job["updated_at"] > WEB_UPLOAD_JOB_TTL_SECONDS
            ):
                self._web_upload_jobs.pop(job_id, None)

    def _clear_web_upload_session(self, upload_id: str, session: dict) -> None:
        for index in range(int(session.get("total_chunks", 0))):
            for suffix in ("part", "tmp"):
                try:
                    (
                        self.store.staging_dir
                        / f"web-chunk-{upload_id}-{index:05d}.{suffix}"
                    ).unlink(missing_ok=True)
                except OSError:
                    pass

    def _assemble_web_upload(self, upload_id: str, session: dict) -> Path:
        output_path = self.store.staging_dir / f"web-assembled-{upload_id}.upload"
        try:
            with output_path.open("wb") as output:
                for index in range(session["total_chunks"]):
                    chunk_path = (
                        self.store.staging_dir
                        / f"web-chunk-{upload_id}-{index:05d}.part"
                    )
                    with chunk_path.open("rb") as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            if output_path.stat().st_size != session["size_bytes"]:
                raise GalleryError("分块合并后的文件大小不匹配，未入库。")
            return output_path
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    def _queue_web_upload_job(
        self, source_path: Path, category_id: str, media_type: str, filename: str
    ) -> str:
        self._prune_web_upload_state()
        job_id = uuid.uuid4().hex
        now = time_module.monotonic()
        self._web_upload_jobs[job_id] = {
            "status": "processing",
            "filename": filename,
            "category_id": category_id,
            "created_at": now,
            "updated_at": now,
        }
        task = asyncio.create_task(
            self._process_web_upload_job(
                job_id, source_path, category_id, media_type
            ),
            name=f"{PLUGIN_NAME}-web-upload-{job_id}",
        )
        self._web_upload_tasks.add(task)
        task.add_done_callback(self._web_upload_tasks.discard)
        return job_id

    async def _process_web_upload_job(
        self, job_id: str, source_path: Path, category_id: str, media_type: str
    ) -> None:
        try:
            async with self._web_upload_semaphore:
                category = await asyncio.to_thread(
                    self.store.category_by_id, category_id
                )
                if not category:
                    raise GalleryError("找不到目标分类，媒体未入库。")
                result = await self._ingest_media_with_tasks(
                    source_path,
                    category_id,
                    media_type,
                    "web",
                    display_name=self._web_upload_jobs.get(job_id, {}).get("filename", ""),
                )
                result["category_name"] = category["name"]
            job = self._web_upload_jobs.get(job_id)
            if job is not None:
                job.update(status="completed", result=result)
                job["updated_at"] = time_module.monotonic()
        except asyncio.CancelledError:
            raise
        except GalleryError as exc:
            job = self._web_upload_jobs.get(job_id)
            if job is not None:
                job.update(status="failed", error=str(exc))
                job["updated_at"] = time_module.monotonic()
        except Exception as exc:
            logger.exception(f"WebUI 媒体导入任务失败：{exc}")
            job = self._web_upload_jobs.get(job_id)
            if job is not None:
                job.update(status="failed", error="导入失败，请检查媒体格式、大小和 FFmpeg。")
                job["updated_at"] = time_module.monotonic()
        finally:
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def web_upload_image(self, category_id: str):
        category = await asyncio.to_thread(self.store.category_by_id, category_id)
        if not category:
            return error_response("找不到目标分类。", status_code=404)

        max_upload_size = max(
            self.store.max_source_image_bytes,
            self.store.max_source_video_bytes,
        )
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > max_upload_size + 512_000
        ):
            return error_response("上传文件超过原始文件接收上限。", status_code=413)

        files = await request.files()
        upload = files.get("file")
        if not isinstance(upload, PluginUploadFile):
            return error_response("缺少上传文件。", status_code=400)

        filename = str(getattr(upload, "filename", "") or "upload")
        content_type = str(getattr(upload, "content_type", "") or "")
        media_type = self._web_media_type(filename, content_type)
        max_size = (
            self.store.max_source_video_bytes
            if media_type == "video"
            else self.store.max_source_image_bytes
        )
        temp_path = self.store.staging_dir / f"web-{uuid.uuid4().hex}.upload"
        keep_file = False
        try:
            await upload.save(temp_path, max_bytes=max_size)
            job_id = self._queue_web_upload_job(
                temp_path, category_id, media_type, Path(filename).name
            )
            keep_file = True
            return json_response(
                {"job_id": job_id, "status": "processing", "filename": Path(filename).name}
            )
        except ValueError as exc:
            if hasattr(exc, "max_bytes"):
                return error_response("上传文件超过原始文件接收上限。", status_code=413)
            return error_response("导入失败，请检查媒体格式和大小。", status_code=400)
        except Exception as exc:
            logger.exception(f"WebUI 媒体接收失败：{exc}")
            return error_response("导入失败，请检查媒体格式和大小。", status_code=400)
        finally:
            if not keep_file:
                temp_path.unlink(missing_ok=True)

    async def web_upload_start(self, category_id: str):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("上传参数格式无效。", status_code=400)
        category = await asyncio.to_thread(self.store.category_by_id, category_id)
        if not category:
            return error_response("找不到目标分类。", status_code=404)

        filename = str(payload.get("filename") or "upload").replace("\\", "/")
        filename = filename.rsplit("/", 1)[-1][:255] or "upload"
        media_type = self._web_media_type(
            filename, str(payload.get("content_type") or ""), str(payload.get("media_type") or "")
        )
        try:
            size_bytes = int(payload.get("size_bytes", 0))
        except (TypeError, ValueError):
            return error_response("文件大小无效。", status_code=400)
        source_limit = (
            self.store.max_source_video_bytes
            if media_type == "video"
            else self.store.max_source_image_bytes
        )
        target_limit = (
            self.store.max_video_bytes
            if media_type == "video"
            else self.store.max_image_bytes
        )
        if size_bytes <= 0:
            return error_response("文件不能为空。", status_code=400)
        if size_bytes > source_limit:
            limit_mb = source_limit // (1024 * 1024)
            return error_response(
                f"原始文件超过接收上限 {limit_mb} MB。", status_code=413
            )
        if not self.store.compress_oversized_media and size_bytes > target_limit:
            limit_mb = target_limit // (1024 * 1024)
            return error_response(
                f"文件超过入库体积上限 {limit_mb} MB，且已关闭自动压缩。",
                status_code=413,
            )

        self._prune_web_upload_state()
        if len(self._web_upload_sessions) >= 4:
            return error_response("当前已有多个分块上传，请稍后重试。", status_code=429)
        upload_id = uuid.uuid4().hex
        total_chunks = (size_bytes + WEB_UPLOAD_CHUNK_BYTES - 1) // WEB_UPLOAD_CHUNK_BYTES
        now = time_module.monotonic()
        self._web_upload_sessions[upload_id] = {
            "category_id": category_id,
            "filename": filename,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "chunk_size": WEB_UPLOAD_CHUNK_BYTES,
            "total_chunks": total_chunks,
            "received": set(),
            "created_at": now,
            "updated_at": now,
            "lock": asyncio.Lock(),
        }
        return json_response(
            {
                "upload_id": upload_id,
                "chunk_size": WEB_UPLOAD_CHUNK_BYTES,
                "total_chunks": total_chunks,
            }
        )

    async def web_upload_chunk(
        self, category_id: str, upload_id: str, index: str
    ):
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = None
        session = self._web_upload_sessions.get(upload_id)
        if not session or session["category_id"] != category_id:
            return error_response("分块上传会话不存在或已过期。", status_code=404)
        if index is None or index < 0 or index >= session["total_chunks"]:
            return error_response("分块序号无效。", status_code=400)

        async with session["lock"]:
            if index in session["received"]:
                return json_response(
                    {"received": True, "index": index, "duplicate": True}
                )
            files = await request.files()
            upload = files.get("file")
            if not isinstance(upload, PluginUploadFile):
                return error_response("缺少上传分块。", status_code=400)
            expected_size = min(
                session["chunk_size"],
                session["size_bytes"] - index * session["chunk_size"],
            )
            temp_path = self.store.staging_dir / f"web-chunk-{upload_id}-{index:05d}.tmp"
            chunk_path = self.store.staging_dir / f"web-chunk-{upload_id}-{index:05d}.part"
            try:
                await upload.save(temp_path, max_bytes=expected_size)
                if temp_path.stat().st_size != expected_size:
                    return error_response("上传分块长度不匹配。", status_code=400)
                os.replace(temp_path, chunk_path)
                session["received"].add(index)
                session["updated_at"] = time_module.monotonic()
                return json_response({"received": True, "index": index})
            except ValueError as exc:
                if hasattr(exc, "max_bytes"):
                    return error_response("单个上传分块超过限制。", status_code=413)
                return error_response("上传分块失败。", status_code=400)
            except Exception as exc:
                logger.exception(f"WebUI 分块接收失败：{exc}")
                return error_response("上传分块失败。", status_code=500)
            finally:
                temp_path.unlink(missing_ok=True)

    async def web_upload_complete(self, category_id: str):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("上传完成参数格式无效。", status_code=400)
        upload_id = str(payload.get("upload_id", ""))
        session = self._web_upload_sessions.get(upload_id)
        if not session or session["category_id"] != category_id:
            return error_response("分块上传会话不存在或已过期。", status_code=404)

        async with session["lock"]:
            expected = set(range(session["total_chunks"]))
            if session["received"] != expected:
                missing = len(expected - session["received"])
                return error_response(f"仍缺少 {missing} 个上传分块。", status_code=400)
            try:
                source_path = await asyncio.to_thread(
                    self._assemble_web_upload, upload_id, session
                )
            except Exception as exc:
                logger.exception(f"WebUI 分块合并失败：{exc}")
                self._web_upload_sessions.pop(upload_id, None)
                self._clear_web_upload_session(upload_id, session)
                return error_response(
                    str(exc) if isinstance(exc, GalleryError) else "上传文件合并失败。",
                    status_code=400,
                )
            self._web_upload_sessions.pop(upload_id, None)
            self._clear_web_upload_session(upload_id, session)

        job_id = self._queue_web_upload_job(
            source_path,
            category_id,
            session["media_type"],
            session["filename"],
        )
        return json_response(
            {
                "job_id": job_id,
                "status": "processing",
                "filename": session["filename"],
            }
        )

    async def web_upload_cancel(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("取消上传参数格式无效。", status_code=400)
        upload_id = str(payload.get("upload_id", ""))
        session = self._web_upload_sessions.pop(upload_id, None)
        if session:
            async with session["lock"]:
                self._clear_web_upload_session(upload_id, session)
        return json_response({"cancelled": bool(session)})

    async def web_upload_status(self):
        self._prune_web_upload_state()
        job_id = str(request.query.get("job_id", ""))
        job = self._web_upload_jobs.get(job_id)
        if not job:
            return error_response("导入任务不存在或已过期。", status_code=404)
        response = {
            "job_id": job_id,
            "status": job["status"],
            "filename": job["filename"],
        }
        if job["status"] == "completed":
            response["result"] = job["result"]
        elif job["status"] == "failed":
            response["error"] = job["error"]
        return json_response(response)

    async def web_delete_images(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("删除参数格式无效。", status_code=400)
        raw_ids = payload.get("image_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 500:
            return error_response("请选择 1–500 个媒体。", status_code=400)
        try:
            image_ids = [int(value) for value in raw_ids]
            if any(value <= 0 for value in image_ids):
                raise ValueError
        except (TypeError, ValueError):
            return error_response("媒体编号无效。", status_code=400)
        trashed = await asyncio.to_thread(self.store.delete_images, image_ids)
        return json_response({"trashed": trashed, "deleted": trashed})

    async def web_trash(self):
        try:
            page = request.query.get("page", 1, type=int)
            page_size = request.query.get("page_size", 30, type=int)
            data = await asyncio.to_thread(self.store.list_trash, page, page_size)
        except (GalleryError, TypeError, ValueError) as exc:
            return error_response(str(exc), status_code=400)
        return json_response(data)

    @staticmethod
    def _trash_ids(payload: object) -> list[int]:
        if not isinstance(payload, dict):
            raise GalleryError("回收站参数格式无效。")
        raw_ids = payload.get("image_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 500:
            raise GalleryError("请选择 1–500 个回收站媒体。")
        try:
            ids = list(dict.fromkeys(int(value) for value in raw_ids))
        except (TypeError, ValueError) as exc:
            raise GalleryError("媒体编号无效。") from exc
        if any(value <= 0 for value in ids):
            raise GalleryError("媒体编号无效。")
        return ids

    async def web_restore_trash(self):
        payload = await request.json(default={})
        try:
            image_ids = self._trash_ids(payload)
            result = await asyncio.to_thread(self.store.restore_images, image_ids)
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc), status_code=400)
        for image_id in result["restored_ids"]:
            try:
                media = await asyncio.to_thread(
                    self.store.get_media_for_evaluation, image_id, "sfw"
                )
            except GalleryError:
                continue
            if not str(media.get("ai_description") or "").strip() and not str(
                media.get("description_override") or ""
            ).strip():
                self._schedule_ai_evaluation(image_id, "sfw")
        return json_response(result)

    async def web_purge_trash_images(self):
        payload = await request.json(default={})
        try:
            image_ids = self._trash_ids(payload)
            deleted = await asyncio.to_thread(
                self.store.purge_trash_images, image_ids
            )
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"deleted": deleted})

    async def web_empty_trash(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("回收站参数格式无效。", status_code=400)
        deleted = await asyncio.to_thread(self.store.empty_trash)
        return json_response({"deleted": deleted})

    async def web_move_images(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("移动参数格式无效。", status_code=400)
        raw_ids = payload.get("image_ids", [])
        target_category_id = str(payload.get("target_category_id", ""))
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 500:
            return error_response("请选择 1–500 个媒体。", status_code=400)
        try:
            image_ids = [int(value) for value in raw_ids]
            if any(value <= 0 for value in image_ids):
                raise ValueError
        except (TypeError, ValueError):
            return error_response("媒体编号无效。", status_code=400)
        try:
            result = await asyncio.to_thread(
                self.store.move_images, image_ids, target_category_id
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        target = await asyncio.to_thread(self.store.category_by_id, target_category_id)
        if target and not target["is_nsfw"] and target["id"] != "pending":
            try:
                needs_evaluation = await asyncio.to_thread(
                    self.store.sfw_media_needing_evaluation,
                    image_ids,
                    target_category_id,
                )
                for image_id in needs_evaluation:
                    self._schedule_ai_evaluation(image_id, "sfw")
            except GalleryError:
                pass
        return json_response(result)

    @staticmethod
    def _provider_option(provider, fallback_id: str = "") -> dict | None:
        try:
            meta = provider.meta()
            provider_id = str(getattr(meta, "id", "") or fallback_id).strip()
            if not provider_id:
                return None
            name = str(getattr(meta, "name", "") or provider_id)
            return {"id": provider_id, "name": name}
        except Exception:
            return None

    async def web_ai_providers(self):
        chat = []
        try:
            for provider in self.context.get_all_providers() or []:
                option = self._provider_option(provider)
                if option:
                    chat.append(option)
        except Exception as exc:
            logger.warning(f"读取聊天模型列表失败：{exc}")
        embedding = []
        get_embeddings = getattr(self.context, "get_all_embedding_providers", None)
        if callable(get_embeddings):
            try:
                for provider in get_embeddings() or []:
                    config = getattr(provider, "provider_config", {})
                    if not isinstance(config, dict):
                        if hasattr(config, "model_dump"):
                            config = config.model_dump()
                        elif hasattr(config, "dict"):
                            config = config.dict()
                        else:
                            config = {}
                    provider_id = str(config.get("id", "")).strip() if isinstance(config, dict) else ""
                    if provider_id:
                        embedding.append({"id": provider_id, "name": provider_id})
            except Exception as exc:
                logger.warning(f"读取 Embedding 模型列表失败：{exc}")
        return json_response(
            {
                "chat": chat,
                "embedding": embedding,
                "sfw_provider_id": self.sfw_evaluation_provider_id,
                "nsfw_provider_id": self.nsfw_evaluation_provider_id,
                "embedding_provider_id": self.embedding_provider_id,
            }
        )

    async def web_processing_tasks(self):
        tasks = await asyncio.to_thread(self.store.list_processing_tasks, 200)
        sfw_version = evaluation_prompt_version(self.media_ai.sfw_evaluation_prompt)
        nsfw_version = evaluation_prompt_version(self.media_ai.nsfw_evaluation_prompt)
        requested_nsfw_provider = str(
            request.query.get("nsfw_provider_id") or self.nsfw_evaluation_provider_id
        ).strip()
        sfw_stale = 0
        nsfw_stale = 0
        if self.sfw_evaluation_provider_id:
            sfw_stale = len(await asyncio.to_thread(
                self.store.stale_evaluation_candidates,
                "sfw",
                self.sfw_evaluation_provider_id,
                sfw_version,
            ))
        if requested_nsfw_provider:
            nsfw_stale = len(await asyncio.to_thread(
                self.store.stale_evaluation_candidates,
                "nsfw",
                requested_nsfw_provider,
                nsfw_version,
            ))
        return json_response(
            {
                "tasks": tasks,
                "stale": {
                    "sfw": sfw_stale,
                    "nsfw": nsfw_stale,
                    "sfw_model_id": self.sfw_evaluation_provider_id,
                    "nsfw_model_id": requested_nsfw_provider,
                    "sfw_prompt_version": sfw_version,
                    "nsfw_prompt_version": nsfw_version,
                    "embedding_model_id": self.embedding_provider_id,
                },
            }
        )

    def _schedule_video_preview_task(
        self,
        image_id: int,
        *,
        force: bool = False,
        retry_of: str = "",
    ) -> str:
        task_key = ("video_preview", int(image_id))
        existing_id = self._processing_task_keys.get(task_key)
        existing = self._processing_tasks.get(existing_id or "")
        if existing_id and existing and not existing.done():
            return existing_id
        if not force:
            latest = self.store.latest_processing_task(image_id, "video_preview")
            if latest and latest.get("status") in {"failed", "cancelled"}:
                return ""
        task_id = self.store.create_processing_task(
            "video_preview",
            media_id=int(image_id),
            retry_of=retry_of,
            message="等待视频预览图重建",
        )
        task = asyncio.create_task(
            self._run_video_preview_task(task_id, int(image_id)),
            name=f"{PLUGIN_NAME}-video-preview-{image_id}-{task_id[:8]}",
        )
        self._processing_tasks[task_id] = task
        self._processing_task_keys[task_key] = task_id
        task.add_done_callback(
            lambda completed, processing_id=task_id, key=task_key:
                self._finish_processing_task(completed, processing_id, key)
        )
        return task_id

    async def _run_video_preview_task(self, task_id: str, image_id: int) -> None:
        def progress_callback(_kind: str, progress: int, message: str) -> None:
            self.store.update_processing_task(
                task_id,
                status="running",
                progress=progress,
                message=message,
            )

        def cancel_check(_kind: str) -> bool:
            return self.store.processing_task_cancel_requested(task_id)

        try:
            async with self._video_preview_semaphore:
                if cancel_check("video_preview"):
                    raise ProcessingTaskCancelled("视频预览任务已取消。")
                self.store.update_processing_task(
                    task_id,
                    status="running",
                    progress=3,
                    message="准备重新生成视频预览图",
                )
                await asyncio.to_thread(
                    self.store.regenerate_video_preview,
                    image_id,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            self.store.update_processing_task(
                task_id,
                status="succeeded",
                progress=100,
                message="视频预览图已重建",
            )
        except ProcessingTaskCancelled as exc:
            self.store.update_processing_task(
                task_id,
                status="cancelled",
                error=str(exc),
                message="已取消视频预览重建",
            )
        except asyncio.CancelledError:
            self.store.update_processing_task(
                task_id,
                status="cancelled",
                error="任务已取消。",
                message="已取消视频预览重建",
            )
            raise
        except Exception as exc:
            self.store.update_processing_task(
                task_id,
                status="failed",
                error=str(exc),
                message="视频预览重建失败，可从任务中心重试",
            )

    async def _retry_ingest_task(
        self, source_path: Path, metadata: dict, original_task_id: str
    ) -> None:
        try:
            await self._ingest_media_with_tasks(
                source_path,
                str(metadata.get("category_id") or ""),
                str(metadata.get("media_type") or "image"),
                "web-retry",
                force_compression_task=True,
                display_name=str(metadata.get("file_name") or source_path.name),
                retry_of=original_task_id,
            )
            source_path.unlink(missing_ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"任务中心重试媒体入库失败：{exc}")

    async def web_processing_task_action(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("任务操作参数格式无效。", status_code=400)
        task_id = str(payload.get("task_id") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        if not task_id or action not in {"retry", "cancel"}:
            return error_response("请选择有效的任务和操作。", status_code=400)
        row = await asyncio.to_thread(self.store.get_processing_task, task_id)
        if not row:
            return error_response("找不到该任务。", status_code=404)
        if action == "cancel":
            cancelled = await asyncio.to_thread(
                self.store.request_processing_task_cancel, task_id
            )
            if not cancelled:
                return error_response("该任务已结束，无法取消。", status_code=409)
            runtime_task = self._processing_tasks.get(task_id)
            if runtime_task and row["task_type"] in {"ai_evaluation", "semantic_index"}:
                if row["status"] == "queued":
                    self.store.update_processing_task(
                        task_id,
                        status="cancelled",
                        error="任务已取消。",
                        message="已取消",
                    )
                runtime_task.cancel()
            return json_response({"cancelled": True, "task_id": task_id})

        if row["status"] not in {"failed", "cancelled"}:
            return error_response("只有失败或已取消的任务可以重试。", status_code=409)
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        task_type = row["task_type"]
        if task_type == "compression":
            source_path = Path(row.get("source_path") or "")
            if not source_path.is_file():
                return error_response("原始文件已不存在，无法重试压缩。", status_code=409)
            if not metadata.get("category_id"):
                return error_response("原任务缺少目标分类信息，无法重试。", status_code=409)
            retry_task = asyncio.create_task(
                self._retry_ingest_task(source_path, metadata, task_id),
                name=f"{PLUGIN_NAME}-retry-ingest-{task_id[:8]}",
            )
            self._web_upload_tasks.add(retry_task)
            retry_task.add_done_callback(self._web_upload_tasks.discard)
            return json_response({"retried": True, "task_type": task_type})

        media_id = int(row.get("media_id") or 0)
        if media_id <= 0:
            return error_response("原任务没有关联媒体，无法重试。", status_code=409)
        if task_type == "video_preview":
            new_task_id = self._schedule_video_preview_task(
                media_id,
                force=True,
                retry_of=task_id,
            )
        elif task_type == "ai_evaluation":
            scope = str(row.get("scope") or "")
            provider_id = str(row.get("model_id") or "")
            if not provider_id or not self.context.get_provider_by_id(provider_id):
                return error_response("原评估模型当前不可用，请先在插件配置中选择有效模型。", status_code=400)
            new_task_id = self._schedule_ai_evaluation(
                media_id,
                scope,
                provider_id,
                force=bool(metadata.get("force")),
                retry_of=task_id,
            )
        elif task_type == "semantic_index":
            provider_id = str(row.get("model_id") or self.embedding_provider_id)
            if not provider_id or not self.context.get_provider_by_id(provider_id):
                return error_response("原 Embedding 模型当前不可用，请先在插件配置中选择有效模型。", status_code=400)
            new_task_id = self._schedule_embedding_task(
                media_id,
                str(row.get("scope") or ""),
                provider_id,
                retry_of=task_id,
            )
        else:
            return error_response("该类型任务暂不支持重试。", status_code=400)
        if not new_task_id:
            return error_response("已有相同媒体任务正在运行。", status_code=409)
        return json_response({"retried": True, "task_id": new_task_id, "task_type": task_type})

    async def web_reassess_stale_media(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("重评参数格式无效。", status_code=400)
        scope = str(payload.get("scope") or "").strip().lower()
        if scope not in {"sfw", "nsfw"}:
            return error_response("请选择 SFW 或 NSFW 范围。", status_code=400)
        if scope == "sfw":
            provider_id = self.sfw_evaluation_provider_id
            prompt = self.media_ai.sfw_evaluation_prompt
        else:
            provider_id = str(payload.get("provider_id") or self.nsfw_evaluation_provider_id).strip()
            prompt = self.media_ai.nsfw_evaluation_prompt
        if not provider_id:
            return error_response("请先选择对应范围的视觉评估模型。", status_code=400)
        if not self.context.get_provider_by_id(provider_id):
            return error_response("所选视觉评估模型当前不可用。", status_code=400)
        prompt_version = evaluation_prompt_version(prompt)
        try:
            candidates = await asyncio.to_thread(
                self.store.stale_evaluation_candidates,
                scope,
                provider_id,
                prompt_version,
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        batch_id = uuid.uuid4().hex
        scheduled = 0
        for image_id in candidates:
            task_id = self._schedule_ai_evaluation(
                image_id,
                scope,
                provider_id,
                force=True,
                batch_id=batch_id,
            )
            if task_id:
                scheduled += 1
        return json_response(
            {
                "scope": scope,
                "stale": len(candidates),
                "scheduled": scheduled,
                "skipped_active": len(candidates) - scheduled,
                "batch_id": batch_id,
                "model_id": provider_id,
                "prompt_version": prompt_version,
            }
        )

    async def web_tag_taxonomy(self):
        data = await asyncio.to_thread(self.store.tag_taxonomy)
        return json_response(data)

    async def web_save_tag_alias(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("标签别名参数格式无效。", status_code=400)
        try:
            result = await asyncio.to_thread(
                self.store.save_tag_alias,
                payload.get("alias", ""),
                payload.get("canonical_tag", ""),
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(result)

    async def web_delete_tag_alias(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("标签别名参数格式无效。", status_code=400)
        try:
            deleted = await asyncio.to_thread(
                self.store.delete_tag_alias, payload.get("alias", "")
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"deleted": deleted})

    async def web_save_tag_parent(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("标签层级参数格式无效。", status_code=400)
        try:
            result = await asyncio.to_thread(
                self.store.save_tag_parent,
                payload.get("child_tag", ""),
                payload.get("parent_tag", ""),
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(result)

    async def web_delete_tag_parent(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("标签层级参数格式无效。", status_code=400)
        try:
            deleted = await asyncio.to_thread(
                self.store.delete_tag_parent, payload.get("child_tag", "")
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"deleted": deleted})

    async def web_preview_tag_normalization(self):
        try:
            result = await asyncio.to_thread(self.store.preview_tag_normalization)
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(result)

    async def web_apply_tag_normalization(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            return error_response("请先确认预览的标签规范化操作。", status_code=400)
        try:
            result = await asyncio.to_thread(
                self.store.normalize_tag_aliases,
                payload.get("plan_token", ""),
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=409)
        return json_response(result)

    async def web_update_tags(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("标签参数格式无效。", status_code=400)
        raw_ids = payload.get("image_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 500:
            return error_response("请选择 1–500 个媒体。", status_code=400)
        try:
            image_ids = [int(value) for value in raw_ids]
            if any(value <= 0 for value in image_ids):
                raise ValueError
            updated = await asyncio.to_thread(
                self.store.update_manual_tags,
                image_ids,
                payload.get("tags", []),
                str(payload.get("mode", "replace")),
            )
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc) or "媒体编号无效。", status_code=400)
        embedding_scheduled = 0
        if self.embedding_provider_id:
            for image_id in sorted(set(image_ids)):
                try:
                    scope = await asyncio.to_thread(
                        self.store.embedding_scope_for_media, image_id
                    )
                    if not scope:
                        continue
                    await asyncio.to_thread(
                        self.store.embedding_text_for_media, image_id, scope
                    )
                except GalleryError:
                    continue
                if self._schedule_embedding_task(
                    image_id,
                    scope,
                    self.embedding_provider_id,
                ):
                    embedding_scheduled += 1
        return json_response(
            {"updated": updated, "embedding_scheduled": embedding_scheduled}
        )

    async def web_update_media_details(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("媒体详情参数格式无效。", status_code=400)
        try:
            image_id = int(payload.get("image_id", 0))
            description = payload.get("description", "")
            if image_id <= 0:
                raise ValueError("媒体编号无效。")
            if not isinstance(description, str):
                raise ValueError("描述必须是文本。")
            clear_ai = payload.get("clear_ai", False)
            if not isinstance(clear_ai, bool):
                raise ValueError("清空 AI 数据选项必须是布尔值。")
            if len(description) > 3000:
                raise GalleryError("描述不能超过 3000 个字符。")
            result = await asyncio.to_thread(
                self.store.save_media_details,
                image_id,
                description,
                payload.get("manual_tags", ""),
                payload.get("ai_tags"),
                clear_ai,
            )
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc), status_code=400)

        embedding_scheduled = False
        scope = result["scope"]
        searchable_text = "\n".join(
            part
            for part in (
                result["description"],
                " ".join(result["ai_tags"]),
                " ".join(result["manual_tags"]),
            )
            if part
        )
        if scope and searchable_text and self.embedding_provider_id:
            embedding_scheduled = bool(
                self._schedule_embedding_task(
                    image_id,
                    scope,
                    self.embedding_provider_id,
                )
            )
        return json_response(
            {
                "updated": True,
                "embedding_scheduled": embedding_scheduled,
                "ai_cleared": result["ai_cleared"],
                "can_evaluate": result["can_evaluate"],
            }
        )

    async def web_ai_evaluate(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("评估参数格式无效。", status_code=400)
        raw_ids = payload.get("image_ids", [])
        scope = str(payload.get("scope", "nsfw")).strip().lower()
        provider_id = str(payload.get("provider_id", "")).strip()
        if scope not in {"sfw", "nsfw"}:
            return error_response("评估范围无效。", status_code=400)
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 30:
            return error_response("请选择 1–30 个媒体进行评估。", status_code=400)
        if scope == "sfw":
            provider_id = self.sfw_evaluation_provider_id
        else:
            provider_id = provider_id or self.nsfw_evaluation_provider_id
        if not provider_id:
            return error_response("请先选择对应范围的视觉评估模型。", status_code=400)
        try:
            image_ids = list(dict.fromkeys(int(value) for value in raw_ids))
            if any(value <= 0 for value in image_ids):
                raise ValueError
            provider = self.context.get_provider_by_id(provider_id)
            if not provider:
                return error_response("所选视觉评估模型当前不可用，请检查插件配置。", status_code=400)
            candidates, skipped_existing = await asyncio.to_thread(
                self.store.evaluation_candidates, image_ids, scope
            )
        except (TypeError, ValueError, GalleryError) as exc:
            return error_response(str(exc) or "媒体编号无效。", status_code=400)
        scheduled = 0
        for image_id in candidates:
            if self._schedule_ai_evaluation(image_id, scope, provider_id):
                scheduled += 1
        return json_response(
            {
                "scheduled": scheduled,
                "skipped_existing": skipped_existing + len(candidates) - scheduled,
                "scope": scope,
            }
        )

    async def web_duplicates_scan(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("重复项扫描参数格式无效。", status_code=400)
        try:
            threshold = int(payload.get("threshold", 8))
        except (TypeError, ValueError):
            return error_response("相似度阈值必须是 0–16 的整数。", status_code=400)
        if threshold < 0 or threshold > 16:
            return error_response("相似度阈值必须是 0–16 的整数。", status_code=400)
        if self._duplicate_job_task and not self._duplicate_job_task.done():
            return error_response("已有重复项检查正在运行。", status_code=409)
        job = {
            "job_id": uuid.uuid4().hex,
            "status": "running",
            "phase": "starting",
            "processed": 0,
            "total": 0,
            "hash_errors": 0,
            "threshold": threshold,
            "exact_groups": 0,
            "similar_pairs": 0,
            "truncated": False,
        }
        self._duplicate_job = job
        self._duplicate_scan_results = None
        self._duplicate_job_task = asyncio.create_task(
            self._run_duplicate_scan(job, threshold),
            name=f"{PLUGIN_NAME}-duplicate-scan",
        )
        return json_response(job)

    async def _run_duplicate_scan(self, job: dict, threshold: int) -> None:
        def report_progress(phase, processed, total, hash_errors):
            job.update(
                phase=str(phase),
                processed=int(processed),
                total=int(total),
                hash_errors=int(hash_errors),
            )
        try:
            results = await asyncio.to_thread(
                self.store.scan_duplicates, threshold, report_progress
            )
            self._duplicate_scan_results = results
            job.update(
                status="completed",
                phase="completed",
                processed=results["total_images"],
                total=results["total_images"],
                hash_errors=results["hash_errors"],
                exact_groups=len(results["exact_groups"]),
                similar_pairs=len(results["similar_pairs"]),
                truncated=results["truncated"],
            )
        except asyncio.CancelledError:
            job["status"] = "cancelled"
            raise
        except Exception as exc:
            job.update(status="failed", error=str(exc))
            logger.exception(f"跨分类重复项扫描失败：{exc}")

    async def web_duplicates_status(self):
        if not self._duplicate_job:
            return json_response({"status": "idle", "active": False})
        job = dict(self._duplicate_job)
        job["active"] = job["status"] == "running"
        return json_response(job)

    async def web_duplicates_results(self):
        results = self._duplicate_scan_results
        if not results or not self._duplicate_job or self._duplicate_job.get("status") != "completed":
            return error_response("请先完成重复项检查。", status_code=409)
        kind = str(request.query.get("kind", "exact")).strip().lower()
        if kind not in {"exact", "similar"}:
            return error_response("结果类型必须是 exact 或 similar。", status_code=400)
        try:
            page = max(1, request.query.get("page", 1, type=int))
            page_size = max(1, min(20, request.query.get("page_size", 10, type=int)))
        except (TypeError, ValueError):
            return error_response("分页参数无效。", status_code=400)
        entries = results["exact_groups"] if kind == "exact" else results["similar_pairs"]
        total = len(entries)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        start = (page - 1) * page_size
        selected_entries = entries[start : start + page_size]
        ids = []
        if kind == "exact":
            for entry in selected_entries:
                ids.extend(entry["ids"])
        else:
            for entry in selected_entries:
                ids.extend((entry["first_id"], entry["second_id"]))
        cards = await asyncio.to_thread(self.store.duplicate_media_cards, ids)
        items = []
        if kind == "exact":
            for entry in selected_entries:
                items.append({
                    "sha256": entry["sha256"],
                    "media": [cards[media_id] for media_id in entry["ids"] if media_id in cards],
                })
        else:
            for entry in selected_entries:
                first = cards.get(entry["first_id"])
                second = cards.get(entry["second_id"])
                if first and second:
                    items.append({"distance": entry["distance"], "media": [first, second]})
        return json_response({
            "kind": kind,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
            "threshold": results["threshold"],
            "hash_errors": results["hash_errors"],
            "truncated": results["truncated"],
            "total_images": results["total_images"],
        })

    async def web_ai_reindex(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("索引重建参数格式无效。", status_code=400)
        scope = str(payload.get("scope", "")).strip().lower()
        if scope not in {"sfw", "nsfw"}:
            return error_response("请选择 SFW 或 NSFW 重建范围。", status_code=400)
        if self._embedding_job_task and not self._embedding_job_task.done():
            return error_response("已有语义索引重建任务正在运行。", status_code=409)
        provider_id = self.embedding_provider_id
        if not provider_id:
            return error_response("尚未配置 Embedding 模型。", status_code=400)
        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            return error_response("Embedding 模型当前不可用，请检查插件配置。", status_code=400)
        try:
            candidates = await asyncio.to_thread(
                self.store.embedding_rebuild_candidates, scope
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)

        if payload.get("confirm") is not True:
            return json_response(
                {
                    "preview": True,
                    "scope": scope,
                    "total": len(candidates),
                    "provider_id": provider_id,
                }
            )

        try:
            expected_total = int(payload.get("expected_total", -1))
        except (TypeError, ValueError):
            expected_total = -1
        if expected_total != len(candidates):
            return error_response(
                "可重建媒体数量已变化，请重新查看数量并确认。", status_code=409
            )

        if self._embedding_job_task and not self._embedding_job_task.done():
            return error_response("已有语义索引重建任务正在运行。", status_code=409)

        if not candidates:
            job = {
                "job_id": uuid.uuid4().hex,
                "scope": scope,
                "status": "completed",
                "total": 0,
                "processed": 0,
                "indexed": 0,
                "failed": 0,
                "cancelled": 0,
            }
            self._embedding_job = job
            return json_response(job)

        batch_id = uuid.uuid4().hex
        child_tasks = []
        for candidate in candidates:
            task_id = self._schedule_embedding_task(
                candidate["image_id"],
                scope,
                provider_id,
                batch_id=batch_id,
            )
            runtime_task = self._processing_tasks.get(task_id or "")
            if runtime_task:
                child_tasks.append(runtime_task)
        job = {
            "job_id": batch_id,
            "scope": scope,
            "status": "running",
            "total": len(child_tasks),
            "processed": 0,
            "indexed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        self._embedding_job = job
        self._embedding_job_task = asyncio.create_task(
            self._run_embedding_batch(job, child_tasks),
            name=f"{PLUGIN_NAME}-embedding-reindex-{scope}",
        )
        return json_response(job)

    async def web_ai_reindex_status(self):
        if not self._embedding_job:
            return json_response({"status": "idle", "active": False})
        job = dict(self._embedding_job)
        if job.get("status") == "running":
            summary = await asyncio.to_thread(
                self.store.processing_task_batch_summary,
                job["job_id"],
            )
            job.update(summary)
            if summary["active"] == 0:
                job["status"] = "completed"
                self._embedding_job.update(job)
        job["active"] = job["status"] == "running"
        return json_response(job)

    async def web_ai_search(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("检索参数格式无效。", status_code=400)
        query = str(payload.get("query", "")).strip()
        if not query or len(query) > 500:
            return error_response("请输入 1–500 个字符的检索描述。", status_code=400)
        provider_id = self.embedding_provider_id
        if not provider_id:
            return error_response("尚未在插件配置中选择 Embedding 模型。", status_code=400)
        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            return error_response("Embedding 模型当前不可用，请检查插件配置。", status_code=400)
        try:
            vector = await create_embedding(provider, query)
            fingerprint = embedding_fingerprint(provider, provider_id)
            items = await asyncio.to_thread(
                self.store.search_embeddings,
                vector,
                "all",
                provider_id,
                fingerprint,
                30,
            )
        except GalleryError as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.warning(f"图集语义检索失败：{exc}")
            return error_response("语义检索失败，请检查 Embedding 模型和服务日志。", status_code=400)
        return json_response({"items": items, "scope": "all", "query": query})

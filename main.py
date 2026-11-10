from __future__ import annotations

import asyncio
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
)
from .store import GalleryError, GalleryStore


PLUGIN_NAME = "astrbot_plugin_image_library"
WEB_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
WEB_UPLOAD_SESSION_TTL_SECONDS = 3600
WEB_UPLOAD_JOB_TTL_SECONDS = 3600


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
        self._trash_cleanup_task: asyncio.Task | None = None
        self._embedding_job: dict | None = None
        self._embedding_job_task: asyncio.Task | None = None
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
            (f"/{PLUGIN_NAME}/images/delete", self.web_delete_images, ["POST"], "Move selected media to trash"),
            (f"/{PLUGIN_NAME}/trash", self.web_trash, ["GET"], "List trashed media"),
            (f"/{PLUGIN_NAME}/trash/restore", self.web_restore_trash, ["POST"], "Restore trashed media"),
            (f"/{PLUGIN_NAME}/trash/delete", self.web_purge_trash_images, ["POST"], "Permanently delete trashed media"),
            (f"/{PLUGIN_NAME}/trash/empty", self.web_empty_trash, ["POST"], "Empty media trash"),
            (f"/{PLUGIN_NAME}/images/move", self.web_move_images, ["POST"], "Move selected media to another category"),
            (f"/{PLUGIN_NAME}/images/tags", self.web_update_tags, ["POST"], "Maintain media tags"),
            (f"/{PLUGIN_NAME}/images/details", self.web_update_media_details, ["POST"], "Edit media description and tags"),
            (f"/{PLUGIN_NAME}/ai/providers", self.web_ai_providers, ["GET"], "List available AI providers"),
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
        self, image_id: int, scope: str, provider_id: str = ""
    ) -> None:
        key = (scope, int(image_id))
        if key in self._ai_queued_ids:
            return
        self._ai_queued_ids.add(key)
        task = asyncio.create_task(
            self._run_ai_evaluation(image_id, scope, provider_id),
            name=f"{PLUGIN_NAME}-ai-{scope}-{image_id}",
        )
        self._ai_tasks.add(task)
        task.add_done_callback(lambda completed, task_key=key: self._finish_ai_task(completed, task_key))

    def _finish_ai_task(self, task: asyncio.Task, key: tuple[str, int]) -> None:
        self._ai_tasks.discard(task)
        self._ai_queued_ids.discard(key)

    async def _run_ai_evaluation(
        self, image_id: int, scope: str, provider_id: str = ""
    ) -> None:
        chosen_provider_id = provider_id or (
            self.nsfw_evaluation_provider_id
            if scope == "nsfw"
            else self.sfw_evaluation_provider_id
        )
        try:
            async with self._evaluation_semaphore:
                await self.media_ai.evaluate(
                    image_id,
                    scope,
                    chosen_provider_id,
                    self.embedding_provider_id,
                )
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(
                    self.store.set_ai_status,
                    image_id,
                    scope,
                    "failed",
                    "评估任务被插件重载中断，请重新提交。",
                    chosen_provider_id,
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
                    chosen_provider_id,
                )
            except Exception:
                pass

    async def initialize(self):
        self._trash_cleanup_task = asyncio.create_task(
            self._trash_cleanup_loop(), name=f"{PLUGIN_NAME}-trash-cleanup"
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

    async def terminate(self):
        self._web_upload_stopping = True
        for upload_id, session in list(self._web_upload_sessions.items()):
            self._clear_web_upload_session(upload_id, session)
        self._web_upload_sessions.clear()
        tasks = tuple(self._ai_tasks)
        if self._trash_cleanup_task:
            tasks = (*tasks, self._trash_cleanup_task)
        if self._embedding_job_task:
            tasks = (*tasks, self._embedding_job_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.WEIXIN_OC
    )
    @image_library_group.command("帮助")
    async def command_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "图集指令：\n"
            "/图集 收藏 [分类]（省略分类时放入待处理；附上图片/视频或回复含媒体的消息；仅 AstrBot 管理员）\n"
            "分类不存在时会自动创建。\n"
            "/图集 看 <分类> [媒体编号]（不填编号时随机查看）\n"
            "/图集 搜索 <标签关键词>（模糊匹配标签并随机返回图片或视频）\n"
            "/图集 语义搜索 <画面描述>（按语义匹配并随机返回一张图片）\n"
            "/图集 删除 <媒体编号>（移入回收站，仅管理员）\n"
            "/图集 分类\n"
            "支持 JPG、PNG、GIF、WebP、BMP、MP4、MOV、3GP、AVI、MKV、WebM。\n"
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
    @image_library_group.command("收藏", alias={"存"})
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
                result = await asyncio.to_thread(
                    self.store.add_media, local_path, target["id"], media_type, "chat"
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
                    if not target["is_nsfw"] and target["id"] != "pending":
                        self._schedule_ai_evaluation(result["id"], "sfw")
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
    @image_library_group.command("分类")
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
    @image_library_group.command("看", alias={"查看"})
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
    @image_library_group.command("搜索", alias={"找标签"})
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
    @image_library_group.command("语义搜索", alias={"语义搜"})
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

    async def web_images(self):
        category_id = str(request.query.get("category_id", ""))
        try:
            page = request.query.get("page", 1, type=int)
            page_size = request.query.get("page_size", 30, type=int)
            tag = str(request.query.get("tag", ""))[:32]
            data = await asyncio.to_thread(
                self.store.list_images, category_id, page, page_size, tag
            )
        except (GalleryError, TypeError, ValueError) as exc:
            return error_response(str(exc), status_code=400)
        return json_response(data)

    @staticmethod
    def _web_media_type(filename: str, content_type: str = "", declared: str = "") -> str:
        suffix = Path(str(filename).replace("\\", "/")).suffix.lower()
        video_suffixes = {".mp4", ".mov", ".3gp", ".avi", ".mkv", ".webm"}
        if str(declared).lower() == "video" or str(content_type).lower().startswith("video/") or suffix in video_suffixes:
            return "video"
        return "image"

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
                result = await asyncio.to_thread(
                    self.store.add_media,
                    source_path,
                    category_id,
                    media_type,
                    "web",
                )
                result["category_name"] = category["name"]
                if (
                    not result.get("duplicate")
                    and not self._web_upload_stopping
                    and not category["is_nsfw"]
                    and category["id"] != "pending"
                ):
                    self._schedule_ai_evaluation(result["id"], "sfw")
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
        return json_response({"updated": updated})

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

        indexed = False
        scope = result["scope"]
        searchable_text = "\n".join(
            part
            for part in (result["description"], " ".join(result["ai_tags"]))
            if part
        )
        if scope and searchable_text and self.embedding_provider_id:
            try:
                provider = self.context.get_provider_by_id(self.embedding_provider_id)
                if not provider:
                    raise GalleryError("Embedding 提供商当前不可用。")
                vector = await create_embedding(provider, searchable_text)
                fingerprint = embedding_fingerprint(provider, self.embedding_provider_id)
                await asyncio.to_thread(
                    self.store.save_embedding,
                    image_id,
                    scope,
                    self.embedding_provider_id,
                    fingerprint,
                    vector,
                )
                indexed = True
            except Exception as exc:
                logger.warning(f"保存媒体详情后重建语义向量失败（媒体 {image_id}）：{exc}")
        return json_response(
            {
                "updated": True,
                "embedding_indexed": indexed,
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
        for image_id in candidates:
            self._schedule_ai_evaluation(image_id, scope, provider_id)
        return json_response(
            {
                "scheduled": len(candidates),
                "skipped_existing": skipped_existing,
                "scope": scope,
            }
        )

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
            }
            self._embedding_job = job
            return json_response(job)

        job = {
            "job_id": uuid.uuid4().hex,
            "scope": scope,
            "status": "running",
            "total": len(candidates),
            "processed": 0,
            "indexed": 0,
            "failed": 0,
        }
        self._embedding_job = job
        self._embedding_job_task = asyncio.create_task(
            self._run_embedding_reindex(job, candidates, provider, provider_id),
            name=f"{PLUGIN_NAME}-embedding-reindex-{scope}",
        )
        return json_response(job)

    async def _run_embedding_reindex(
        self, job: dict, candidates: list[dict], provider, provider_id: str
    ) -> None:
        scope = job["scope"]
        try:
            fingerprint = embedding_fingerprint(provider, provider_id)
            for candidate in candidates:
                image_id = candidate["image_id"]
                try:
                    vector = await create_embedding(
                        provider, candidate["searchable_text"]
                    )
                    await asyncio.to_thread(
                        self.store.save_embedding,
                        image_id,
                        scope,
                        provider_id,
                        fingerprint,
                        vector,
                    )
                    job["indexed"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    job["failed"] += 1
                    logger.warning(
                        f"批量重建语义索引失败（范围 {scope}，媒体 {image_id}）：{exc}"
                    )
                finally:
                    job["processed"] += 1
            job["status"] = "completed"
        except asyncio.CancelledError:
            job["status"] = "cancelled"
            raise
        except Exception as exc:
            job["status"] = "failed"
            logger.exception(f"批量重建语义索引任务失败：{exc}")

    async def web_ai_reindex_status(self):
        if not self._embedding_job:
            return json_response({"status": "idle", "active": False})
        job = dict(self._embedding_job)
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

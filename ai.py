from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import uuid
import warnings
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .store import (
    GalleryError,
    GalleryStore,
    MAX_IMAGE_DECODE_PIXELS,
    MAX_IMAGE_PIXELS,
)


MAX_EVALUATION_IMAGE_EDGE = 5000


def _provider_config(provider: Any) -> dict[str, Any]:
    raw = getattr(provider, "provider_config", {})
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:
            pass
    if hasattr(raw, "dict"):
        try:
            return raw.dict()
        except Exception:
            pass
    return {}


def embedding_fingerprint(provider: Any, provider_id: str) -> str:
    config = _provider_config(provider)
    relevant = {
        key: config.get(key)
        for key in (
            "id",
            "type",
            "provider_type",
            "model",
            "model_name",
            "embedding_model",
            "base_url",
            "api_base",
            "api_base_url",
            "dimensions",
            "dimension",
            "dim",
        )
        if config.get(key) is not None
    }
    relevant.setdefault("id", provider_id)
    relevant["provider_class"] = f"{type(provider).__module__}.{type(provider).__name__}"
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _as_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        value = value.get("embedding", value.get("vector"))
    if not isinstance(value, (list, tuple)):
        raise GalleryError("Embedding 提供商没有返回向量。")
    if value and isinstance(value[0], (list, tuple)):
        value = value[0]
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise GalleryError("Embedding 提供商返回了无效向量。") from exc
    if not vector or len(vector) > 8192 or any(not math.isfinite(item) for item in vector):
        raise GalleryError("Embedding 提供商返回了空向量或无效数值。")
    return vector


async def create_embedding(provider: Any, text: str) -> list[float]:
    method = getattr(provider, "get_embedding", None)
    if callable(method):
        value = method(text)
        if inspect.isawaitable(value):
            value = await value
        return _as_vector(value)
    method = getattr(provider, "get_embeddings", None)
    if callable(method):
        value = method([text])
        if inspect.isawaitable(value):
            value = await value
        return _as_vector(value)
    raise GalleryError("所选模型不是可用的 Embedding 提供商。")


def parse_evaluation(text: str, store: GalleryStore) -> tuple[str, list[str]]:
    content = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()
    payload = None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                payload = None
    if isinstance(payload, dict):
        description = str(payload.get("description") or payload.get("描述") or "").strip()
        raw_tags = payload.get("tags", payload.get("标签", []))
        if isinstance(raw_tags, str):
            raw_tags = re.split(r"[,，、\n]+", raw_tags)
        tags = store.normalize_tags(raw_tags if isinstance(raw_tags, list) else [])
        if description:
            return description, tags
    if not content:
        raise GalleryError("模型没有返回有效描述。")
    return content[:3000], []


DEFAULT_SFW_EVALUATION_PROMPT = (
    "你是媒体图集的视觉标注器。请用简洁中文概括可见主体、场景、动作和风格，"
    "并给出 3 到 12 个简短、可检索的中文标签。"
    "这是普通 SFW 媒体。只描述画面中可见内容，不推断人物身份、年龄、出处或画外情节。"
    "{{media_context}}"
    '只输出合法 JSON，不要 Markdown，格式为：{"description":"...","tags":["...", "..."]}。'
)
DEFAULT_NSFW_EVALUATION_PROMPT = (
    "你是媒体图集的视觉标注器。请用简洁中文概括可见主体、场景、动作和风格，"
    "并给出 3 到 12 个简短、可检索的中文标签。"
    "这是管理员在后台明确选择后提交的 NSFW 媒体。仅作中性、客观的视觉描述，"
    "不进行露骨扩写，不推断人物身份、年龄或出处。"
    "{{media_context}}"
    '只输出合法 JSON，不要 Markdown，格式为：{"description":"...","tags":["...", "..."]}。'
)


def build_evaluation_prompt(custom_prompt: str, media_type: str) -> str:
    prompt = str(custom_prompt or "").strip()
    if not prompt:
        raise GalleryError("请在插件配置中填写对应范围的自定义评估提示词。")
    media_context = (
        "输入是同一视频的至多三张代表帧，请综合帧中确实可见的信息描述视频；不要假装看到了未提供的帧、声音或完整情节。"
        if media_type == "video"
        else "输入是一张图片。"
    )
    return prompt.replace("{{media_context}}", media_context)


def evaluation_prompt_version(custom_prompt: str) -> str:
    """Return a stable, non-reversible identifier for an evaluation prompt."""
    normalized = str(custom_prompt or "").strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _prepare_image_for_evaluation(
    source_path: str | Path,
    staging_dir: str | Path,
) -> Path | None:
    """Create an EXIF-corrected temporary copy only when the source is oversized."""
    source_path = Path(source_path)
    temporary_path: Path | None = None
    image_copy: Image.Image | None = None
    oriented: Image.Image | None = None
    encoded: Image.Image | None = None
    succeeded = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(source_path) as source:
                source.seek(0)
                source_width, source_height = source.size
                if max(source_width, source_height) <= MAX_EVALUATION_IMAGE_EDGE:
                    return None
                source_pixels = source_width * source_height
                if source_pixels > MAX_IMAGE_PIXELS:
                    raise GalleryError("图片像素超过安全处理上限，无法生成 AI 评估副本。")

                image_format = str(source.format or "").upper()
                if source_pixels > MAX_IMAGE_DECODE_PIXELS:
                    if image_format not in {"JPEG", "MPO"}:
                        raise GalleryError(
                            "超大非 JPEG 图片超过安全解码上限，无法生成 AI 评估副本。"
                        )
                    source.draft(
                        "RGB",
                        (max(1, source_width // 2), max(1, source_height // 2)),
                    )
                    if source.width * source.height > MAX_IMAGE_DECODE_PIXELS:
                        raise GalleryError(
                            "图片超过安全解码上限，无法生成 AI 评估副本。"
                        )

                icc_profile = source.info.get("icc_profile")
                image_copy = source.copy()
                oriented = ImageOps.exif_transpose(image_copy)
                if oriented is not image_copy:
                    image_copy.close()
                image_copy = None
                if max(oriented.size) > MAX_EVALUATION_IMAGE_EDGE:
                    oriented.thumbnail(
                        (MAX_EVALUATION_IMAGE_EDGE, MAX_EVALUATION_IMAGE_EDGE),
                        Image.Resampling.LANCZOS,
                    )
                has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                exif = oriented.getexif().tobytes()
                save_options: dict[str, Any]
                if has_alpha:
                    encoded = oriented.convert("RGBA")
                    temporary_path = Path(staging_dir) / (
                        f"ai-evaluation-{uuid.uuid4().hex}.png"
                    )
                    save_options = {"format": "PNG", "optimize": True}
                else:
                    encoded = oriented.convert("RGB")
                    temporary_path = Path(staging_dir) / (
                        f"ai-evaluation-{uuid.uuid4().hex}.jpg"
                    )
                    save_options = {
                        "format": "JPEG",
                        "quality": 90,
                        "optimize": True,
                        "progressive": True,
                    }
                if exif:
                    save_options["exif"] = exif
                if icc_profile:
                    save_options["icc_profile"] = icc_profile
                encoded.save(temporary_path, **save_options)
        succeeded = True
        return temporary_path
    except GalleryError:
        raise
    except Image.DecompressionBombError as exc:
        raise GalleryError("图片像素超过安全处理上限，无法生成 AI 评估副本。") from exc
    except Exception as exc:
        raise GalleryError("生成 AI 评估图片副本失败。") from exc
    finally:
        if image_copy is not None:
            image_copy.close()
        if oriented is not None:
            oriented.close()
        if encoded is not None:
            encoded.close()
        if temporary_path is not None and not succeeded:
            temporary_path.unlink(missing_ok=True)


class MediaAI:
    def __init__(
        self,
        context: Any,
        store: GalleryStore,
        logger: Any,
        sfw_evaluation_prompt: str,
        nsfw_evaluation_prompt: str,
    ):
        self.context = context
        self.store = store
        self.logger = logger
        self.sfw_evaluation_prompt = str(sfw_evaluation_prompt or "")
        self.nsfw_evaluation_prompt = str(nsfw_evaluation_prompt or "")

    async def evaluate(
        self,
        image_id: int,
        scope: str,
        chat_provider_id: str,
        embedding_provider_id: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        chat_provider_id = str(chat_provider_id or "").strip()
        if not chat_provider_id:
            raise GalleryError("尚未选择视觉评估模型。")
        media = await asyncio.to_thread(
            self.store.get_media_for_evaluation, int(image_id), scope
        )
        if not force and (
            str(media.get("description_override") or "").strip()
            or str(media.get("ai_description") or "").strip()
        ):
            return {"image_id": int(image_id), "scope": scope, "skipped": True}
        await asyncio.to_thread(
            self.store.set_ai_status,
            int(image_id),
            scope,
            "processing",
            "",
            chat_provider_id,
        )
        frames: list[Any] = []
        evaluation_image_copy: Path | None = None
        try:
            if media["media_type"] == "video":
                frames = await asyncio.to_thread(
                    self.store.extract_video_frames, media["path"]
                )
                image_inputs = [str(path) for path in frames]
            else:
                evaluation_image_copy = await asyncio.to_thread(
                    _prepare_image_for_evaluation,
                    media["path"],
                    self.store.staging_dir,
                )
                image_inputs = [
                    str(evaluation_image_copy or media["path"])
                ]
            custom_prompt = (
                self.nsfw_evaluation_prompt
                if scope == "nsfw"
                else self.sfw_evaluation_prompt
            )
            response = await self.context.llm_generate(
                chat_provider_id=chat_provider_id,
                prompt=build_evaluation_prompt(custom_prompt, media["media_type"]),
                image_urls=image_inputs,
                max_tokens=700,
            )
            response_text = str(getattr(response, "completion_text", "") or "").strip()
            description, tags = parse_evaluation(response_text, self.store)
            await asyncio.to_thread(
                self.store.save_ai_evaluation,
                int(image_id),
                scope,
                description,
                tags,
                chat_provider_id,
            )
        except Exception as exc:
            try:
                await asyncio.to_thread(
                    self.store.set_ai_status,
                    int(image_id),
                    scope,
                    "failed",
                    str(exc),
                    chat_provider_id,
                )
            except Exception:
                pass
            raise
        finally:
            if frames:
                self.store.cleanup_video_frames(frames)
            if evaluation_image_copy is not None:
                evaluation_image_copy.unlink(missing_ok=True)

        return {
            "image_id": int(image_id),
            "scope": scope,
            "description": description,
            "tags": tags,
        }


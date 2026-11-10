from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
from typing import Any

from .store import GalleryError, GalleryStore


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
    ) -> dict[str, Any]:
        chat_provider_id = str(chat_provider_id or "").strip()
        if not chat_provider_id:
            raise GalleryError("尚未选择视觉评估模型。")
        media = await asyncio.to_thread(
            self.store.get_media_for_evaluation, int(image_id), scope
        )
        if str(media.get("description_override") or "").strip() or str(
            media.get("ai_description") or ""
        ).strip():
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
        try:
            if media["media_type"] == "video":
                frames = await asyncio.to_thread(
                    self.store.extract_video_frames, media["path"]
                )
                image_inputs = [str(path) for path in frames]
            else:
                image_inputs = [str(media["path"])]
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

        indexed = False
        embedding_provider_id = str(embedding_provider_id or "").strip()
        if embedding_provider_id:
            try:
                provider = self.context.get_provider_by_id(embedding_provider_id)
                if not provider:
                    raise GalleryError("Embedding 提供商当前不可用。")
                searchable_text = "\n".join(
                    part for part in (description, " ".join(tags)) if part
                )
                vector = await create_embedding(provider, searchable_text)
                fingerprint = embedding_fingerprint(provider, embedding_provider_id)
                await asyncio.to_thread(
                    self.store.save_embedding,
                    int(image_id),
                    scope,
                    embedding_provider_id,
                    fingerprint,
                    vector,
                )
                indexed = True
            except Exception as exc:
                self.logger.warning(
                    "图集媒体 %s 描述已保存，但语义向量生成失败：%s",
                    image_id,
                    exc,
                )
        return {"image_id": int(image_id), "scope": scope, "indexed": indexed}


"""慢道 LLM 客户端（OpenAI 兼容）。

live 模式：真实调用并做 JSON 解析容错；mock 模式下调用方（beats / parser_agent）
使用确定性启发式，本模块不发起网络请求。
每次真实 API 往返写入 llm_log（按 run 另存 *.llm.jsonl）。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from .config import settings
from .llm_log import current_llm_stage, ensure_log_and_record


class LLMError(RuntimeError):
    pass


# 网关是否接受 reasoning_effort 只能实测。一旦某次调用因该参数被拒，本进程内
# 不再发送它，避免每次调用都白白失败一轮。
_reasoning_effort_supported = True


def _reasoning_kwargs() -> dict[str, Any]:
    """按当前阶段选择推理档位：设计要想得深，核验与审计不必。"""
    if not _reasoning_effort_supported:
        return {}
    effort = settings.reasoning_effort_for(current_llm_stage())
    if not effort:
        return {}
    model = settings.model.lower()
    if not (model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4")):
        return {}
    return {"reasoning_effort": effort}


def _disable_reasoning_effort_if_rejected(message: str) -> None:
    """网关拒收该参数时全局关闭，让本次运行改用网关默认档继续跑完。"""
    global _reasoning_effort_supported
    lowered = message.lower()
    if "reasoning_effort" in lowered and any(
        word in lowered for word in ("unsupported", "unrecognized", "not supported", "unknown", "invalid")
    ):
        _reasoning_effort_supported = False
        print("[llm] 网关拒收 reasoning_effort，后续调用改用默认推理档", flush=True)


def _message_content(resp: Any) -> str:
    """从 ChatCompletion / 兼容网关响应取出文本；HTML 首页等异常形态给出明确错误。"""
    if isinstance(resp, str):
        head = resp.lstrip()[:80].lower()
        if head.startswith("<!doctype") or head.startswith("<html"):
            raise LLMError(
                "网关返回了 HTML 页面而非 ChatCompletion；请检查 OPENAI_BASE_URL 是否应为 …/v1"
            )
        return resp
    try:
        choice0 = resp.choices[0]
        msg = choice0.message
        content = getattr(msg, "content", None)
        if content is None and isinstance(choice0, dict):
            content = (choice0.get("message") or {}).get("content")
        return content or ""
    except Exception as exc:  # noqa: BLE001
        raise LLMError(
            f"无法解析 LLM 响应（type={type(resp).__name__}）：{exc}"
        ) from exc


def extract_json(text: str) -> Any:
    """从模型输出提取 JSON（容忍 markdown 围栏与前后缀噪声文本）。"""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        start = text.find(start_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_ch:
                depth += 1
            elif text[i] == end_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError("无法从模型输出解析 JSON")


class LLMClient:
    def __init__(self) -> None:
        self._client = None

    @property
    def mode(self) -> str:
        return settings.llm_mode

    def _build_client(self):
        from openai import AsyncOpenAI  # 延迟导入：mock 模式无需可用 key

        return AsyncOpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        )

    def _ensure_client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def _reset_client(self) -> None:
        """丢弃异常连接池，使下一次重试建立全新 HTTP 客户端。"""
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.close()
            except Exception:  # noqa: BLE001 — 清理失败不覆盖原始调用错误
                pass

    async def chat_json(self, system: str, user: str, retries: int = 1) -> Any:
        """调用 LLM 并解析 JSON 输出；mock 模式直接抛错由调用方降级。"""
        if self.mode != "live":
            raise LLMError("mock 模式不发起真实 LLM 调用")
        errors: list[str] = []
        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            raw: str | None = None
            try:
                print(
                    f"[llm] calling model={settings.model} kind=chat_json "
                    f"attempt={attempt + 1}/{retries + 1}",
                    flush=True,
                )
                client = self._ensure_client()
                resp = await client.chat.completions.create(
                    model=settings.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    **_reasoning_kwargs(),
                )
                raw = _message_content(resp)
                parsed = extract_json(raw)
                await ensure_log_and_record(
                    {
                        "kind": "chat_json",
                        "model": settings.model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": True,
                        "system": system,
                        "user": user,
                        "raw": raw,
                        "parsed": parsed,
                        "error": None,
                    }
                )
                print(
                    f"[llm] success model={settings.model} kind=chat_json "
                    f"ms={round((time.perf_counter() - t0) * 1000, 1)}",
                    flush=True,
                )
                return parsed
            except Exception as exc:  # noqa: BLE001 — 统一转 LLMError，调用方决定降级
                err = f"{type(exc).__name__}: {exc}"
                errors.append(err)
                _disable_reasoning_effort_if_rejected(err)
                print(
                    f"[llm] failed model={settings.model} kind=chat_json "
                    f"attempt={attempt + 1}/{retries + 1} error={err}",
                    flush=True,
                )
                await ensure_log_and_record(
                    {
                        "kind": "chat_json",
                        "model": settings.model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": False,
                        "system": system,
                        "user": user,
                        "raw": raw,
                        "parsed": None,
                        "error": err,
                    }
                )
                if attempt < retries:
                    await self._reset_client()
            except asyncio.CancelledError:
                # 拍次看门狗取消时留痕，但不吞掉取消信号
                await ensure_log_and_record(
                    {
                        "kind": "chat_json",
                        "model": settings.model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": False,
                        "cancelled": True,
                        "error": "Cancelled by advisor stage timeout",
                    }
                )
                raise
        raise LLMError("；".join(errors))

    async def chat_json_vision(
        self,
        system: str,
        user_text: str,
        image_data_url: str | list[str],
        *,
        model: str | None = None,
        detail: str = "low",
        retries: int = 1,
    ) -> Any:
        """多模态调用：文本 + 一张或多张图片（data URL 或 https URL），解析 JSON。

        多图用于「原图 vs 候选图」对照审阅，图片顺序即提示词中的 IMAGE 序号。
        gpt-4o-mini / gpt-4o 等支持 image_url content part。
        mock 模式抛 LLMError，由调用方跳过视觉审图。
        """
        if self.mode != "live":
            raise LLMError("mock 模式不发起真实 LLM 调用")
        urls = image_data_url if isinstance(image_data_url, list) else [image_data_url]
        urls = [str(u).strip() for u in urls if isinstance(u, str) and str(u).strip()]
        if not urls:
            raise LLMError("缺少图片 URL")
        detail_val = detail if detail in ("low", "high", "auto") else "low"
        use_model = (model or settings.vision_model or settings.model).strip()
        user_content = [{"type": "text", "text": user_text}] + [
            {"type": "image_url", "image_url": {"url": url, "detail": detail_val}}
            for url in urls
        ]
        image_meta = [
            {
                "chars": len(url),
                "kind": "data_url" if url.startswith("data:") else "url",
                "detail": detail_val,
            }
            for url in urls
        ]
        errors: list[str] = []
        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            raw: str | None = None
            try:
                print(
                    f"[llm] calling model={use_model} kind=chat_json_vision "
                    f"attempt={attempt + 1}/{retries + 1}",
                    flush=True,
                )
                client = self._ensure_client()
                resp = await client.chat.completions.create(
                    model=use_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.2,
                    **_reasoning_kwargs(),
                )
                raw = _message_content(resp)
                parsed = extract_json(raw)
                await ensure_log_and_record(
                    {
                        "kind": "chat_json_vision",
                        "model": use_model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": True,
                        "system": system,
                        "user": user_text,
                        "image": image_meta,
                        "raw": raw,
                        "parsed": parsed,
                        "error": None,
                    }
                )
                print(
                    f"[llm] success model={use_model} kind=chat_json_vision "
                    f"ms={round((time.perf_counter() - t0) * 1000, 1)}",
                    flush=True,
                )
                return parsed
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                errors.append(err)
                _disable_reasoning_effort_if_rejected(err)
                print(
                    f"[llm] failed model={use_model} kind=chat_json_vision "
                    f"attempt={attempt + 1}/{retries + 1} error={err}",
                    flush=True,
                )
                await ensure_log_and_record(
                    {
                        "kind": "chat_json_vision",
                        "model": use_model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": False,
                        "system": system,
                        "user": user_text,
                        "image": image_meta,
                        "raw": raw,
                        "parsed": None,
                        "error": err,
                    }
                )
                if attempt < retries:
                    await self._reset_client()
            except asyncio.CancelledError:
                await ensure_log_and_record(
                    {
                        "kind": "chat_json_vision",
                        "model": use_model,
                        "attempt": attempt,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "ok": False,
                        "cancelled": True,
                        "error": "Cancelled by advisor stage timeout",
                    }
                )
                raise
        raise LLMError("；".join(errors))

#!/usr/bin/env python
"""探测慢道 LLM（文本 + 可选多模态）是否可用。

用法（先激活 conda vizguide）::

    cd backend
    python scripts/probe_llm.py
    python scripts/probe_llm.py --text-only
    python scripts/probe_llm.py --vision-only
    python scripts/probe_llm.py --env-file .env

退出码：0=所请求探测全部成功；1=配置不足或调用失败。
不打印 API Key。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 1x1 PNG
_TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def load_dotenv(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            # 脚本探测以 env 文件为准（覆盖空的进程环境）
            os.environ[key] = value
    return True


def _clip(err: object, n: int = 400) -> str:
    s = str(err).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def probe_text(llm) -> tuple[bool, str]:
    from app.llm import LLMError

    t0 = time.perf_counter()
    try:
        out = await llm.chat_json(
            "Reply with JSON only. No markdown.",
            'Return exactly {"ok": true, "ping": "pong"}',
            retries=1,
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        ok = isinstance(out, dict) and out.get("ok") is True
        return ok, f"OK ({ms} ms) → {out}" if ok else f"UNEXPECTED ({ms} ms) → {out}"
    except LLMError as exc:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return False, f"FAIL ({ms} ms) {_clip(exc)}"
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return False, f"FAIL ({ms} ms) {type(exc).__name__}: {_clip(exc)}"


async def probe_vision(llm) -> tuple[bool, str]:
    from app.llm import LLMError

    t0 = time.perf_counter()
    try:
        out = await llm.chat_json_vision(
            "Reply with JSON only. No markdown.",
            'Look at the tiny image and return exactly {"ok": true, "has_image": true}',
            _TINY_PNG,
            detail="low",
            retries=1,
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        ok = isinstance(out, dict) and out.get("ok") is True
        return ok, f"OK ({ms} ms) → {out}" if ok else f"UNEXPECTED ({ms} ms) → {out}"
    except LLMError as exc:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return False, f"FAIL ({ms} ms) {_clip(exc)}"
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return False, f"FAIL ({ms} ms) {type(exc).__name__}: {_clip(exc)}"


async def main_async(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()
    loaded = load_dotenv(env_path)
    print(f"env_file={'loaded ' + str(env_path) if loaded else 'missing ' + str(env_path)}")

    from app.config import settings
    from app.llm import LLMClient

    print(f"mode={settings.llm_mode}")
    print(f"model={settings.model}")
    print(f"vision_model={settings.vision_model}")
    print(f"base_url={settings.openai_base_url}")
    print(f"has_key={bool(settings.openai_api_key)} key_len={len(settings.openai_api_key or '')}")
    if settings.openai_base_url.rstrip("/").lower().endswith("/v1") is False:
        print("WARN: base_url 通常应以 /v1 结尾；否则可能打到网关 HTML 首页")

    if settings.llm_mode != "live" or not settings.openai_api_key:
        print("RESULT: SKIP — need VIZGUIDE_LLM_MODE=live and OPENAI_API_KEY")
        return 1

    llm = LLMClient()
    do_text = not args.vision_only
    do_vision = not args.text_only
    ok_all = True

    if do_text:
        ok, msg = await probe_text(llm)
        print(f"TEXT: {msg}")
        ok_all = ok_all and ok

    if do_vision:
        ok, msg = await probe_vision(llm)
        print(f"VISION: {msg}")
        ok_all = ok_all and ok

    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe VizGuide LLM (text/vision)")
    parser.add_argument(
        "--env-file",
        default=str(BACKEND_DIR / ".env"),
        help="path to .env (default: backend/.env)",
    )
    parser.add_argument("--text-only", action="store_true", help="only test chat_json")
    parser.add_argument("--vision-only", action="store_true", help="only test chat_json_vision")
    args = parser.parse_args()
    if args.text_only and args.vision_only:
        parser.error("use at most one of --text-only / --vision-only")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

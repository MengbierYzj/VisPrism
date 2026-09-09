"""运行配置：环境变量集中读取。

注意区分两个正交概念（详见 doc/后端方案.md）：
- 快慢双通道：每个 persona agent 每次推理固定走"慢-快-慢-快"四拍，拓扑不变；
- LLM 双模式（live/mock）：仅是慢道两拍（读图立意、溯源裁决）的实现后备——
  配置了 OpenAI 兼容 API 即走真实 LLM，否则用确定性启发式顶替，保证系统
  离线可端到端运行、测试可复现。
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class Settings:
    """属性即取即读，便于测试用环境变量覆盖。"""

    @property
    def data_dir(self) -> Path:
        return Path(_env("VIZGUIDE_DATA_DIR", str(REPO_ROOT / "data")))

    @property
    def storage_dir(self) -> Path:
        return Path(_env("VIZGUIDE_STORAGE_DIR", str(BACKEND_DIR / "storage")))

    @property
    def openai_api_key(self) -> str:
        return _env("OPENAI_API_KEY")

    @property
    def openai_base_url(self) -> str:
        """OpenAI 兼容网关根；若只写了站点根（无 /v1）则自动补上，避免打到 HTML 首页。"""
        url = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if not url:
            return "https://api.openai.com/v1"
        lower = url.lower()
        # 已是版本化 API 路径则不改
        if lower.endswith("/v1") or "/v1/" in lower + "/":
            return url
        return url + "/v1"

    @property
    def model(self) -> str:
        return _env("VIZGUIDE_MODEL", "gpt-4o-mini")

    @property
    def vision_model(self) -> str:
        """多模态审图模型；默认与慢道文本模型相同（gpt-4o-mini 支持 vision）。"""
        return _env("VIZGUIDE_VISION_MODEL") or self.model

    # 设计拍要想得深，只做判断/审计的拍不需要同等推理深度。gpt-5 上单次调用可达
    # 两三分钟，而一个 persona 要串行 7–9 次，分档是最直接的提速手段。
    # 这里显式列出「不产出 spec」的阶段，未知阶段一律按设计档：宁可慢，也不因为
    # 阶段名没登记就悄悄降低产出质量。
    _VERIFY_STAGES = ("beat1", "beat2", "beat3_visual_acceptance", "beat4")

    @property
    def reasoning_effort(self) -> str:
        """VIZGUIDE_REASONING_EFFORT：设计拍的推理档位（minimal|low|medium|high）。"""
        value = _env("VIZGUIDE_REASONING_EFFORT", "medium").lower()
        return value if value in ("minimal", "low", "medium", "high", "") else "medium"

    @property
    def verify_reasoning_effort(self) -> str:
        """VIZGUIDE_VERIFY_REASONING_EFFORT：读图/审图/审计等核验拍的推理档位。"""
        value = _env("VIZGUIDE_VERIFY_REASONING_EFFORT", "low").lower()
        return value if value in ("minimal", "low", "medium", "high", "") else "low"

    def reasoning_effort_for(self, stage: str | None) -> str:
        """按阶段名选档；阶段未知时按设计档，宁可慢也不牺牲产出质量。"""
        if not stage:
            return self.reasoning_effort
        return self.verify_reasoning_effort if stage.startswith(self._VERIFY_STAGES) else self.reasoning_effort

    @property
    def vision_mode(self) -> str:
        """VIZGUIDE_VISION_MODE=off|auto|on。

        auto/on：live 时启用拍3 视觉审图（优先服务端 VL→PNG；可被
        context.preview_image 覆盖）；off：关闭。
        """
        mode = _env("VIZGUIDE_VISION_MODE", "auto").lower()
        return mode if mode in ("off", "auto", "on") else "auto"

    @property
    def vision_server_render(self) -> bool:
        """是否用 vl-convert 在服务端将 working spec 渲成 PNG（默认开）。"""
        raw = _env("VIZGUIDE_VISION_SERVER_RENDER", "1").lower()
        return raw not in ("0", "false", "off", "no")

    @property
    def vl_render_scale(self) -> float:
        """vl-convert PNG 缩放；1.0 兼顾清晰度与 token。"""
        try:
            return float(_env("VIZGUIDE_VL_RENDER_SCALE", "1"))
        except ValueError:
            return 1.0

    @property
    def preview_image_max_chars(self) -> int:
        """preview_image / 服务端渲染 data URL 字符上限，防止撑爆请求。"""
        try:
            value = int(_env("VIZGUIDE_PREVIEW_IMAGE_MAX_CHARS", "3500000"))
        except ValueError:
            return 3500000
        return min(max(value, 50_000), 8_000_000)

    @property
    def llm_log_enabled(self) -> bool:
        """是否落盘每次 LLM API 往返（默认开）。"""
        raw = _env("VIZGUIDE_LLM_LOG", "1").lower()
        return raw not in ("0", "false", "off", "no")

    @property
    def parser_chunk_chars(self) -> int:
        """Parser live 抽取的单块字符上限；较小块可规避兼容网关的长生成超时。"""
        try:
            value = int(_env("VIZGUIDE_PARSER_CHUNK_CHARS", "3000"))
        except ValueError:
            return 3000
        return min(max(value, 1000), 12000)

    @property
    def llm_mode(self) -> str:
        """VIZGUIDE_LLM_MODE=auto|live|mock，解析为 live|mock。"""
        mode = _env("VIZGUIDE_LLM_MODE", "auto").lower()
        if mode == "auto":
            return "live" if self.openai_api_key else "mock"
        return mode if mode in ("live", "mock") else "mock"

    @property
    def mock_beat_delay_ms(self) -> int:
        try:
            return int(_env("VIZGUIDE_MOCK_BEAT_DELAY_MS", "300"))
        except ValueError:
            return 300

    @property
    def advisor_engine(self) -> str:
        """VIZGUIDE_ADVISOR_ENGINE=v1|v2，决定 /api/advisor/run 由哪个引擎承接。

        v1（默认）：编译执行引擎，改动受 actions 词表约束；
        v2：契约核验引擎，LLM 直接重构 spec、程序核验 L1 不变量。
        两者响应结构一致，切换不改变既有前端契约。
        """
        engine = _env("VIZGUIDE_ADVISOR_ENGINE", "v1").lower()
        return engine if engine in ("v1", "v2") else "v1"

    @property
    def v2_l1_enforcement(self) -> str:
        """VIZGUIDE_V2_L1_ENFORCEMENT=patch|report|off（v2 引擎拍4 契约核验强度）。

        patch（默认）：核验后对仍违规且可编译的 L1 规则做确定性令牌修补；
        report：只核验并留痕，不修改 LLM 产出；
        off：跳过核验。三档用于「契约是否可验证」的消融对照。
        """
        mode = _env("VIZGUIDE_V2_L1_ENFORCEMENT", "patch").lower()
        return mode if mode in ("patch", "report", "off") else "patch"

    @property
    def replay_beat_delay_ms(self) -> int:
        """回放历史 run 时每一拍的停留时间；设 0 可用于脚本与测试。"""
        try:
            return min(max(int(_env("VIZGUIDE_REPLAY_BEAT_DELAY_MS", "350")), 0), 5000)
        except ValueError:
            return 350

    @property
    def advisor_stage_timeout_seconds(self) -> int:
        """单个可见拍次无状态推进的最长挂钟时间。

        live 网关请求可能长时间不返回；v2 runner 的看门狗据此取消该 persona，
        并按既有前端契约暴露 agent 错误，而不是让前端一直轮询。
        """
        try:
            value = int(_env("VIZGUIDE_ADVISOR_STAGE_TIMEOUT_SECONDS", "720"))
        except ValueError:
            return 720
        return min(max(value, 1), 900)

    @property
    def prefer_mode(self) -> str:
        """VIZGUIDE_PREFER_MODE=suggest|apply（兼容旧名 VIZGUIDE_CHART_TYPE_PREFER_MODE）。

        suggest（默认）：L2 `prefer: chart.type` 仅建议；其它可编译 prefer（如 mark.color）仍执行。
        apply：所有可编译 prefer 与 set 同权（含受控 chart.type → set_mark_type）。
        """
        mode = (_env("VIZGUIDE_PREFER_MODE") or _env("VIZGUIDE_CHART_TYPE_PREFER_MODE", "suggest")).lower()
        return mode if mode in ("suggest", "apply") else "suggest"

    @property
    def chart_type_prefer_mode(self) -> str:
        """兼容别名；请改用 prefer_mode。"""
        return self.prefer_mode

    @property
    def advisor_chart_type_changes_enabled(self) -> bool:
        """机构顾问能否自动改图型（默认否）。

        这是和 ``prefer_mode`` 分离的安全门：后者只决定 L2 的 prefer
        是否可执行；本开关决定 persona 规则是否可以产生任何 chart.type
        操作。用户在界面中明确提出的图型编辑仍走 user-intent 直通路径。
        """
        mode = _env("VIZGUIDE_ADVISOR_CHART_TYPE_MODE").lower()
        if mode:
            return mode in ("allow", "enabled", "on", "true", "1")
        raw = _env("VIZGUIDE_ALLOW_ADVISOR_CHART_TYPE_CHANGE", "0").lower()
        return raw in ("1", "true", "on", "yes", "allow", "enabled")

    @property
    def cors_origins(self) -> list[str]:
        raw = _env(
            "VIZGUIDE_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
        )
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()

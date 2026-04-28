from typing import Any, Literal, TypedDict

Provider = Literal["claude", "gemini"]


class AgentState(TypedDict, total=False):
    user_prompt: str
    provider_keys: dict[str, str]
    provider: Provider
    model: str

    manim_code: str
    previous_code: str

    compile_log: str
    error_log: str

    error_context: str

    render_ok: bool
    video_url: str | None

    job_id: str | None

    timings: list[dict[str, Any]]

    error: str
    artifacts: dict[str, Any]

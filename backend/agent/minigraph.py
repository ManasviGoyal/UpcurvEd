# backend/agent/minigraph.py
import textwrap
from typing import TypedDict


class MiniState(TypedDict, total=False):
    user_prompt: str
    manim_code: str


def _sanitize(s: str) -> str:
    s = (s or "")[:120]
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return s


def draft_code_node(state: MiniState) -> MiniState:
    text = _sanitize(state.get("user_prompt", ""))
    code = textwrap.dedent(f"""\
        from manim import Text, Write
        from manim_voiceover import VoiceoverScene
        from manim_voiceover.services.gtts import GTTSService

        class GeneratedScene(VoiceoverScene):
            def construct(self):
                self.set_speech_service(GTTSService())
                
                t = Text("{text}")
                with self.voiceover(text="{text}") as tracker:
                    self.play(Write(t), run_time=tracker.duration)
                self.wait(0.5)
    """)
    new_state: MiniState = dict(state)  # copy
    new_state["manim_code"] = code
    return new_state


def echo_manim_code(prompt: str) -> str:
    # Kept intentionally simple to avoid dragging workflow/runtime deps into desktop mode.
    result = draft_code_node({"user_prompt": prompt})
    code = result.get("manim_code")
    if not code:
        raise RuntimeError("Mini graph returned no 'manim_code'.")
    return code

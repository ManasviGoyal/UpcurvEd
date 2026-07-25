"""Reusable Manim scene components for structured UpcurvEd videos.

Standard scenes use deterministic layouts. Model-authored custom scenes run inside a
bounded VoiceoverScene wrapper. Internal planning metadata is never shown on screen.
"""

from __future__ import annotations

import re
from typing import Any


def portable_math_text(value: Any) -> str:
    """Convert common model math notation to text that Pango renders reliably."""
    text = str(value or "").replace("\n", " ").strip()
    replacements = {
        "−": "-",
        "–": "-",
        "—": "-",
        "±": "+/-",
        "×": "*",
        "÷": "/",
        "·": "*",
        "√": "sqrt",
        "²": "^2",
        "³": "^3",
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\\(?:dfrac|frac)\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1) / (\2)", text)
    text = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", text)
    text = text.replace("\\pm", "+/-").replace("\\times", "*").replace("\\cdot", "*")
    text = text.replace("\\left", "").replace("\\right", "")
    text = text.replace("{", "(").replace("}", ")")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _looks_equation_like(value: Any) -> bool:
    text = portable_math_text(value)
    if not text:
        return False
    if "=" in text or re.search(r"(?:<=|>=|!=)", text):
        return True
    if re.search(r"[A-Za-z0-9)]\s*[+*/^]\s*[A-Za-z0-9(]", text):
        return True
    if re.search(r"[A-Za-z0-9)]\s*-\s*(?:\d|[A-Za-z]\b|\()", text):
        return True
    return bool(re.search(r"\b(?:sqrt|sin|cos|tan|log|ln)\s*\(", text, flags=re.IGNORECASE))


def _math_to_speech(value: Any) -> str:
    text = portable_math_text(value)
    text = re.sub(r"\^2\b", " squared", text)
    text = re.sub(r"\^3\b", " cubed", text)
    text = re.sub(r"\^\s*([A-Za-z0-9.-]+)", r" to the power of \1", text)
    text = re.sub(r"\bsqrt\s*\(", "the square root of (", text, flags=re.IGNORECASE)
    for source, target in (
        ("+/-", " plus or minus "),
        (">=", " is greater than or equal to "),
        ("<=", " is less than or equal to "),
        ("!=", " is not equal to "),
        ("=", " equals "),
        ("*", " times "),
        ("/", " divided by "),
        ("+", " plus "),
        ("-", " minus "),
    ):
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def _fallback_step_narration(step: str, index: int, total: int) -> str:
    spoken = _math_to_speech(step) if _looks_equation_like(step) else str(step or "").strip()
    spoken = re.sub(
        r"^\s*(?:first|firstly|next|then|after that|finally|lastly)\s*[:,.-]?\s*",
        "",
        spoken,
        flags=re.IGNORECASE,
    ).strip().rstrip(" .")
    if not spoken:
        spoken = "Notice what changes in this step"
    if total <= 1:
        return spoken + "."
    prefix = "First" if index == 0 else ("Finally" if index == total - 1 else "Next")
    return f"{prefix}: {spoken}."


def _derive_display_points(value: Any, *, limit: int = 3) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|[;•]+", text)
    points: list[str] = []
    for raw in parts:
        point = re.sub(r"^[\s\-–—•]+", "", raw).strip().rstrip(" .")
        if not point:
            continue
        if len(point) > 112:
            point = point[:109].rstrip() + "..."
        if point.lower() not in {existing.lower() for existing in points}:
            points.append(point)
        if len(points) >= limit:
            break
    return points


def _has_visible_component_content(scene: dict[str, Any]) -> bool:
    return bool(
        str(scene.get("subtitle") or "").strip()
        or str(scene.get("learner_question") or "").strip()
        or str(scene.get("formula") or "").strip()
        or str(scene.get("code_snippet") or "").strip()
        or [x for x in (scene.get("key_points") or []) if str(x).strip()]
        or [x for x in (scene.get("labels") or []) if str(x).strip()]
        or [x for x in (scene.get("steps") or scene.get("calculation_steps") or []) if str(x).strip()]
    )


def _scene_for_render(scene: dict[str, Any]) -> dict[str, Any]:
    rendered = dict(scene)
    if rendered.get("formula"):
        rendered["formula"] = portable_math_text(rendered["formula"])

    rendered["key_points"] = [
        str(value).strip()
        for value in (rendered.get("key_points") or [])
        if str(value).strip()
    ][:5]

    raw_steps = rendered.get("steps") or rendered.get("calculation_steps") or []
    steps = [
        portable_math_text(step) if _looks_equation_like(step) else str(step).strip()
        for step in raw_steps
        if str(step).strip()
    ][:6]
    provided = [
        str(value).strip()
        for value in (rendered.get("step_narrations") or [])
        if str(value).strip()
    ][:6]
    narrations = [
        provided[index]
        if index < len(provided)
        else _fallback_step_narration(step, index, len(steps))
        for index, step in enumerate(steps)
    ]
    if steps:
        rendered["steps"] = steps
        rendered["step_narrations"] = narrations
        # Keep the old name in the generated wrapper so saved custom bodies continue to work.
        rendered["calculation_steps"] = steps

    if str(rendered.get("type") or "") != "title_scene" and not _has_visible_component_content(rendered):
        rendered["key_points"] = _derive_display_points(rendered.get("narration"), limit=3)
        if not rendered["key_points"]:
            rendered["key_points"] = ["Focus on the key relationship in this idea"]
    return rendered


def _safe_python_literal(value: Any) -> str:
    """Return data as valid Python source for generated Manim scene files."""
    return repr(value)


def build_code_snippet_scene_code(scene: dict[str, Any]) -> str:
    """Render the complete learner-facing snippet with deterministic pagination.

    The fallback never depends on Manim ``Code`` internals and never drops later lines. Long
    snippets are split across successive pages while retaining their original line numbers.
    """
    safe_scene = _scene_for_render(scene)
    scene_literal = _safe_python_literal(safe_scene)
    template = r'''
import manim as mn
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))
        scene = __SCENE_JSON__
        title_text = str(scene.get("title") or "Code example")
        narration = str(scene.get("narration") or title_text)
        snippet = str(scene.get("code_snippet") or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).strip("\n")
        raw_lines = snippet.splitlines() if snippet else ["# Code snippet unavailable"]
        page_size = 16
        pages = [raw_lines[index:index + page_size] for index in range(0, len(raw_lines), page_size)]

        bg = mn.Rectangle(width=mn.config.frame_width, height=mn.config.frame_height)
        bg.set_fill("#0b1120", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

        title = mn.Text(title_text, font_size=35, color=mn.WHITE)
        if title.width > 11.0:
            title.scale_to_fit_width(11.0)
        title.to_edge(mn.UP, buff=0.35)

        panel = mn.RoundedRectangle(
            width=11.5,
            height=5.55,
            corner_radius=0.18,
            color=mn.TEAL_C,
            stroke_width=1.5,
        )
        panel.set_fill("#111827", opacity=0.98)
        panel.next_to(title, mn.DOWN, buff=0.28)

        def build_rows(lines, starting_line):
            longest = max((len(line) for line in lines), default=1)
            line_count = max(1, len(lines))
            font_size = min(23, max(13, int(560 / max(24, longest))))
            font_size = min(font_size, max(13, int(330 / line_count)))
            rows = mn.VGroup()
            for offset, line in enumerate(lines):
                number = mn.Text(f"{starting_line + offset:>2}", font_size=font_size, color=mn.GRAY_B)
                code = mn.Text(line if line else " ", font_size=font_size, color=mn.WHITE)
                row = mn.VGroup(number, code).arrange(mn.RIGHT, buff=0.28, aligned_edge=mn.DOWN)
                rows.add(row)
            rows.arrange(mn.DOWN, aligned_edge=mn.LEFT, buff=0.08)
            if rows.width > 10.75:
                rows.scale_to_fit_width(10.75)
            if rows.height > 4.75:
                rows.scale_to_fit_height(4.75)
            rows.move_to(panel.get_center()).align_to(panel, mn.LEFT).shift(mn.RIGHT * 0.34)
            return rows

        with self.voiceover(text=narration) as tracker:
            self.play(mn.FadeIn(title, shift=mn.DOWN * 0.08), mn.Create(panel), run_time=0.75)
            current_rows = None
            current_focus = None
            used = 0.75
            for page_index, page_lines in enumerate(pages):
                rows = build_rows(page_lines, page_index * page_size + 1)
                nonempty = [i for i, line in enumerate(page_lines) if line.strip()]
                focus_index = nonempty[min(len(nonempty) - 1, len(nonempty) // 2)] if nonempty else 0
                focus = mn.SurroundingRectangle(
                    rows[focus_index], color=mn.YELLOW, buff=0.07, corner_radius=0.05
                )
                if current_rows is None:
                    page_time = min(1.8, max(0.8, 0.08 * len(rows)))
                    self.play(
                        mn.LaggedStart(
                            *[mn.FadeIn(row, shift=mn.RIGHT * 0.08) for row in rows],
                            lag_ratio=0.03,
                        ),
                        run_time=page_time,
                    )
                else:
                    page_time = 0.7
                    self.play(
                        mn.FadeOut(current_rows, shift=mn.LEFT * 0.12),
                        mn.FadeOut(current_focus),
                        mn.FadeIn(rows, shift=mn.RIGHT * 0.12),
                        run_time=page_time,
                    )
                self.play(mn.Create(focus), mn.Indicate(rows[focus_index]), run_time=0.55)
                used += page_time + 0.55
                current_rows, current_focus = rows, focus
                if page_index < len(pages) - 1:
                    self.wait(0.45)
                    used += 0.45
            remaining = max(0.15, float(getattr(tracker, "duration", 0) or 0) - used)
            if remaining > 0.15:
                self.wait(remaining)
        self.wait(1.0)
        fades = [mn.FadeOut(panel), mn.FadeOut(title)]
        if current_rows is not None:
            fades.append(mn.FadeOut(current_rows))
        if current_focus is not None:
            fades.append(mn.FadeOut(current_focus))
        self.play(*fades, run_time=0.55)
        self.wait(0.1)
'''.strip() + "\n"
    return template.replace("__SCENE_JSON__", scene_literal)


def build_component_scene_code(scene: dict[str, Any]) -> str:
    """Return one runnable Manim/Voiceover scene for a standard scene object."""
    if str(scene.get("code_snippet") or "").strip():
        return build_code_snippet_scene_code(scene)
    scene_literal = _safe_python_literal(_scene_for_render(scene))
    template = r'''
import re
import manim as mn
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))

        scene = __SCENE_JSON__
        scene_type = str(scene.get("type") or "concept_scene")
        learning_role = str(scene.get("learning_role") or "").lower()
        title_text = str(scene.get("title") or scene.get("heading") or "Key idea")
        subtitle_text = str(scene.get("subtitle") or "")
        narration = str(scene.get("narration") or title_text)
        learner_question = str(scene.get("learner_question") or "")
        labels = [str(x) for x in (scene.get("labels") or []) if str(x).strip()][:5]
        key_points = [str(x) for x in (scene.get("key_points") or []) if str(x).strip()][:5]
        formula_text = str(scene.get("formula") or "").replace("\n", " ").strip()
        steps = [
            str(x).replace("\n", " ").strip()
            for x in (scene.get("steps") or scene.get("calculation_steps") or [])
            if str(x).strip()
        ][:6]
        step_narrations = [
            str(x).replace("\n", " ").strip()
            for x in (scene.get("step_narrations") or [])
            if str(x).strip()
        ][:6]
        while len(step_narrations) < len(steps):
            step_narrations.append(steps[len(step_narrations)])

        def clean_text(text):
            value = str(text or "").replace("\n", " ").strip()
            replacements = {
                "−": "-", "–": "-", "—": "-", "±": "+/-", "×": "*",
                "÷": "/", "·": "*", "√": "sqrt", "²": "^2", "³": "^3",
                "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
                "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
            }
            for source, target in replacements.items():
                value = value.replace(source, target)
            value = value.replace("\\pm", "+/-").replace("\\times", "*")
            value = value.replace("\\cdot", "*").replace("\\left", "").replace("\\right", "")
            value = value.replace("{", "(").replace("}", ")")
            return re.sub(r"\s+", " ", value).strip()

        def safe_label(text, limit=70):
            value = clean_text(text)
            if len(value) > limit:
                value = value[: limit - 3].rstrip() + "..."
            return value

        def fit_text(text, size=28, color=mn.WHITE, max_width=11.2):
            mob = mn.Text(safe_label(text, 110), font_size=size, color=color)
            if mob.width > max_width:
                mob.scale_to_fit_width(max_width)
            return mob

        def formula_mob(text, size=30, color=mn.YELLOW):
            return fit_text(text, size=size, color=color, max_width=10.8)

        def hold_voiceover(tracker, used_time):
            duration = float(getattr(tracker, "duration", 0) or 0)
            remaining = max(0.15, duration - float(used_time or 0))
            if remaining > 0.15:
                self.wait(remaining)

        def add_background():
            bg = mn.Rectangle(width=mn.config.frame_width, height=mn.config.frame_height)
            bg.set_fill("#0f172a", opacity=1)
            bg.set_stroke(width=0)
            self.add(bg)
            return bg

        def clean_out(bg):
            leftovers = [m for m in list(self.mobjects) if m is not bg]
            if leftovers:
                self.play(*[mn.FadeOut(m) for m in leftovers], run_time=0.5)
            self.wait(0.1)

        bg = add_background()

        if scene_type == "title_scene":
            line = mn.Line(start=[-3.9, 0, 0], end=[3.9, 0, 0], color=mn.BLUE_C)
            title = fit_text(title_text, 47, mn.WHITE, 11.0).next_to(line, mn.UP, buff=0.38)
            subtitle_source = subtitle_text or learner_question
            subtitle = fit_text(subtitle_source, 26, mn.BLUE_B, 10.5).next_to(line, mn.DOWN, buff=0.38)
            formula = formula_mob(formula_text, 27) if formula_text else None
            if formula is not None:
                formula.next_to(subtitle, mn.DOWN, buff=0.3)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.Create(line), mn.Write(title), run_time=1.15)
                if subtitle_source:
                    self.play(mn.FadeIn(subtitle, shift=mn.UP * 0.12), run_time=0.7)
                if formula is not None:
                    self.play(mn.Write(formula), run_time=0.75)
                    self.play(mn.Indicate(formula), run_time=0.6)
                    hold_voiceover(tracker, 3.2)
                else:
                    hold_voiceover(tracker, 1.85)
            fades = [mn.FadeOut(title), mn.Uncreate(line)]
            if subtitle_source:
                fades.append(mn.FadeOut(subtitle))
            if formula is not None:
                fades.append(mn.FadeOut(formula))
            self.play(*fades, run_time=0.65)
            self.wait(0.1)
            return

        header = fit_text(title_text, 35, mn.WHITE, 10.6).to_edge(mn.UP, buff=0.4)
        self.play(mn.FadeIn(header, shift=mn.DOWN * 0.08), run_time=0.4)

        # Instructional sequences use one voice request for the whole scene. This is more
        # reliable than making a separate gTTS request for every visible step.
        if steps:
            formula = formula_mob(formula_text, 28) if formula_text else None
            if formula is not None:
                formula.next_to(header, mn.DOWN, buff=0.25)
            anchor = formula if formula is not None else header

            step_font = 25 if len(steps) <= 3 else (23 if len(steps) <= 4 else 21)
            step_mobs = mn.VGroup(*[
                fit_text(step_text, step_font, mn.WHITE, 10.2)
                for step_text in steps
            ])
            step_mobs.arrange(mn.DOWN, aligned_edge=mn.LEFT, buff=0.22)
            if step_mobs.height > 4.35:
                step_mobs.scale_to_fit_height(4.35)
            step_mobs.next_to(anchor, mn.DOWN, buff=0.38)
            if step_mobs.get_bottom()[1] < -3.15:
                step_mobs.shift(mn.UP * (-3.15 - step_mobs.get_bottom()[1]))

            combined_narration = " ".join(
                [narration] + [
                    step_narrations[index] if index < len(step_narrations) else steps[index]
                    for index in range(len(steps))
                ]
            ).strip()
            with self.voiceover(text=combined_narration) as tracker:
                used = 0.0
                if formula is not None:
                    self.play(mn.Write(formula), run_time=0.7)
                    used += 0.7
                else:
                    self.play(mn.Indicate(header), run_time=0.55)
                    used += 0.55
                for step_mob in step_mobs:
                    self.play(mn.Write(step_mob), run_time=0.65)
                    self.wait(0.55)
                    used += 1.2

                final_step = step_mobs[-1]
                completion_box = mn.SurroundingRectangle(
                    final_step, color=mn.GREEN_C, buff=0.16, corner_radius=0.08
                )
                self.play(mn.Create(completion_box), mn.Indicate(final_step), run_time=0.75)
                used += 0.75
                hold_voiceover(tracker, used)
            self.wait(1.5)
            clean_out(bg)
            return

        formula = formula_mob(formula_text) if formula_text else None
        if formula is not None:
            formula.next_to(header, mn.DOWN, buff=0.25)
            self.play(mn.Write(formula), run_time=0.65)
        content_top = formula if formula is not None else header

        if scene_type == "question_scene":
            question_text = subtitle_text or learner_question or title_text
            q = fit_text(question_text, 33, mn.YELLOW, 10.4).next_to(content_top, mn.DOWN, buff=0.55)
            mark = mn.Text("?", font_size=82, color=mn.BLUE_C).next_to(q, mn.LEFT, buff=0.3)
            details = mn.VGroup(*[fit_text(x, 22, mn.WHITE, 8.5) for x in labels[:3]])
            if len(details):
                details.arrange(mn.DOWN, aligned_edge=mn.LEFT, buff=0.18).next_to(q, mn.DOWN, buff=0.45)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.FadeIn(mark, scale=0.75), mn.Write(q), run_time=1.0)
                if len(details):
                    self.play(mn.LaggedStart(*[mn.FadeIn(x) for x in details], lag_ratio=0.12), run_time=0.9)
                self.play(mn.Indicate(formula if formula is not None else q), run_time=0.65)
                hold_voiceover(tracker, 2.95)

        elif scene_type == "process_scene" and labels:
            names = labels[:3]
            count = len(names)
            xs = {1: [0], 2: [-2.4, 2.4], 3: [-3.4, 0, 3.4]}[count]
            boxes = mn.VGroup()
            for index, name in enumerate(names):
                box = mn.RoundedRectangle(width=2.25, height=1.0, corner_radius=0.16, color=[mn.BLUE_C, mn.GREEN_C, mn.ORANGE][index])
                box.set_fill("#1e293b", opacity=0.9).move_to([xs[index], -0.35, 0])
                txt = fit_text(name, 22, mn.WHITE, 1.9).move_to(box)
                boxes.add(mn.VGroup(box, txt))
            arrows = mn.VGroup()
            for index in range(count - 1):
                arrows.add(mn.Arrow(boxes[index].get_right(), boxes[index + 1].get_left(), buff=0.16, color=mn.WHITE))
            with self.voiceover(text=narration) as tracker:
                used = 0.4
                self.play(mn.FadeIn(boxes[0]), run_time=0.65)
                used += 0.65
                for index, arrow in enumerate(arrows):
                    self.play(mn.GrowArrow(arrow), mn.FadeIn(boxes[index + 1]), run_time=0.95)
                    used += 0.95
                self.play(mn.Indicate(formula if formula is not None else boxes[-1]), run_time=0.65)
                used += 0.65
                hold_voiceover(tracker, used)

        elif scene_type == "comparison_scene" and len(labels) >= 2:
            left = mn.RoundedRectangle(width=3.65, height=2.35, corner_radius=0.2, color=mn.BLUE_C).set_fill("#172554", opacity=0.88).shift(mn.LEFT * 2.25 + mn.DOWN * 0.2)
            right = mn.RoundedRectangle(width=3.65, height=2.35, corner_radius=0.2, color=mn.ORANGE).set_fill("#431407", opacity=0.84).shift(mn.RIGHT * 2.25 + mn.DOWN * 0.2)
            lt = fit_text(labels[0], 26, mn.WHITE, 3.0).move_to(left)
            rt = fit_text(labels[1], 26, mn.WHITE, 3.0).move_to(right)
            takeaway = fit_text(labels[2], 23, mn.GREEN_C, 10.0).to_edge(mn.DOWN, buff=0.6) if len(labels) > 2 else None
            with self.voiceover(text=narration) as tracker:
                self.play(mn.FadeIn(left, shift=mn.LEFT * 0.15), mn.Write(lt), run_time=0.85)
                self.play(mn.FadeIn(right, shift=mn.RIGHT * 0.15), mn.Write(rt), run_time=0.85)
                if takeaway is not None:
                    self.play(mn.FadeIn(takeaway, shift=mn.UP * 0.1), run_time=0.65)
                self.play(mn.Indicate(formula if formula is not None else right), run_time=0.65)
                hold_voiceover(tracker, 3.0)

        else:
            # Simple concept layout. Internal production directions are never displayed.
            main_text = subtitle_text or learner_question
            main = fit_text(main_text, 29, mn.BLUE_B, 10.2).next_to(content_top, mn.DOWN, buff=0.42) if main_text else None

            if key_points:
                anchor = main if main is not None else content_top
                point_font = 24 if len(key_points) <= 3 else 21
                cards = mn.VGroup()
                colors = [mn.BLUE_C, mn.GREEN_C, mn.ORANGE, mn.PURPLE_C, mn.TEAL_C]
                for index, point in enumerate(key_points[:5]):
                    card = mn.RoundedRectangle(
                        width=10.4,
                        height=0.82,
                        corner_radius=0.16,
                        color=colors[index % len(colors)],
                    )
                    card.set_fill("#1e293b", opacity=0.92)
                    dot = mn.Dot(radius=0.075, color=colors[index % len(colors)])
                    text_mob = fit_text(point, point_font, mn.WHITE, 8.9)
                    content = mn.VGroup(dot, text_mob).arrange(mn.RIGHT, buff=0.24)
                    content.move_to(card.get_center()).align_to(card, mn.LEFT).shift(mn.RIGHT * 0.35)
                    cards.add(mn.VGroup(card, content))
                cards.arrange(mn.DOWN, buff=0.18).next_to(anchor, mn.DOWN, buff=0.38)
                if cards.height > 4.45:
                    cards.scale_to_fit_height(4.45)
                if cards.get_bottom()[1] < -3.2:
                    cards.shift(mn.UP * (-3.2 - cards.get_bottom()[1]))

                with self.voiceover(text=narration) as tracker:
                    used = 0.4
                    if main is not None:
                        self.play(mn.FadeIn(main, shift=mn.UP * 0.12), run_time=0.65)
                        used += 0.65
                    self.play(
                        mn.LaggedStart(
                            *[mn.FadeIn(card, shift=mn.RIGHT * 0.18) for card in cards],
                            lag_ratio=0.16,
                        ),
                        run_time=max(1.0, 0.42 * len(cards)),
                    )
                    used += max(1.0, 0.42 * len(cards))
                    for card in cards:
                        self.play(mn.Indicate(card[0], scale_factor=1.015), run_time=0.35)
                        used += 0.35
                    hold_voiceover(tracker, used)
            else:
                label_mobs = mn.VGroup(*[
                    fit_text(item, 22, mn.WHITE, 3.0).set_z_index(2)
                    for item in labels[:3]
                ])
                pills = mn.VGroup()
                for mob in label_mobs:
                    pill = mn.RoundedRectangle(width=max(2.2, mob.width + 0.45), height=0.72, corner_radius=0.16, color=mn.BLUE_C)
                    pill.set_fill("#1e293b", opacity=0.9).move_to(mob)
                    pills.add(pill)
                if len(label_mobs):
                    groups = mn.VGroup(*[mn.VGroup(pills[i], label_mobs[i]) for i in range(len(label_mobs))])
                    groups.arrange(mn.RIGHT, buff=0.35).move_to(mn.DOWN * 0.45)
                with self.voiceover(text=narration) as tracker:
                    used = 0.4
                    if main is not None:
                        self.play(mn.FadeIn(main, shift=mn.UP * 0.12), run_time=0.7)
                        used += 0.7
                    if len(label_mobs):
                        self.play(mn.LaggedStart(*[mn.FadeIn(group) for group in groups], lag_ratio=0.14), run_time=1.05)
                        used += 1.05
                    target = formula if formula is not None else (main if main is not None else header)
                    self.play(mn.Indicate(target), run_time=0.65)
                    used += 0.65
                    hold_voiceover(tracker, used)

        clean_out(bg)
'''.strip() + "\n"
    return template.replace("__SCENE_JSON__", scene_literal)


def build_concept_fallback_scene_code(scene: dict[str, Any]) -> str:
    """Create a deterministic animated fallback for a failed optional custom scene.

    A failed creative visual must never collapse into a heading-only slide. Existing learner
    content is preserved, then concise cards are added until at least two visible ideas exist.
    """
    if str(scene.get("code_snippet") or "").strip():
        return build_code_snippet_scene_code(scene)
    safe_scene = dict(scene)
    safe_scene["type"] = "concept_scene"
    safe_scene["visual_mode"] = "diagram"
    safe_scene.pop("manim_body", None)
    safe_scene.pop("manim_body_ref", None)
    safe_scene.pop("manim_script", None)
    safe_scene.pop("manim_script_ref", None)
    safe_scene.pop("requires_3d", None)
    safe_scene.pop("code_goal", None)

    # Ordered steps and formulas already have strong deterministic renderers. Otherwise force
    # at least two animated key-point cards, using only content the model already supplied.
    has_steps = bool([
        value
        for value in (safe_scene.get("steps") or safe_scene.get("calculation_steps") or [])
        if str(value).strip()
    ])
    has_formula = bool(str(safe_scene.get("formula") or "").strip())
    if not has_steps and not has_formula:
        points: list[str] = []
        for source in (safe_scene.get("key_points") or [], safe_scene.get("labels") or []):
            for value in source:
                text = str(value or "").strip()
                if text and text.lower() not in {item.lower() for item in points}:
                    points.append(text)
        for value in _derive_display_points(safe_scene.get("narration"), limit=4):
            if value.lower() not in {item.lower() for item in points}:
                points.append(value)
            if len(points) >= 3:
                break
        if len(points) < 2:
            question = str(safe_scene.get("learner_question") or safe_scene.get("subtitle") or "").strip()
            if question and question.lower() not in {item.lower() for item in points}:
                points.append(question)
        if len(points) < 2:
            topic = str(safe_scene.get("title") or "this idea").strip()
            points.append(f"See how the parts of {topic} connect")
        safe_scene["key_points"] = points[:4]

    return build_component_scene_code(safe_scene)


def build_custom_scene_code(scene: dict[str, Any], body_code: str) -> str:
    """Wrap legacy body-only custom code in a stable VoiceoverScene shell.

    New generations use complete MANIM_SCRIPT files. This wrapper remains so older saved
    structured bundles can be opened, edited, and migrated without losing their custom scene.
    """
    scene_literal = _safe_python_literal(_scene_for_render(scene))
    body = (body_code or "").strip() or "self.wait(0.1)"
    indented = "\n".join("        " + line if line.strip() else "" for line in body.splitlines())
    template = r'''
import re
import manim as mn
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))
        scene = __SCENE_JSON__
        title = str(scene.get("title") or scene.get("heading") or "")
        narration = str(scene.get("narration") or title or "")
        labels = [str(x) for x in (scene.get("labels") or []) if str(x).strip()][:5]
        key_points = [str(x) for x in (scene.get("key_points") or []) if str(x).strip()][:5]
        visual = str(scene.get("visual") or scene.get("visual_goal") or scene.get("code_goal") or "")
        formula = str(scene.get("formula") or "").replace("\n", " ").strip()
        code_snippet = str(scene.get("code_snippet") or "")
        steps = [str(x).replace("\n", " ").strip() for x in (scene.get("steps") or scene.get("calculation_steps") or []) if str(x).strip()][:6]
        step_narrations = [str(x).replace("\n", " ").strip() for x in (scene.get("step_narrations") or []) if str(x).strip()][:6]
        calculation_steps = steps  # legacy alias for existing saved custom bodies
        learning_role = str(scene.get("learning_role") or "").lower()
        learner_question = str(scene.get("learner_question") or "")
        visual_mode = str(scene.get("visual_mode") or "").lower()
        required_visual_elements = [str(x) for x in (scene.get("required_visual_elements") or []) if str(x).strip()][:6]
        essential_visual = bool(scene.get("essential_visual"))

        def clean_text(text):
            value = str(text or "").replace("\n", " ").strip()
            replacements = {
                "−": "-", "–": "-", "—": "-", "±": "+/-", "×": "*",
                "÷": "/", "·": "*", "√": "sqrt", "²": "^2", "³": "^3",
                "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
                "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
            }
            for source, target in replacements.items():
                value = value.replace(source, target)
            value = value.replace("\\pm", "+/-").replace("\\times", "*")
            value = value.replace("\\cdot", "*").replace("\\left", "").replace("\\right", "")
            value = value.replace("{", "(").replace("}", ")")
            return re.sub(r"\s+", " ", value).strip()

        def safe_label(text, limit=72):
            value = clean_text(text)
            if len(value) > limit:
                value = value[: limit - 3].rstrip() + "..."
            return value

        def label(text, size=26, color=mn.WHITE):
            mob = mn.Text(safe_label(text, 100), font_size=size, color=color)
            if mob.width > 10.8:
                mob.scale_to_fit_width(10.8)
            return mob

        def formula_label(text, size=30, color=mn.YELLOW):
            return label(clean_text(text), size=size, color=color)

        def instruction_step_label(text, size=24, color=mn.WHITE, max_width=10.4):
            mob = label(clean_text(text), size=size, color=color)
            if mob.width > max_width:
                mob.scale_to_fit_width(max_width)
            return mob

        def calculation_step_label(text, size=24, color=mn.WHITE, max_width=10.4):
            return instruction_step_label(
                text, size=size, color=color, max_width=max_width
            )

        def add_instruction_step(
            existing,
            text,
            *,
            position=None,
            size=24,
            color=mn.WHITE,
            run_time=0.8,
            max_width=10.4,
            buff=0.2,
        ):
            group = existing if isinstance(existing, mn.VGroup) else mn.VGroup()
            target = instruction_step_label(
                text, size=size, color=color, max_width=max_width
            )
            group.add(target)
            group.arrange(mn.DOWN, aligned_edge=mn.LEFT, buff=buff)
            group.move_to(mn.DOWN * 0.2 if position is None else position)
            self.play(mn.Write(target), run_time=run_time)
            return group

        def next_calculation_step(
            current,
            text,
            *,
            position=None,
            size=24,
            color=mn.WHITE,
            run_time=0.8,
            max_width=10.4,
        ):
            # Legacy replacement helper retained for older saved custom bodies.
            target = calculation_step_label(
                text, size=size, color=color, max_width=max_width
            )
            target.move_to(mn.UP * 0.15 if position is None else position)
            if current is None:
                self.play(mn.Write(target), run_time=run_time)
            else:
                self.play(mn.ReplacementTransform(current, target), run_time=run_time)
            return target

        def wait_for_voiceover(tracker, used_time):
            duration = float(getattr(tracker, "duration", 0) or 0)
            remaining = max(0.15, duration - float(used_time or 0))
            if remaining > 0.15:
                self.wait(remaining)

        bg = mn.Rectangle(width=mn.config.frame_width, height=mn.config.frame_height)
        bg.set_fill("#0f172a", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

__BODY_CODE__

        leftovers = [m for m in list(self.mobjects) if m is not bg]
        if leftovers:
            self.play(*[mn.FadeOut(m) for m in leftovers], run_time=0.5)
        self.wait(0.1)
'''.lstrip()
    return template.replace("__SCENE_JSON__", scene_literal).replace("__BODY_CODE__", indented)


def build_legacy_custom_scene_code(scene: dict[str, Any], body_code: str) -> str:
    """Explicit alias used by the complete-script orchestrator for older MANIM_BODY bundles."""
    return build_custom_scene_code(scene, body_code)

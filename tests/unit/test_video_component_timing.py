"""Timing invariants for deterministic educational scene components."""

from backend.agent.video_components import build_component_scene_code


def test_step_list_has_no_post_narration_hold():
    code = build_component_scene_code(
        {
            "type": "process_scene",
            "title": "Three steps",
            "narration": "Follow these steps.",
            "steps": ["First item", "Second item", "Third item"],
            "step_narrations": [
                "Start with the first item.",
                "Continue with the second item.",
                "Finish with the third item.",
            ],
        }
    )

    # The voiceover context already waits for narration to finish. An additional fixed hold made
    # list clips uniquely longer than their audio and exposed cumulative subtitle-offset drift at
    # the following scene boundary.
    assert "self.wait(1.5)" not in code
    assert "hold_voiceover(tracker, total_duration)" in code
    assert "clean_out(bg)" in code

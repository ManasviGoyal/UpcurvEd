import json
from typing import Any

from fastmcp import FastMCP

from .quiz_logic import generate_quiz_embedded

app = FastMCP("quiz-mcp-server")


@app.tool()
def generate_embedded_quiz_tool(
    prompt: str, num_questions: int = 5, difficulty: str = "medium"
) -> str:
    """Generate an embedded quiz (no external form).

    Returns JSON string with keys: title, description, questions, count.
    """
    result: dict[str, Any] = generate_quiz_embedded(
        prompt=prompt,
        num_questions=num_questions,
        difficulty=difficulty,
    )
    return json.dumps(result)


@app.tool()
def generate_video_quiz_tool(
    vtt_captions: str,
    num_questions: int = 5,
    difficulty: str = "medium",
    scene_code: str | None = None,
) -> str:
    """Generate a quiz from video captions (VTT content).

    Reuses exact same quiz logic as embedded_quiz.
    Only difference: vtt_captions is passed as the prompt content.

    Args:
        vtt_captions: Text extracted from VTT subtitle file (captions only)
        num_questions: Number of questions to generate (default 5)
        difficulty: Quiz difficulty level (easy, medium, hard)
        scene_code: Optional scene.py code for additional context

    Returns JSON string with keys: title, description, questions, count.
    """
    # Pass VTT captions as prompt directly - reuses all quiz_embedded logic
    result: dict[str, Any] = generate_quiz_embedded(
        prompt=vtt_captions,
        num_questions=num_questions,
        difficulty=difficulty,
        context=scene_code,
    )
    return json.dumps(result)


if __name__ == "__main__":
    app.run()

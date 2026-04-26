import json
from typing import Any

from fastmcp import FastMCP

from .podcast_logic import generate_podcast

app = FastMCP("podcast-mcp-server")


@app.tool()
def generate_podcast_tool(
    prompt: str, provider: str | None = None, model: str | None = None
) -> str:
    """Generate a podcast (mp3 + captions) from an LLM script.

    Returns JSON string with keys: status, job_id, video_url (mp3), srt_url, vtt_url, lang.
    """
    result: dict[str, Any] = generate_podcast(prompt=prompt, provider=provider, model=model)
    return json.dumps(result)


if __name__ == "__main__":
    app.run()

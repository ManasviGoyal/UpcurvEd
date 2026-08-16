"""Native render-stack breakage must be distinguishable from an ordinary render failure."""

import pytest

from backend.utils.diagnostics import diagnostic_category, diagnostic_retryable

# The real preflight stderr: the failing import sits right next to `import manim`, so the
# message contains "manim" and used to be filed as a plain (retryable-looking) render error.
CAIRO_TEE_SYMBOL_ERROR = (
    "Traceback (most recent call last):\n"
    '  File "<string>", line 2, in <module>\n'
    "    import cairo; import manim; import manim_voiceover\n"
    "ImportError: /opt/env/lib/python3.12/site-packages/cairo/"
    "_cairo.cpython-312-x86_64-linux-gnu.so: undefined symbol: cairo_tee_surface_index"
)


@pytest.mark.parametrize(
    "message",
    [
        CAIRO_TEE_SYMBOL_ERROR,
        "ImportError: libcairo.so.2: cannot open shared object file: No such file or directory",
        "ModuleNotFoundError: No module named 'cairo'",
        "symbol lookup error: /usr/lib/libpangocairo-1.0.so.0: undefined symbol: g_once_init",
    ],
)
def test_native_stack_breakage_is_render_runtime(message):
    assert diagnostic_category(message) == "render_runtime"


def test_render_runtime_is_not_retryable():
    # No retry changes the loader's search order, so retrying only wastes an LLM call.
    assert diagnostic_retryable(CAIRO_TEE_SYMBOL_ERROR) is False


def test_ordinary_render_failure_still_classifies_as_render():
    assert diagnostic_category("manim failed to render scene 3") == "render"


def test_unrelated_errors_are_unaffected():
    assert diagnostic_category("ffmpeg concat failed") == "media_export"
    assert diagnostic_category("rate limit exceeded") == "rate_limit"
    assert diagnostic_category("gTTS gave an error") == "voice_synthesis"

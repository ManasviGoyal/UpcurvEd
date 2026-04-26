from backend.runner import job_runner


def test_to_static_url_and_truncate(tmp_path):
    # create a file under STORAGE and verify static mapping
    p = job_runner.STORAGE / "jobs" / "tst" / "f.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("ok")
    assert job_runner.to_static_url(p) == f"/static/{p.relative_to(job_runner.STORAGE)}"

    # _truncate respects limit and returns full when under limit
    assert job_runner._truncate("abcd", limit=10) == "abcd"
    assert job_runner._truncate("abcdefgh", limit=4) == "abcd"
    assert job_runner._truncate(None, limit=4) == ""


def test_inject_watermark_inserts_snippet():
    code = (
        "class MyScene(Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.1)\n"
        "        self.play()\n"
    )
    modified = job_runner._inject_watermark(code)
    # Watermark string from the injection should be present
    assert "Generated using UpcurvEd" in modified
    # Ensure we still have a construct method and watermark init was added
    assert "def construct" in modified
    assert "_watermark_text" in modified


def test_run_job_from_code_returns_manim_not_found_and_cancel_writes_log(tmp_path):
    # Use a deterministic job_id so we can inspect files
    job_id = "unittest01"
    result = job_runner.run_job_from_code(
        "print('hello')\n", scene_name="GeneratedScene", timeout_seconds=1, job_id=job_id
    )
    # If 'manim' CLI is not on PATH, we should get the expected error dict
    assert isinstance(result, dict)
    assert result["job_id"] == job_id
    # Either manim not found or render failed; we at least expect shape
    assert "ok" in result and "status" in result

    # cancel_job for a job with no active process returns not_found and writes cancel.txt
    cancel_result = job_runner.cancel_job(job_id)
    assert cancel_result["status"] in ("not_found", "already_finished", "canceled")
    logs_dir = job_runner.STORAGE / "jobs" / job_id / "logs"
    cancel_file = logs_dir / "cancel.txt"
    # cancel.txt should exist after calling cancel_job
    assert cancel_file.exists()
    content = cancel_file.read_text()
    assert any(s in content for s in ("no active process", "already exited", "canceled"))


def test_cancel_job_when_no_proc_creates_log(tmp_path):
    job_id = "definitely_no_proc"
    # Ensure logs dir exists
    logs_dir = job_runner.STORAGE / "jobs" / job_id / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    res = job_runner.cancel_job(job_id)
    assert res["status"] == "not_found"
    assert (logs_dir / "cancel.txt").read_text() == "no active process"

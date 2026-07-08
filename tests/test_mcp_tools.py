"""Tests for the pure-stdlib MCP tool implementations in wesktop.mcp_tools.

Covers filesystem path guards, git operations against a real temp repo, and the
HTTP-backed tools (ask_user, deployment, review, testing) against a local
http.server bound to an ephemeral port.
"""

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from wesktop.mcp_tools import ask_user, deployment, filesystem, git, review, testing


# --------------------------------------------------------------------------- #
# git tools
# --------------------------------------------------------------------------- #


@pytest.fixture()
def git_repo(tmp_path):
    """A real git repository with one initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env_args = ["-C", str(repo)]
    subprocess.run(["git", *env_args, "init", "-q"], check=True)
    subprocess.run(["git", *env_args, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", *env_args, "config", "user.name", "Tester"], check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", *env_args, "add", "a.txt"], check=True)
    subprocess.run(["git", *env_args, "commit", "-q", "-m", "initial"], check=True)
    return repo


def test_git_diff_traversal_guard_blocks_sibling_prefix(tmp_path):
    """A sibling dir sharing the worktree's string prefix must be blocked.

    Regression: the old guard used str.startswith without a separator, so
    worktree '/x/repo' let '../repo2' (-> '/x/repo2') slip through because
    '/x/repo2'.startswith('/x/repo') is True.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "repo2"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret\n")

    result = git.git_diff(str(repo), "../repo2/secret.txt")
    assert result == "Error: path traversal blocked"


def test_git_diff_allows_in_tree_path(git_repo):
    (git_repo / "a.txt").write_text("hello\nworld\n")
    result = git.git_diff(str(git_repo), "a.txt")
    assert "world" in result


def test_git_commit_happy_path(git_repo):
    (git_repo / "b.txt").write_text("new file\n")
    result = git.git_commit(str(git_repo), "add b")
    assert "Error" not in result
    log = git.git_log(str(git_repo))
    assert "add b" in log


def test_git_commit_nothing_to_commit(git_repo):
    result = git.git_commit(str(git_repo), "noop")
    assert "Nothing to commit" in result


def test_git_log_happy_path(git_repo):
    (git_repo / "c.txt").write_text("c\n")
    git.git_commit(str(git_repo), "second commit")
    log = git.git_log(str(git_repo), count=5)
    lines = log.splitlines()
    assert len(lines) == 2
    assert "second commit" in lines[0]
    assert "initial" in lines[1]


def test_git_status_clean(git_repo):
    assert git.git_status(str(git_repo)) == "(clean working tree)"


def test_git_status_dirty(git_repo):
    (git_repo / "a.txt").write_text("changed\n")
    assert "a.txt" in git.git_status(str(git_repo))


# --------------------------------------------------------------------------- #
# filesystem tools
# --------------------------------------------------------------------------- #


def test_guard_path_blocks_sibling_prefix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "repo2").mkdir()
    with pytest.raises(ValueError):
        filesystem._guard_path(repo, "../repo2")


def test_guard_path_allows_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert filesystem._guard_path(repo, ".") == repo.resolve()


def test_edit_file_single_occurrence(tmp_path):
    (tmp_path / "f.txt").write_text("alpha beta\n")
    result = filesystem.edit_file(str(tmp_path), "f.txt", "beta", "gamma")
    assert "Replaced text" in result
    assert (tmp_path / "f.txt").read_text() == "alpha gamma\n"


def test_edit_file_multiple_occurrences_replaces_first_only(tmp_path):
    (tmp_path / "f.txt").write_text("x x x\n")
    result = filesystem.edit_file(str(tmp_path), "f.txt", "x", "y")
    assert "found 3 total" in result
    assert (tmp_path / "f.txt").read_text() == "y x x\n"


def test_edit_file_missing_old_text(tmp_path):
    (tmp_path / "f.txt").write_text("nope\n")
    result = filesystem.edit_file(str(tmp_path), "f.txt", "absent", "z")
    assert result == "Error: old_text not found in file"


def test_search_files_finds_match(tmp_path):
    (tmp_path / "one.txt").write_text("needle here\n")
    (tmp_path / "two.txt").write_text("nothing\n")
    result = filesystem.search_files(str(tmp_path), "needle")
    assert "one.txt" in result
    assert "needle" in result
    # Path is relativized (no absolute worktree prefix).
    assert str(tmp_path.resolve()) not in result


def test_search_files_no_match(tmp_path):
    (tmp_path / "one.txt").write_text("hay\n")
    assert filesystem.search_files(str(tmp_path), "needle") == "No matches found."


def test_read_write_roundtrip(tmp_path):
    filesystem.write_file(str(tmp_path), "sub/f.txt", "content")
    assert filesystem.read_file(str(tmp_path), "sub/f.txt") == "content"


def test_list_files(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    (tmp_path / "d").mkdir()
    out = filesystem.list_files(str(tmp_path))
    assert "d d/" in out
    assert "f f.txt" in out


# --------------------------------------------------------------------------- #
# HTTP-backed tools -- local http.server on an ephemeral port
# --------------------------------------------------------------------------- #


class _RecordingHandler(BaseHTTPRequestHandler):
    """Records requests and replies per the server's script."""

    def log_message(self, *args):  # silence logging
        pass

    def _handle(self, method):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        self.server.requests.append(
            {
                "method": method,
                "path": self.path,
                "headers": dict(self.headers),
                "body": raw.decode("utf-8") if raw else "",
            }
        )
        status, payload = self.server.responder(self, method)
        body = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class _Server:
    """Context-manager wrapper around a threaded HTTPServer on an ephemeral port."""

    def __init__(self, responder):
        self.httpd = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.httpd.requests = []
        self.httpd.responder = responder
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self):
        return self.httpd.requests

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()


# --- deployment --------------------------------------------------------------


def test_stage_branch_quotes_special_chars():
    def responder(handler, method):
        return 200, {"ok": True}

    with _Server(responder) as srv:
        out = deployment.stage_branch(srv.url, "tok", "feat #1?x y", "msg")
        assert '"ok": true' in out
        recorded = srv.requests[0]["path"]
        # Special characters must be percent-encoded, not passed raw.
        assert "#" not in recorded
        assert "?" not in recorded
        assert " " not in recorded
        assert "%23" in recorded  # '#'
        assert "%3F" in recorded  # '?'
        assert "%20" in recorded  # ' '
        assert recorded.startswith("/api/branches/")
        assert recorded.endswith("/pipeline/stage")


def test_stage_branch_sends_auth_and_payload():
    def responder(handler, method):
        return 200, {"ok": True}

    with _Server(responder) as srv:
        deployment.stage_branch(srv.url, "sekret", "b", "hello")
        req = srv.requests[0]
        assert req["method"] == "POST"
        assert req["headers"]["Authorization"] == "Bearer sekret"
        assert json.loads(req["body"]) == {"message": "hello"}


def test_create_prod_pr_path():
    def responder(handler, method):
        return 200, {"ok": True}

    with _Server(responder) as srv:
        deployment.create_prod_pr(srv.url, "tok", "b", "m")
        assert srv.requests[0]["path"] == "/api/branches/b/pipeline/prod"


def test_check_pipeline_get_no_body():
    def responder(handler, method):
        return 200, {"status": "green"}

    with _Server(responder) as srv:
        out = deployment.check_pipeline(srv.url, "tok", "b")
        assert "green" in out
        req = srv.requests[0]
        assert req["method"] == "GET"
        assert req["body"] == ""


def test_deployment_http_error():
    def responder(handler, method):
        return 500, {"error": "boom"}

    with _Server(responder) as srv:
        out = deployment.check_pipeline(srv.url, "tok", "b")
        assert out.startswith("Error: HTTP 500")


def test_deployment_unreachable():
    # Port 1 is not listening.
    out = deployment.check_pipeline("http://127.0.0.1:1", "tok", "b")
    assert out.startswith("Error: could not reach server")


# --- review ------------------------------------------------------------------


def test_post_review_comment_happy():
    def responder(handler, method):
        return 200, {"stored": True}

    with _Server(responder) as srv:
        out = review.post_review_comment(srv.url, "tok", "f.py", 10, "nit")
        assert "stored" in out
        req = srv.requests[0]
        assert req["path"] == "/api/review/comment"
        assert json.loads(req["body"]) == {"file": "f.py", "line": 10, "body": "nit"}


def test_post_review_comment_http_error():
    def responder(handler, method):
        return 403, "denied"

    with _Server(responder) as srv:
        out = review.post_review_comment(srv.url, "tok", "f.py", 1, "x")
        assert out.startswith("Error: HTTP 403")


# --- testing -----------------------------------------------------------------


def test_run_tests_happy():
    def responder(handler, method):
        return 200, {"passed": 5}

    with _Server(responder) as srv:
        out = testing.run_tests(srv.url, "tok", suite="unit", pattern="foo")
        assert "passed" in out
        req = srv.requests[0]
        assert req["path"] == "/api/tests/run"
        assert json.loads(req["body"]) == {"suite": "unit", "pattern": "foo"}


def test_run_tests_empty_payload():
    def responder(handler, method):
        return 200, {"passed": 0}

    with _Server(responder) as srv:
        testing.run_tests(srv.url, "tok")
        assert json.loads(srv.requests[0]["body"]) == {}


def test_run_tests_http_error():
    def responder(handler, method):
        return 500, "kaboom"

    with _Server(responder) as srv:
        out = testing.run_tests(srv.url, "tok")
        assert out.startswith("Error: HTTP 500")


# --- ask_user ----------------------------------------------------------------


def test_ask_user_polls_until_answered():
    state = {"polls": 0}

    def responder(handler, method):
        if method == "POST":
            return 200, {"id": "q1"}
        state["polls"] += 1
        if state["polls"] >= 2:
            return 200, {"status": "answered", "answer": "42"}
        return 200, {"status": "pending"}

    with _Server(responder) as srv:
        # Speed up polling for the test.
        answer = ask_user.ask_user(
            srv.url,
            "tok",
            "sess",
            "branch",
            "role",
            "What is the answer?",
            poll_timeout_seconds=10,
            poll_interval_seconds=0.05,
        )
        assert answer == "42"
        # First request is the POST creating the question.
        assert srv.requests[0]["method"] == "POST"
        assert json.loads(srv.requests[0]["body"])["question"] == "What is the answer?"


def test_ask_user_timeout():
    def responder(handler, method):
        if method == "POST":
            return 200, {"id": "q1"}
        return 200, {"status": "pending"}

    with _Server(responder) as srv:
        answer = ask_user.ask_user(
            srv.url,
            "tok",
            "sess",
            "branch",
            "role",
            "q?",
            poll_timeout_seconds=0.2,
            poll_interval_seconds=0.05,
        )
        assert answer.startswith("Error: timed out")


def test_ask_user_create_error():
    def responder(handler, method):
        return 500, {"error": "no"}

    with _Server(responder) as srv:
        answer = ask_user.ask_user(srv.url, "tok", "sess", "branch", "role", "q?")
        assert answer.startswith("Error creating question")


def test_ask_user_no_id():
    def responder(handler, method):
        return 200, {"notid": True}

    with _Server(responder) as srv:
        answer = ask_user.ask_user(srv.url, "tok", "sess", "branch", "role", "q?")
        assert "no question id" in answer

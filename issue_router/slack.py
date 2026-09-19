"""Optional local Socket Mode adapter. No public HTTP endpoint required."""
import os
import argparse
from functools import partial
import shlex
import threading
import time
from .core import RouterError, route, render
from .github import fetch_issue, parse_url
from .settings import add_routing_arguments, routing_options
from .policies import POLICIES


class RecentRequests:
    """Bounded, in-memory retry deduplication; not a durable job queue."""
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}

    def seen(self, request_id):
        if not request_id:
            return False
        now = time.monotonic()
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if now - v < 300}
            if request_id in self.entries:
                return True
            if len(self.entries) >= 256:
                del self.entries[next(iter(self.entries))]
            self.entries[request_id] = now
            return False


def parse_command(text):
    usage = "Usage: /issue-model ISSUE_URL [" + "|".join(POLICIES) + "]"
    try:
        parts = shlex.split(text)
    except ValueError:
        raise RouterError(usage) from None
    if len(parts) not in (1, 2) or (len(parts) == 2 and parts[1] not in POLICIES):
        raise RouterError(usage)
    url = parts[0]
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].split("|", 1)[0]
    parse_url(url)
    return url, parts[1] if len(parts) == 2 else None


def handle_command(ack, respond, command, *, allowed_users, allowed_repos, gate,
                   fetch=fetch_issue, select=route, team_id=None, recent=None):
    ack()  # Acknowledge before GitHub or Jev network I/O.
    if command.get("user_id") not in allowed_users or (team_id and command.get("team_id") != team_id):
        respond(text="このコマンドの利用が許可されていません。", response_type="ephemeral")
        return
    if not gate.acquire(blocking=False):
        respond(text="評価中です。完了後にもう一度実行してください。", response_type="ephemeral")
        return
    try:
        if recent and recent.seen(command.get("trigger_id")):
            return
        url, policy = parse_command(command.get("text", "").strip())
        issue = fetch(url, allowed_repos=allowed_repos)
        result = select(issue, **({"policy": policy} if policy else {}))
        respond(text=url + "\n" + render(result, slack=True), response_type="ephemeral", replace_original=False)
    except RouterError as exc:
        respond(text=str(exc), response_type="ephemeral")
    except Exception:
        respond(text="評価に失敗しました。接続と設定を確認してください。", response_type="ephemeral")
    finally:
        gate.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run /issue-model using Slack Socket Mode")
    add_routing_arguments(parser)
    args = parser.parse_args(argv)
    try:
        options = routing_options(args)
    except RouterError as exc:
        raise SystemExit(str(exc)) from None
    users = {s.strip() for s in os.getenv("SLACK_ALLOWED_USERS", "").split(",") if s.strip()}
    repos = {s.strip() for s in os.getenv("GITHUB_ALLOWED_REPOS", "").split(",") if s.strip()}
    if not users or not repos:
        raise SystemExit("Set SLACK_ALLOWED_USERS and GITHUB_ALLOWED_REPOS before starting")
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        if not os.getenv(name):
            raise SystemExit(f"Set {name} securely before starting")
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        raise SystemExit("Install the Slack extra: pip install -e '.[slack]'") from None
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    gate = threading.BoundedSemaphore(1)
    recent = RecentRequests()
    team_id = app.client.auth_test()["team_id"]

    @app.command("/issue-model")
    def command_handler(ack, respond, command):
        handle_command(ack, respond, command, allowed_users=users, allowed_repos=repos, gate=gate,
                       select=partial(route, **options), team_id=team_id, recent=recent)

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()

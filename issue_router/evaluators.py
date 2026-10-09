"""Evaluator backends: Jev on TypeSafe, and Clef on Workers AI or a local System One server.
Both speak the same System One request; only URL, credentials, model name and envelope differ."""
import dataclasses
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from .errors import RouterError

EVALUATORS = ("jev", "clef")
CLEF_HOSTS = ("workers-ai", "local")
STAGES = ("assess", "select")  # first call: assessment (classification); second call: selection
LABELS = {"jev": "Jev", "clef": "Clef"}
JEV_URL = "https://api.typesafe.ai/v1/systemone"
WORKERS_AI_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
WORKERS_AI_MODELS = ("clef", "clef-flash")
LOCAL_URL = "http://127.0.0.1:11434/v1/systemone"
# Context window per Clef model (Cloudflare model pages). Clef truncates long state silently; see context_limit.
CLEF_CONTEXT_TOKENS = {"clef": 65536, "clef-flash": 24576}
TIMEOUTS = {"typesafe": 60, "workers-ai": 60, "local": 300}
KEYCHAIN = {"jev": "local.jev.typesafe", "clef": "local.clef.cloudflare"}
ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")
MODEL_TAG = re.compile(r"[A-Za-z0-9._:-]{1,64}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def keychain_secret(service):
    """macOS only; the generic-password item whose account is the login user. Returns None when absent."""
    proc = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-a", getpass.getuser(), "-w"],
        capture_output=True, text=True, timeout=20)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def credential(env_name, service, hint):
    value = os.environ.get(env_name)
    if value:
        return value
    if service and sys.platform == "darwin":
        try:
            value = keychain_secret(service)
        except (OSError, subprocess.TimeoutExpired):
            raise RouterError(f"Keychain unavailable or timed out; set {env_name} securely") from None
        if value:
            return value
    raise RouterError(hint)


def parse_timeout(value, default):
    if value is None or value == "":
        return default
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        raise RouterError("CLEF_TIMEOUT must be an integer number of seconds") from None
    if not 10 <= seconds <= 600:
        raise RouterError("CLEF_TIMEOUT must be between 10 and 600")
    return seconds


def local_url(value):
    try:
        parts = urllib.parse.urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        parts, hostname = None, None
    loopback = hostname in ("127.0.0.1", "localhost", "::1")
    if (parts is None or parts.scheme not in ("http", "https") or not hostname or parts.query
            or parts.fragment or (parts.scheme == "http" and not loopback)):
        raise RouterError("CLEF_URL must be a loopback http URL or an https URL (no query/fragment)")
    return value


def unwrap_workers_ai(payload, label):
    """Workers AI REST wraps the System One response: {"result": {...}, "success": bool, "errors": [...]}.
    Only numeric error codes are surfaced; messages could echo input."""
    if (not isinstance(payload, dict) or payload.get("success") is not True
            or not isinstance(payload.get("result"), dict)):
        errors = payload.get("errors") if isinstance(payload, dict) else None
        codes = sorted({e["code"] for e in (errors if isinstance(errors, list) else [])
                        if isinstance(e, dict) and type(e.get("code")) is int})
        raise RouterError(f"{label} request failed (Cloudflare error codes {codes}); response body omitted")
    return payload["result"]


@dataclasses.dataclass(frozen=True)
class Evaluator:
    name: str              # "jev" | "clef"
    host: str              # "typesafe" | "workers-ai" | "local"
    models: dict           # {"assess": model, "select": model}; route() puts these in each request's "model"
    url_template: str      # Workers AI keeps a {model} placeholder; Jev and local are fixed URLs
    timeout: int
    envelope: bool         # unwrap Workers AI {"result": ...}
    token_env: str | None  # env var holding the bearer token
    keychain: str | None   # Keychain service (macOS) consulted after the env var
    token_required: bool
    context_tokens: dict | None = None  # {model name: tokens}; warn when usage.input_tokens approaches it

    @property
    def label(self):
        return LABELS[self.name]

    def context_limit(self, model):
        """Context window for a request's model, or None when unknown (Jev, unrecognised local tags)."""
        if not self.context_tokens or not isinstance(model, str):
            return None
        return self.context_tokens.get(model.split(":", 1)[0])  # local Ollama tags: "clef-flash:9b" -> clef-flash

    def describe(self):  # goes into the result JSON; never url, account id or secrets
        return {"name": self.name, "host": self.host, "models": dict(self.models)}

    def url_for(self, model):
        if model not in self.models.values():  # only the configured, validated names reach the URL
            raise RouterError("Request model is not one of the configured evaluator models")
        return self.url_template.replace("{model}", model)  # str.replace: a user-supplied local URL may hold braces

    def headers(self):  # resolved per request; the secret is never stored on the object
        headers = {"Content-Type": "application/json"}
        if self.token_required:
            headers["Authorization"] = "Bearer " + credential(
                self.token_env, self.keychain,
                f"Set {self.token_env} securely"
                + (f", or register the {self.keychain} Keychain entry" if self.keychain else ""))
        elif self.token_env and os.environ.get(self.token_env):
            headers["Authorization"] = "Bearer " + os.environ[self.token_env]
        return headers

    def call(self, request):
        url = self.url_for(request.get("model"))
        req = urllib.request.Request(url, data=json.dumps(request).encode(), headers=self.headers())
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RouterError(f"{self.label} HTTP {exc.code}; response body omitted to protect input and credentials") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise RouterError(f"{self.label} network/timeout/JSON error; no recommendation generated") from None
        return unwrap_workers_ai(payload, self.label) if self.envelope else payload


def make_evaluator(name="jev", *, jev_model="jev-latest", clef_host="workers-ai", clef_model="clef",
                   clef_assess_model=None, clef_url=None, account_id=None, timeout=None, environ=None):
    environ = os.environ if environ is None else environ
    if name not in EVALUATORS:
        raise RouterError("ISSUE_MODEL_EVALUATOR must be one of: " + ", ".join(EVALUATORS))
    if name == "jev":
        if not isinstance(jev_model, str) or not jev_model.strip():
            raise RouterError("JEV_MODEL must not be empty")
        return Evaluator("jev", "typesafe", {"assess": jev_model, "select": jev_model}, JEV_URL,
                         TIMEOUTS["typesafe"], False, "TYPESAFE_API_KEY", KEYCHAIN["jev"], True)
    if clef_host not in CLEF_HOSTS:
        raise RouterError("CLEF_HOST must be one of: " + ", ".join(CLEF_HOSTS))
    timeout = parse_timeout(timeout if timeout is not None else environ.get("CLEF_TIMEOUT"), TIMEOUTS[clef_host])
    models = {"assess": clef_assess_model or clef_model, "select": clef_model}  # same model unless tiered
    if clef_host == "workers-ai":
        if any(model not in WORKERS_AI_MODELS for model in models.values()):
            raise RouterError("CLEF_MODEL and CLEF_ASSESS_MODEL must be clef or clef-flash on Workers AI")
        account = account_id or environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
        if not ACCOUNT_ID.fullmatch(account):
            raise RouterError("Set CLOUDFLARE_ACCOUNT_ID (32 hexadecimal characters)")
        template = WORKERS_AI_URL.format(account=account, model="{model}")  # the model is filled per request
        return Evaluator("clef", "workers-ai", models, template, timeout, True,
                         "CLOUDFLARE_API_TOKEN", KEYCHAIN["clef"], True, CLEF_CONTEXT_TOKENS)
    if any(not isinstance(model, str) or not MODEL_TAG.fullmatch(model) for model in models.values()):
        raise RouterError("CLEF_MODEL and CLEF_ASSESS_MODEL must be Ollama-style model tags")
    return Evaluator("clef", "local", models, local_url(clef_url or LOCAL_URL), timeout, False,
                     "CLEF_API_KEY", None, False, CLEF_CONTEXT_TOKENS)


def api_key():
    """Backward-compatible Jev key lookup: TYPESAFE_API_KEY, then the macOS Keychain."""
    return credential("TYPESAFE_API_KEY", KEYCHAIN["jev"],
                      "Set TYPESAFE_API_KEY securely, or register the existing Jev Keychain entry")


def evaluate(request):
    """Backward-compatible Jev call for callers that send a complete request themselves."""
    return make_evaluator("jev", jev_model=request.get("model") or "jev-latest").call(request)

# Clef 対応 設計書（実装着手用）

作成日: 2026-10-06 / 対象: `main` `a97d16f` / 状態: 提案（未実装）

## 1. 結論

- Clef は Cloudflare が 2026-10-01 に公開した判定モデルです。Jev の System One API（`state` + `noul` / `choice` / `score`）と
  同じリクエスト・応答形式を受け付けます。Workers AI でホストされ、重みは Apache-2.0 で公開されています
  （Ollama / vLLM / llama.cpp で自前実行できます）。
- 本プロジェクトでの「Clef 対応」は、**Issue を判定する評価モデルを Jev と Clef から選べるようにすること**です。
  推薦対象（OpenAI / Claude / Grok の実装モデル）のカタログには加えません。Clef は文章もコードも生成しないため、
  実装モデルにはなり得ません。
- 2 段階評価・評価軸・方針・カタログ・結果検証は変更しません。**Jev へ送る本文と Clef へ送る本文は `model` 以外を
  完全に同一に保ちます。** 同じ Issue を両モデルで比較できる状態を維持するためです。
- 変更の中心は、`core.py` に固定されている Jev 依存部分（エンドポイント・認証・モデル名・表示文言）を
  新設の `issue_router/evaluators.py` へ切り出すことです。CLI / macOS アプリ / Slack / Action / iOS / スキルは
  その設定を受け渡すだけにします。
- Clef のホストは 2 種類です。**Workers AI**（Cloudflare へ送信、従量課金）と **local**（Ollama 等、外部送信なし）。
  iOS は v1 では Workers AI のみ対応します。
- `clef`（27B）と `clef-flash`（9B）の**両方に対応**します。評価段階（1 回目の分類）と選定段階（2 回目の選択）で
  別々のモデルを指定でき、既定は両段階とも `clef` です。使い分けの指針は 4.1 節にまとめます（校正前の仮説として扱います）。
- 2 回目の質問で `needs_context` を先頭に置く並び順は**現状維持**です（決定済み。7 章参照）。
- Jev と Clef の間の自動フォールバック・自動切替は行いません。既存の「API 障害時に推薦を捏造しない」
  「自動再試行しない」と同じ方針です。

## 2. Clef の事実関係（設計の前提。すべて出典付き）

| 項目 | Clef | 出典 |
| --- | --- | --- |
| Workers AI モデル ID | `@cf/cloudflare/clef`（27B）、`@cf/cloudflare/clef-flash`（9B） | [changelog] |
| REST URL | `https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/cloudflare/clef` | [clef-model] |
| 認証 | `Authorization: Bearer <Cloudflare API token>`。公式 REST 手順は「Workers AI - Read」と「Workers AI - Edit」の両方を要求 | [rest-api] |
| 本文 `model` | 必須。パターン `^\s*(clef\|clef-flash)\s*$`（Workers AI） | [schema-in] |
| 応答エンベロープ | REST は `{"result": {model, answers, usage}, "success": true, "errors": [], "messages": []}`。Jev は `{model, answers, usage}` を直接返す | [rest-api] [classmethod] |
| 質問数 | 1〜64 / リクエスト。ID は英数字・`_`・`.`・`-`、100 文字以内 | [schema-in] |
| choice の選択肢数 | 2〜255（Jev と同じ上限。カタログの 254 組 + 保留 1 組の制限はそのまま使える） | [schema-in] |
| score の段階 | 2〜10 | [schema-in] |
| コンテキスト | 65,536 トークン。「長い state はモデルのトークン上限に合わせて切り詰められる」（無断切り詰め） | [clef-model] [schema-in] |
| 画像 | 最大 4 枚（PNG/JPEG/WebP、各 4 MiB、合計 8 MiB、本文 13 MiB）。Jev にない拡張 | [schema-in] |
| 応答 `usage` | `input_tokens`, `output_tokens` | [schema-out] |
| 料金 | clef $0.24 / clef-flash $0.09（入力 100 万トークンあたり、出力課金なし）。Jev は $0.042 | [ai-tldr] [classmethod] |
| ローカル実行 | Ollama 0.35.1 以降。`http://localhost:11434/v1/systemone`、`model` は `clef` / `clef-flash`。タグ: `clef:27b`（18GB）、`clef:27b-q8_0`（30GB）、`clef:27b-mlx-bf16`（55GB）、`clef-flash:9b`（約 12GB） | [ollama] [ollama-flash] |
| 重み | Hugging Face `Cloudflare/clef`, `Cloudflare/clef-flash`（Apache-2.0）。`vllm serve Cloudflare/clef` | [hf] |
| 同点時 | 選択肢の並び順で先のものが選ばれる（Jev の同点挙動は非公開） | [orcarouter] |
| confidence | Jev と同じく分布の集中度。正しさの確率ではない | [orcarouter] |

[changelog]: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
[clef-model]: https://developers.cloudflare.com/workers-ai/models/clef/
[rest-api]: https://developers.cloudflare.com/workers-ai/get-started/rest-api/
[schema-in]: https://developers.cloudflare.com/workers-ai/models/clef/schema-input.json
[schema-out]: https://developers.cloudflare.com/workers-ai/models/clef/schema-output.json
[classmethod]: https://dev.classmethod.jp/en/articles/cloudflare-clef-overview/
[ai-tldr]: https://ai-tldr.dev/models/clef/
[ollama]: https://ollama.com/library/clef
[ollama-flash]: https://ollama.com/library/clef-flash
[hf]: https://huggingface.co/Cloudflare/clef
[orcarouter]: https://www.orcarouter.ai/blog/clef-decision-models-release

Jev との差分のうち設計に影響するものは 5 つです。(1) 応答エンベロープ、(2) 認証と URL、(3) state の無断切り詰め、
(4) 同点時の順序依存、(5) 料金。(1)(2) はアダプタで吸収し、(3) は `usage` から検出して警告し、(4)(5) は文書化します。

実装前に TypeSafe 以外の情報源で確認すべき点: Workers AI の API トークンに必要な最小権限（公式手順は Read + Edit と
記載。Read だけで `/ai/run` が通るかは実測で確認し、通れば文書で Read のみを推奨）。

## 3. 範囲

### 対応する

- CLI `issue-model`、macOS アプリ、Slack（プロセス起動時の設定）、GitHub Action、iOS（Workers AI のみ）、
  Codex/Claude スキル（引数の透過と説明文）
- ホスト: Workers AI、local（Ollama / vLLM / llama.cpp の `/v1/systemone`）
- 疎通確認（macOS / iOS の「疎通確認」ボタン）を Clef でも動かす

### 対応しない（今回の範囲外）

- 画像入力（Issue のスクリーンショット）。将来候補
- score 質問、AI Gateway 経由。将来候補（URL の差し替えで対応可能な構造にしておく）
- Jev ↔ Clef の自動フォールバック・自動切替
- Clef 向けの評価軸・方針文の再調整。本設計は「同じ質問を Clef にも投げられる」ところまで。精度の比較と校正は
  実 Issue で別途行う（[architecture.md の精度改善](architecture.md#精度を改善する) の記録項目に `evaluator` を加える）
- iOS からの local ホスト利用（端末から loopback へ届かないため）
- 評価段階だけを実行する高速トリアージ（例: `--assess-only` で `clef-flash` により情報の充足だけを判定し、Issue 作成時に
  ラベルを付ける）。`status` に新しい値が要るため schema の変更とまとめて検討する。将来候補

## 4. 設定インターフェース

| 設定 | 環境変数 | CLI / Slack 起動引数 | Action 入力 | 既定 | 備考 |
| --- | --- | --- | --- | --- | --- |
| 評価モデル | `ISSUE_MODEL_EVALUATOR` | `--evaluator {jev,clef}` | `evaluator` | `jev` | |
| Jev モデル | `JEV_MODEL` | `--jev-model` | `jev-model` | `jev-latest` | 既存。`jev` のときだけ使う |
| Clef ホスト | `CLEF_HOST` | `--clef-host {workers-ai,local}` | `clef-host` | `workers-ai` | Action の `local` は self-hosted runner 向け |
| Clef モデル（選定段階） | `CLEF_MODEL` | `--clef-model` | `clef-model` | `clef` | 2 回目（選定）に使い、評価段階の既定にもなる。workers-ai は `clef` / `clef-flash` のみ。local は Ollama タグ可（`^[A-Za-z0-9._:-]{1,64}$`） |
| Clef モデル（評価段階） | `CLEF_ASSESS_MODEL` | `--clef-assess-model` | `clef-assess-model` | `CLEF_MODEL` と同じ | 1 回目（情報の充足・評価軸・文脈チェック）だけ別モデルにする。段階分け（`clef-flash` → `clef`）に使う。検証規則は `CLEF_MODEL` と同じ |
| local の URL | `CLEF_URL` | `--clef-url` | `clef-url` | `http://127.0.0.1:11434/v1/systemone` | loopback の http、または https だけ許可。query / fragment 不可 |
| タイムアウト | `CLEF_TIMEOUT` | （なし） | （なし） | workers-ai 60 秒 / local 300 秒 | 10〜600 の整数。local は初回のモデル読み込みが遅いため長め |
| Cloudflare アカウント ID | `CLOUDFLARE_ACCOUNT_ID` | （なし。macOS アプリは画面で保存） | `cloudflare-account-id` | なし | `^[0-9a-f]{32}$`。識別子であり秘密ではないが、結果 JSON には入れない |
| Cloudflare API トークン | `CLOUDFLARE_API_TOKEN` | （なし） | `cloudflare-api-token` | なし | 環境変数 → macOS Keychain `local.clef.cloudflare` の順 |
| local の任意キー | `CLEF_API_KEY` | （なし） | （なし） | なし | vLLM 等がキーを要求する場合だけ Bearer に付ける |

- 優先順位は既存どおり CLI 引数 > 環境変数 > 既定。
- Slack コマンドは `/issue-model URL [policy]` のまま。評価モデルはプロセス起動引数で固定します（`--catalog` と同じ扱い）。
  コマンド引数で評価モデルを切り替える機能は付けません（利用者が課金先を切り替えられる面を増やさない）。
- `--evaluator jev` のとき Clef 系の設定は無視し、`--evaluator clef` のとき `--jev-model` は無視します。
- 認証情報は今までどおり **最初の API 呼び出し時に遅延して読みます**（起動時に Keychain を読まない。`--help` やテストが
  キー無しで動く前提を維持）。非秘密の設定（アカウント ID、URL、モデル名）は起動時に検証します。

### 4.1 clef と clef-flash の使い分け（適性マップ）

両モデルは同じ API と同じ上限（64K トークン、255 選択肢、64 質問、画像 4 枚）を持ち、違いは規模・速度・料金です。
公表値は Cloudflare 自社のベンチマークなので、本ツールでの適性は**校正前の仮説**として扱い、合成 Issue と実 Issue で確かめます。

| | clef（27B） | clef-flash（9B） |
| --- | --- | --- |
| 料金（入力 100 万トークン） | $0.24 | $0.09 |
| モデル側の中央値レイテンシ（公表値） | 209 ms | 39 ms（Jev は 524 ms） |
| 分類ベンチ（公表値） | BANKING77 94.2 / CLINC150 97.4（Jev 79.7 / 89.3） | 公式は「低遅延に最適化」と説明。精度の公表値は本設計時点で未確認 |
| ローカル実行のメモリ | 約 18GB（q4）〜55GB（bf16）。32GB 以上を推奨 | 約 12GB。16GB 以上で現実的 |

本ツール内の処理ごとの適性:

| 処理 | 推奨 | 根拠 |
| --- | --- | --- |
| 選定段階（2 回目。方針文を読み分け、最大 16 択から 1 組を選ぶ） | `clef` | 方針ごとの長い指示と候補説明の読み分けが必要。判定の質を優先 |
| 評価段階（1 回目。情報の充足・評価軸・文脈チェックの 2〜5 択 × 9 問） | `clef-flash` でも可 | 短い基準に対する分類で、flash の設計目的（低遅延）に合う。保留（`needs_context`）の判定を速く安く回せる |
| 疎通確認 | 設定中のモデル（段階で違えば両方） | キーだけでなく、そのモデルを使えるかを確かめる |
| Slack の対話利用 | 段階分け（flash → clef）または高速（flash / flash） | 応答待ち時間が体験に直結する |
| ラベル実行の CI で多数の Issue を処理 | 高速（flash / flash） | 料金と速度。保留・暫定が多くても人が後で見直す前提 |
| `max-quality` / `total-cost` など判断の重い方針 | 精度優先（clef / clef） | 方針文の読み分けが結果を左右する |
| 手元の Mac（Ollama） | メモリ 16GB は flash、32GB 以上なら clef | 常駐メモリ |
| 画像付き Issue（将来） | どちらも vision 対応。`clef` を優先 | 公式は両方を multimodal と説明 |

3 つの組み合わせに名前を付け、文書と macOS / iOS のプリセットで使います。CLI と Action には名前を増やさず、2 つのモデル指定で表します。

| 名前 | 評価段階 | 選定段階 | 指定 |
| --- | --- | --- | --- |
| 精度優先（既定） | clef | clef | `--clef-model clef` |
| 高速 | clef-flash | clef-flash | `--clef-model clef-flash` |
| 段階分け | clef-flash | clef | `--clef-model clef --clef-assess-model clef-flash` |

- 既定を精度優先にする理由: 校正前は最も能力の高い構成を基準にし、他の 2 つはそれとの比較で採否を決めるためです。
  段階分けや高速を既定へ昇格させるのは、合成 Issue と実 Issue で同等の判定が得られると確認してからにします。
- 段階分けのとき、1 回目の判定（`assessment`、`missing_context`）は flash のものになり、それを 2 回目の `state` に
  渡す流れは Jev と同じです。どの段階をどのモデルが判定したかは、結果 JSON の `evaluator.models` と
  `jev_calls[].model` で必ず追跡できます。
- local ホストでも同じ 2 つの指定が使えます（例: `--clef-model clef:27b-q8_0 --clef-assess-model clef-flash`）。

## 5. モジュール設計

### 5.1 新設 `issue_router/evaluators.py`

Jev 固定だった `core.py` の `api_key` / `NoRedirect` / `evaluate` をここへ移し、Clef を加えます。
`core.py` には後方互換の薄い再エクスポートだけ残します（`app.py` が `evaluate` を import しているため）。

```python
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

EVALUATORS = ("jev", "clef")
CLEF_HOSTS = ("workers-ai", "local")
STAGES = ("assess", "select")        # 1 回目: 評価（分類）、2 回目: 選定
LABELS = {"jev": "Jev", "clef": "Clef"}
JEV_URL = "https://api.typesafe.ai/v1/systemone"
WORKERS_AI_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
WORKERS_AI_MODELS = ("clef", "clef-flash")
LOCAL_URL = "http://127.0.0.1:11434/v1/systemone"
CLEF_CONTEXT_TOKENS = 65536          # Clef truncates long state silently; see Evaluator.context_tokens
TIMEOUTS = {"typesafe": 60, "workers-ai": 60, "local": 300}
KEYCHAIN = {"jev": "local.jev.typesafe", "clef": "local.clef.cloudflare"}
ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")
MODEL_TAG = re.compile(r"[A-Za-z0-9._:-]{1,64}")


class NoRedirect(urllib.request.HTTPRedirectHandler):   # moved from core.py unchanged
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def keychain_secret(service):
    """macOS only; the generic-password item whose account is the login user. Returns None when absent."""
    ...  # body of today's core.api_key Keychain branch, parameterised by service


def credential(env_name, service, hint):
    value = os.environ.get(env_name)
    if value:
        return value
    if service and sys.platform == "darwin":
        value = keychain_secret(service)
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
    parts = urllib.parse.urlsplit(value)
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment
            or (parts.scheme == "http" and not loopback)):
        raise RouterError("CLEF_URL must be a loopback http URL or an https URL (no query/fragment)")
    return value


def unwrap_workers_ai(payload, label):
    """Workers AI REST wraps the System One response: {"result": {...}, "success": bool, "errors": [...]}.
    Only numeric error codes are surfaced; messages could echo input."""
    if (not isinstance(payload, dict) or payload.get("success") is not True
            or not isinstance(payload.get("result"), dict)):
        errors = payload.get("errors") if isinstance(payload, dict) else None
        codes = sorted({e["code"] for e in errors or [] if isinstance(e, dict) and isinstance(e.get("code"), int)})
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
    context_tokens: int | None = None  # warn when usage.input_tokens approaches this

    @property
    def label(self):
        return LABELS[self.name]

    def describe(self):   # goes into the result JSON; never url, account id or secrets
        return {"name": self.name, "host": self.host, "models": dict(self.models)}

    def url_for(self, model):
        if model not in self.models.values():   # only the configured, validated names reach the URL
            raise RouterError("Request model is not one of the configured evaluator models")
        return self.url_template.replace("{model}", model)   # str.replace: a user-supplied local URL may hold braces

    def headers(self):    # resolved per request; the secret is never stored on the object
        headers = {"Content-Type": "application/json"}
        if self.token_required:
            headers["Authorization"] = "Bearer " + credential(
                self.token_env, self.keychain,
                f"Set {self.token_env} securely" + (f", or register the {self.keychain} Keychain entry" if self.keychain else ""))
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
        if not jev_model.strip():
            raise RouterError("JEV_MODEL must not be empty")
        return Evaluator("jev", "typesafe", {"assess": jev_model, "select": jev_model}, JEV_URL,
                         TIMEOUTS["typesafe"], False, "TYPESAFE_API_KEY", KEYCHAIN["jev"], True)
    if clef_host not in CLEF_HOSTS:
        raise RouterError("CLEF_HOST must be one of: " + ", ".join(CLEF_HOSTS))
    timeout = parse_timeout(timeout if timeout is not None else environ.get("CLEF_TIMEOUT"), TIMEOUTS[clef_host])
    models = {"assess": clef_assess_model or clef_model, "select": clef_model}   # same model unless tiered
    if clef_host == "workers-ai":
        if any(model not in WORKERS_AI_MODELS for model in models.values()):
            raise RouterError("CLEF_MODEL and CLEF_ASSESS_MODEL must be clef or clef-flash on Workers AI")
        account = account_id or environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
        if not ACCOUNT_ID.fullmatch(account):
            raise RouterError("Set CLOUDFLARE_ACCOUNT_ID (32 hexadecimal characters)")
        template = WORKERS_AI_URL.format(account=account, model="{model}")   # the model is filled per request
        return Evaluator("clef", "workers-ai", models, template, timeout, True,
                         "CLOUDFLARE_API_TOKEN", KEYCHAIN["clef"], True, CLEF_CONTEXT_TOKENS)
    if any(not MODEL_TAG.fullmatch(model) for model in models.values()):
        raise RouterError("CLEF_MODEL and CLEF_ASSESS_MODEL must be Ollama-style model tags")
    return Evaluator("clef", "local", models, local_url(clef_url or LOCAL_URL), timeout, False,
                     "CLEF_API_KEY", None, False, CLEF_CONTEXT_TOKENS)
```

設計上の要点:

- **循環 import の回避:** `evaluators.py` は `RouterError` を必要とし、`core.py` は `evaluators.py` を import します。
  `RouterError` を新設の `issue_router/errors.py` へ移し、`core.py` から従来どおり再エクスポートします
  （`from .core import RouterError` と書いている既存コード・テストはそのまま動きます）。
- **リクエスト本文は `route()` が組み立て、`model` も `route()` が段階ごとに `evaluator.models["assess"]` /
  `evaluator.models["select"]` から入れます。** `call()` は `request["model"]` から URL を決めて送るだけです（Workers AI は
  モデルごとに URL が異なるため）。iOS 移植との対応を保つためで、「同じ入力・同じ応答で Python と Swift のリクエストが
  一致する」確認がそのまま使えます。
- **`describe()` に URL を含めません。** Workers AI の URL にはアカウント ID が入るためです。local の URL も結果 JSON には
  入れません（表示テキストにはホスト名だけを出します。5.3 参照）。
- `envelope` は host で決まる固定値です。応答の形から自動判定はしません（検証は厳格に、推測はしない）。
- `local_url` は「秘密情報と Issue 本文は TLS か loopback でしか流さない」という既存方針の延長です。LAN 上の GPU マシンを
  使う場合は https（例: Cloudflare Tunnel や自前の TLS 終端）を要求します。
- エラー文の `Jev HTTP 401` は `{label} HTTP 401` になります。`app.py` の `check_key` の文字列判定（`"HTTP 401" in message`）は
  ラベルに依存していないため、そのまま動きます。

### 5.2 `core.py` の変更

```python
from .evaluators import Evaluator, NoRedirect, api_key, evaluate, make_evaluator   # 再エクスポート（互換）

def route(issue, *, catalog=None, call=None, policy="balanced", evaluator=None, repository=None):
    evaluator = evaluator or make_evaluator("jev")   # credentials are not touched here
    call = call or evaluator.call                    # tests keep injecting fakes through `call`
    ...
    first = call({"model": evaluator.models["assess"], "state": dict(evidence), "questions": questions})
    ...   # 2 回目は evaluator.models["select"]
    result = {
        "schema_version": 1, ...,
        "evaluator": evaluator.describe(),           # 追加（{"name", "host", "models": {"assess", "select"}}）
        ...
        "jev_calls": [],                              # 名前は schema_version 1 のまま維持（6 章）
    }
    if evaluator.name == "clef":
        result["warnings"].append("評価モデルはClefです。評価軸・方針・候補の説明はJevで動作確認したもので、"
                                  "Clefでは未校正です。Jevと同じ結果になる保証はありません。")

    def record(response):   # 1 回目・2 回目の両方で使う
        usage = response.get("usage")
        result["jev_calls"].append({"model": response.get("model"), "usage": usage})
        tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        if (evaluator.context_tokens and isinstance(tokens, int)
                and tokens >= evaluator.context_tokens * 0.9):
            result["warnings"].append("入力が評価モデルのコンテキスト上限に近づいています。Clefは長い入力を黙って"
                                      "切り詰めるため、判定が本文の一部だけに基づいた可能性があります。要約して再評価してください。")
```

- 既存の kwarg `jev_model` は廃止し、`evaluator` に置き換えます。呼び出し元は `settings.routing_options` と
  `app.handle_route` の 2 箇所です。`route(issue, call=FakeJev())` という既存テストの書き方はそのまま動きます。
- `MAX_INPUT_CHARS`（60,000 文字）は変えません。Clef の 64K トークンは Jev の 32K より大きいものの、日本語 60,000 文字は
  トークン換算で上限に近づき得るため、上記の `usage` ベースの警告で「無断切り詰め」を可視化します。
- `validate_catalog` の「254 組 + 保留 1 組」の上限は Clef でも同じ（255 選択肢）なので変更しません。
- 質問数（1 回目 9 問、2 回目 3 問）は Clef の上限 64 の範囲内です。将来の増加に備え、`route()` で
  `len(questions) <= 64` を assert ではなく `RouterError` で検証する 1 行を加えます（Jev にも害はない）。

### 5.3 `render()` の変更

```python
def evaluator_label(result):
    name = (result.get("evaluator") or {}).get("name", "jev")   # 旧 JSON は Jev として表示
    return LABELS.get(name, "Jev")

lines = [f"{label} モデル推薦（暫定）", ""]
...
reason = f"{label}が候補を1つに絞れませんでした" if ... else "情報不足"
...
lines += ["", f"選定を保留しました。{label}が不足と判断した情報:"]
...
info = result.get("evaluator") or {}
host = info.get("host", "typesafe")
models = info.get("models") or {}
shown = models.get("select", "jev-latest")
if models.get("assess") not in (None, shown):
    shown = f"{models['assess']} → {shown}"          # 段階分け: 評価段階 → 選定段階
lines += ["", f"評価モデル: {label} ({host} / {shown}) / 方針: {policy} / カタログ: {catalog_version}"]
```

表示例（Workers AI、段階分け）:

```text
Clef モデル推薦（暫定）

• openai: gpt-6.1-sol / medium (選択確率 61%, confidence 0.72)
  次候補: gpt-6-luna / medium (24%)
...
評価モデル: Clef (workers-ai / clef-flash → clef) / 方針: balanced / カタログ: 2026-09-30.1
評価モデルはClefです。評価軸・方針・候補の説明はJevで動作確認したもので、Clefでは未校正です。Jevと同じ結果になる保証はありません。
```

### 5.4 `settings.py`

```python
def add_routing_arguments(parser):
    parser.add_argument("--catalog", default=os.getenv("ISSUE_MODEL_CATALOG"), help="Custom catalog JSON")
    parser.add_argument("--policy", choices=list(POLICIES), default=os.getenv("ISSUE_MODEL_POLICY", "balanced"))
    parser.add_argument("--evaluator", choices=list(EVALUATORS), default=os.getenv("ISSUE_MODEL_EVALUATOR", "jev"),
                        help="Decision model that judges the issue: Jev (TypeSafe) or Clef (Cloudflare)")
    parser.add_argument("--jev-model", default=os.getenv("JEV_MODEL", "jev-latest"))
    parser.add_argument("--clef-host", choices=list(CLEF_HOSTS), default=os.getenv("CLEF_HOST", "workers-ai"))
    parser.add_argument("--clef-model", default=os.getenv("CLEF_MODEL", "clef"),
                        help="Clef model for the selection stage (and the assessment stage unless overridden)")
    parser.add_argument("--clef-assess-model", default=os.getenv("CLEF_ASSESS_MODEL"),
                        help="Clef model for the assessment stage only, e.g. clef-flash")
    parser.add_argument("--clef-url", default=os.getenv("CLEF_URL"), help="Local System One server (loopback http or https)")


def routing_options(args):
    if args.policy not in POLICIES:
        raise RouterError("ISSUE_MODEL_POLICY must be one of: " + ", ".join(POLICIES))
    evaluator = make_evaluator(args.evaluator, jev_model=args.jev_model, clef_host=args.clef_host,
                               clef_model=args.clef_model, clef_assess_model=args.clef_assess_model,
                               clef_url=args.clef_url)
    return {"catalog": load_catalog(args.catalog), "policy": args.policy, "evaluator": evaluator}
```

`argparse` の `choices` で環境変数の不正値も拒否されます（`ISSUE_MODEL_EVALUATOR=bogus` は `--help` 相当のエラー）。
既存テスト `routing_options(parser.parse_args([]))` はキー無しで動きます（遅延読み込みのため）。

### 5.5 `cli.py` / `slack.py` / `action.py`

- `cli.py`: 説明文を「Jev or Clef selects ...」にする以外は変更なし。`route(issue, **options)` は `evaluator` を受け取ります。
- `slack.py`: `main()` の `routing_options` で評価モデルが決まります。`handle_command` は `select=partial(route, **options)` の
  ままで変更なし。`docs/slack.md` に `--evaluator clef` の起動例を加えます。
- `action.py`: 環境変数から読む項目を増やし、**GitHub 取得より前に** 選んだ評価モデルの秘密が空でないか確かめます
  （Actions には Keychain が無いので、環境変数の有無で正確に判定できます）。

```python
args.evaluator = env.get("ISSUE_MODEL_EVALUATOR") or "jev"
args.clef_host = env.get("CLEF_HOST") or "workers-ai"
args.clef_model = env.get("CLEF_MODEL") or "clef"
args.clef_assess_model = env.get("CLEF_ASSESS_MODEL") or None
args.clef_url = env.get("CLEF_URL") or None
options = routing_options(args)            # account id などの非秘密設定はここで検証される
evaluator = options["evaluator"]
if evaluator.token_required and not env.get(evaluator.token_env):
    raise RouterError(f"{evaluator.token_env} is required when evaluator is {evaluator.name}")
```

`action.yml` の変更:

```yaml
inputs:
  typesafe-api-key:
    description: TypeSafe API key (required when evaluator is jev)
    required: false            # 従来は true。評価モデルごとの必須判定は action.py で行う
  evaluator:
    description: jev (TypeSafe Jev, default) or clef (Cloudflare Clef)
    default: jev
  clef-host:
    description: workers-ai (default) or local (self-hosted runner with a System One server)
    default: workers-ai
  clef-model:
    description: Clef model for the selection stage (clef or clef-flash on Workers AI; any model tag for local)
    default: clef
  clef-assess-model:
    description: Clef model for the assessment stage only (empty = same as clef-model)
    default: ''
  clef-url:
    description: Local System One endpoint for clef-host=local
    default: ''
  cloudflare-account-id:
    description: Cloudflare account ID (required when evaluator is clef on Workers AI); pass a repository variable
    default: ''
  cloudflare-api-token:
    description: Cloudflare API token with Workers AI permission, supplied from an Actions Secret
    default: ''
runs:
  steps:
    - env:
        ISSUE_MODEL_EVALUATOR: ${{ inputs.evaluator }}
        CLEF_HOST: ${{ inputs.clef-host }}
        CLEF_MODEL: ${{ inputs.clef-model }}
        CLEF_ASSESS_MODEL: ${{ inputs.clef-assess-model }}
        CLEF_URL: ${{ inputs.clef-url }}
        CLOUDFLARE_ACCOUNT_ID: ${{ inputs.cloudflare-account-id }}
        CLOUDFLARE_API_TOKEN: ${{ inputs.cloudflare-api-token }}
```

`.github/workflows/recommend.yml`、`integrations/github-actions.yml`、`integrations/github-label.yml` には
`evaluator`（choice: jev / clef）の入力を足し、`cloudflare-api-token: ${{ secrets.CLOUDFLARE_API_TOKEN }}`、
`cloudflare-account-id: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}` を渡します。Secret が未設定なら空文字が渡り、
`action.py` が明確なエラーで止めます。`actionlint` を通すこと。

### 5.6 `app.py`（macOS アプリ）

画面と API の変更点:

| 要素 | 変更 |
| --- | --- |
| 「APIキー」セクション | 先頭に **評価モデル** の選択（Jev（TypeSafe）/ Clef（Cloudflare Workers AI）/ Clef（このMac内のサーバー））を置き、選択に応じて入力欄を切り替える |
| Jev | 既存のまま（Keychain `local.jev.typesafe`） |
| Clef / Workers AI | アカウント ID（テキスト、設定ファイルに保存）、API トークン（password 入力、Keychain `local.clef.cloudflare`）、使い分けのプリセット（精度優先 / 高速 / 段階分け）と、それが埋める 2 つのモデル欄（選定段階・評価段階。4.1 節） |
| Clef / local | URL（既定 `http://127.0.0.1:11434/v1/systemone`）、モデルタグ 2 つ（選定段階は既定 `clef`、評価段階は空なら同じ）。メモリ目安（flash 約 12GB、clef 約 18GB〜）を注記 |
| 疎通確認 | 選択中の評価モデルで `check_connection(evaluator)` を実行。段階でモデルが違えば両方に 1 回ずつ送り、「OK — clef-flash, clef（14:02 確認）」のように表示 |
| 送信先の注意書き | 選択に応じて文言を切り替える（7 章） |
| 「評価中…」 | `Jevで評価中…` → `{label}で評価中…` |

サーバー側:

- 設定の保存先は draft と分け、`~/Library/Application Support/jev-issue-router/settings.json`（0600）にします。
  内容は `evaluator` / `clef_host` / `clef_model` / `clef_assess_model` / `clef_url` / `cloudflare_account_id` の
  非秘密項目だけ。
  トークンは Keychain のみ。「入力をクリア」は draft だけを消し、settings は残します。
- `/api/settings`（GET / POST）を追加。POST は `make_evaluator()` を通して検証してから保存します。
- `/api/key` は `{"service": "jev" | "clef", "key": "..."}` を受け、`save_key(key, service)` で対応する Keychain 項目へ保存。
  `keychain_entry(service)` も service 引数を取るよう一般化。
- `/api/status` は `{"jev": {...}, "clef": {...}, "settings": {...}}` を返す。
- `/api/check` と `/api/route` は保存済み設定から `make_evaluator()` を作り、`check_connection(evaluator)` /
  `route(issue, ..., evaluator=evaluator)` を呼ぶ。
- `check_key(call=evaluate)` は `check_connection(evaluator, call=None)` に改名。固定の小さな質問は共通で、
  Clef でもそのまま使えます。`evaluator.models` の重複を除いた各モデルに 1 回ずつ送り、`{"models": [...], "checked_at"}`
  を返します（精度優先・高速は 1 回、段階分けは 2 回）。

### 5.7 iOS（Swift 移植）

v1 は Jev と Clef / Workers AI。local は非対応（端末から loopback へ届かない。LAN の http は TLS/loopback 方針で不可）。

| ファイル | 変更 |
| --- | --- |
| `Engine/Evaluator.swift`（新設） | `evaluators.py` の定数と `Evaluator` 構造体の移植: `names = ["jev", "clef"]`、`hosts = ["typesafe", "workers-ai"]`、`stages = ["assess", "select"]`、URL テンプレート、`WORKERS_AI_MODELS`、`models` 辞書と `describe` の JSON、`contextTokens` |
| `Engine/JevClient.swift` → `Engine/SystemOneClient.swift` | `init(evaluator:token:)`。`evaluate` は `request["model"]` から URL を決め、`envelope` に応じて `result` を取り出す。エラー文は `label` を使う。`check()` は重複を除いた各モデルに 1 回ずつ |
| `Engine/Router.swift` | `route(issue:catalog:policy:evaluator:evaluate:)`。結果 JSON に `evaluator` を追加、Clef の警告、`usage` 警告。`policyVersion` は据え置き（判定ルールは変わらないため） |
| `Engine/Render.swift` | `label` と `評価モデル:` 行 |
| `Services/Keychain.swift` | `cloudflareService = "local.clef.cloudflare"` を追加 |
| `Services/SettingsStore.swift`（新設） | DraftStore と同じ方式で `evaluator` / `clefModel` / `clefAssessModel` / `cloudflareAccountID` を保存（完全保護ファイル。秘密は含まない） |
| `Views/SettingsView.swift` | 評価モデルの Picker、Cloudflare セクション（アカウント ID、トークン、プリセット「精度優先 / 高速 / 段階分け」とモデル 2 欄、疎通確認、削除） |
| `Views/AppModel.swift` / `ContentView.swift` | 選択中の評価モデルでクライアントを作る。注意書きと「評価中…」の文言をラベルに連動 |
| `tests/test_ios.py` | `Evaluator.swift` に評価モデル名・ホスト名・URL テンプレート・モデル一覧・Keychain サービス名が Python と一致して含まれることを確認。iOS のホストは Python の部分集合であることを確認 |

同じ入力・同じ応答で Python と Swift の結果 JSON（`evaluator` を含む）・リクエスト・表示テキストが一致することを、
Clef / Workers AI の設定でもフェイク応答で確認します（エンベロープ付きの応答を両方に与える）。

### 5.8 スキル（`skills/jev-issue-router`）

- `scripts/route.py` は引数を透過するため変更不要です。
- `SKILL.md` に 1 段落追加: 既定は Jev。利用者が Clef を求めたときだけ `--evaluator clef`、ローカル実行なら
  `--clef-host local` を付ける。速さやコストを求められたら `--clef-model clef-flash`、段階分けなら
  `--clef-assess-model clef-flash`（4.1 節の表を要約して載せる）。Workers AI は Cloudflare へ送信し課金が発生する、
  local は外部送信しない、結果の `evaluator` と「未校正」の警告をそのまま提示する、Jev と Clef の比較を求められたら
  両方を実行して並べる。
- `agents/openai.yaml` の説明は任意で「Jev / Clef」に広げる。

## 6. 結果 JSON の変更

| フィールド | 変更 |
| --- | --- |
| `evaluator` | 追加。`{"name": "jev" \| "clef", "host": "typesafe" \| "workers-ai" \| "local", "models": {"assess": "<1 回目に要求したモデル>", "select": "<2 回目に要求したモデル>"}}`。Jev では両方 `jev-latest` 等の同じ値。URL・アカウント ID・秘密は含めない |
| `jev_calls` | **名前を維持**。内容は従来どおり実際に応答したモデル名（Clef なら `"clef"` 等）と `usage`。名前は `schema_version` 1 の互換性のために残し、文書で「評価モデルの呼び出し記録」と説明する |
| `warnings` | Clef のとき未校正の警告を追加。`usage.input_tokens` が上限の 90% 以上なら切り詰めの警告を追加 |
| `schema_version` | **1 のまま**（追加のみで既存フィールドの意味は不変） |

代替案として `jev_calls` → `evaluator_calls` に改名して `schema_version` を 2 にする案があります。
iOS 移植・`examples/*.json`・スキルの説明・利用先の自動処理すべてに影響するため、今回は採りません。
Clef の採用が定着した時点で、他の破壊的変更とまとめて行うのが妥当です。

## 7. セキュリティ・プライバシー

### 送信先

| 評価モデル / ホスト | Issue 本文・コンテキスト・リポジトリメタデータの送信先 | 認証情報 | 課金 |
| --- | --- | --- | --- |
| Jev / typesafe | TypeSafe（既存） | `TYPESAFE_API_KEY` / Keychain `local.jev.typesafe` | TypeSafe |
| Clef / workers-ai | Cloudflare Workers AI（Cloudflare の利用規約・ログ設定に従う） | `CLOUDFLARE_API_TOKEN` / Keychain `local.clef.cloudflare`、アカウント ID | Cloudflare（clef $0.24 / clef-flash $0.09 per 1M 入力トークン） |
| Clef / local | 指定した loopback（既定）または https の自前サーバー。**外部送信なし**（loopback の場合） | 任意の `CLEF_API_KEY` | なし（自前の計算資源） |

### 守ること（既存方針の適用）

- 秘密情報と本文は **TLS か loopback** でしか送らない。`CLEF_URL` の検証で強制する。HTTP リダイレクトは Clef でも拒否する。
- エラー表示に応答本文を含めない。Workers AI の `errors[].message` も出さず、数値コードだけ出す。
- 結果 JSON・draft・settings・ログにトークンを書かない。アカウント ID も結果 JSON に入れない。
- 評価モデルの自動フォールバックをしない。失敗はそのまま失敗として返す（推薦を捏造しない）。
- Workers AI の API トークンは対象アカウントの Workers AI 権限だけに絞る。公式手順は Read + Edit と記載しているため、
  まず Read のみで動作確認し、通ればそれを推奨として文書化する。
- テストは引き続きフェイクの `call` を使い、Cloudflare にも Ollama にも接続しない。実 API の疎通確認は合成 Issue
  （`examples/issue.json`、`examples/complex-issue.json`）だけで行う。
- Clef の同点時は選択肢の並び順で先が選ばれます。2 回目の質問では `needs_context` を先頭に置いているため、
  **完全な同点のときだけ** 保留側に倒れます。確率は検証済みで表示されるため挙動は見えます。並び順は**現状維持と
  決定済み**です（並び順の変更は Jev へのリクエストも変え、Jev 側の比較基準がずれるため）。`docs/architecture.md` に
  「Clef では完全同点のとき保留になる」と明記します。

### 文書・UI の注意書き

- `README.md` 冒頭の「評価処理は TypeSafe のホスト API で行います」を「評価処理は TypeSafe の Jev、または Cloudflare の
  Clef（Workers AI か手元のサーバー）で行います」に改める。
- macOS / iOS の注意書きは選択中のホストに合わせて 3 通りに切り替える。
- `SECURITY.md` の "Data and credentials" に Clef の送信先と `CLOUDFLARE_API_TOKEN` を追記する。
- `AGENTS.md` の「Jev selects typed choices」「A real Jev evaluation sends data externally」を評価モデル一般の表現に広げ、
  「Clef local は外部送信しないが、テストでは依然としてフェイクを使う」を加える。

## 8. テスト計画

既存テストはすべて緑のまま。新設 `tests/test_evaluators.py` と、各既存テストへの追加:

| 対象 | 確認内容 |
| --- | --- |
| `make_evaluator` | 既定は jev / typesafe / 両段階 jev-latest / `JEV_URL` / envelope なし。workers-ai は `url_for(model)` にアカウント ID とモデルが入り、`clef` と `clef-flash` で URL が変わる。`clef_assess_model` 省略時は両段階が同じ。不正なアカウント ID・モデル名（評価段階も）・ホスト・評価モデル名はネットワーク前に `RouterError`。`url_for` は設定外のモデル名を拒否 |
| `local_url` | loopback の http は許可、`http://10.0.0.5` は拒否、https は許可、query 付きは拒否 |
| `Evaluator.call` | `urllib` をモックし、送信本文に `model` が入ること、Authorization が環境変数から入ること、local でキー未設定なら Authorization が無いこと、HTTP エラーが `Clef HTTP 4xx` で本文を含まないこと |
| `unwrap_workers_ai` | `success: true` で `result` を返す。`success: false` は数値コードだけを含むエラー。`result` 欠落・配列もエラー |
| `route` | `evaluator=clef` + `FakeJev` で `result["evaluator"]` が入ること。Jev 実行と Clef 実行の 2 リクエストが `model` 以外で一致すること。段階分け設定では 1 回目の `model` が `clef-flash`、2 回目が `clef` で、`evaluator.models` と一致すること。`jev_calls` が 2 件のまま。警告に「未校正」が入る。`usage.input_tokens` が 58,983 以上で切り詰め警告が入る |
| `render` | 「Clef モデル推薦（暫定）」「評価モデル: Clef (workers-ai / clef)」、段階分けでは「clef-flash → clef」。`evaluator` の無い旧 JSON は Jev として表示 |
| `check_connection` | 両段階が同じなら 1 回、段階分けなら重複を除いた 2 回送り、入力本文を送らない。失敗はラベル付きの NG 文 |
| `settings` | `--evaluator clef` と `CLOUDFLARE_ACCOUNT_ID` で `options["evaluator"]` が workers-ai。`--clef-assess-model clef-flash` が `models["assess"]` に入る。`ISSUE_MODEL_EVALUATOR=bogus` は拒否 |
| `action` | evaluator=clef で `CLOUDFLARE_API_TOKEN` が空なら fetch 前に `RouterError`。設定済みなら従来どおり出力。`CLEF_ASSESS_MODEL` が渡る。`action.yml` に新入力が存在する（文字列検査） |
| `app` | `/api/settings` の往復（0600、トークンを含まない、不正値は拒否）。`/api/key` が service ごとに Keychain へ保存（`security` はモック）。`check_connection` が Clef のラベルでメッセージを出す。ページ HTML に 3 通りの注意書きが含まれる |
| `slack` | `main()` の引数パーサが `--evaluator clef --clef-host local` を受理する（起動はしない） |
| `ios` | `Evaluator.swift` の定数が Python と一致。`SystemOneClient.swift` に `local.clef.cloudflare` と URL テンプレートがある。Swift ファイルに秘密が無い（既存） |

実 API を使う疎通確認（CI には入れない。利用量が発生）:

```sh
# Workers AI（合成 Issue。入力数千トークンなので 1 円未満）。3 つの組み合わせを同じ Issue で実行する
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
  .venv/bin/issue-model --file examples/issue.json --evaluator clef --format json                                   # 精度優先
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
  .venv/bin/issue-model --file examples/issue.json --evaluator clef --clef-model clef-flash --format json          # 高速
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
  .venv/bin/issue-model --file examples/issue.json --evaluator clef --clef-assess-model clef-flash --format json   # 段階分け
# local（Ollama 0.35.1 以降。clef は 18GB、clef-flash は約 12GB のダウンロード）
ollama pull clef-flash
.venv/bin/issue-model --file examples/issue.json --evaluator clef --clef-host local --clef-model clef-flash
```

結果は `examples/clef-result.md`（精度優先）、`clef-flash-result.md`（高速）、`clef-tiered-result.md`（段階分け）として
Jev の `live-result.md` と並べ、`complex-issue.json` でも同じ 3 通りを記録する案です。4.1 節の適性マップを見直す材料になります。
「疎通確認であり精度のベンチマークではない」という但し書きを既存と同じく付けます。

## 9. ドキュメント更新一覧

| ファイル | 内容 |
| --- | --- |
| `README.md` | 冒頭 3 行目、「まずローカルで試す」に Clef の 1 例、「実装・検証の範囲」に Clef の行、評価モデルの表 |
| `docs/local.md` | 「Jev認証」を「評価モデルと認証」に拡張。Workers AI（アカウント ID、トークンの権限、料金）、Ollama（バージョン、pull、URL、タイムアウト、メモリ目安）、clef と clef-flash の使い分け（4.1 節の表と 3 つの組み合わせ）、共通設定の表に新しい環境変数、よくある問題（Cloudflare 400/401、Ollama 未起動、モデル未 pull、切り詰め警告） |
| `docs/desktop.md` | 評価モデルの選択、Cloudflare のキー保存、注意書き、settings.json の場所 |
| `docs/ios.md` | Clef / Workers AI の設定、local 非対応の理由、Python 版との対応表に `Evaluator.swift` |
| `docs/slack.md` | 起動例 `--evaluator clef`、送信先の注意 |
| `docs/github.md` | 新しい入力、Secret `CLOUDFLARE_API_TOKEN` と変数 `CLOUDFLARE_ACCOUNT_ID`、`typesafe-api-key` が条件付き必須になったこと |
| `docs/architecture.md` | 処理の流れ図の「Jev 1回目 / 2回目」を「評価モデル（Jev / Clef）」に、モジュール表に `evaluators.py`、判定結果の表に `evaluator`、「精度を改善する」の記録項目に評価モデル、公式資料に Clef の 4 リンク |
| `SECURITY.md` / `AGENTS.md` | 7 章のとおり |
| `skills/jev-issue-router/SKILL.md` | 5.8 のとおり |

## 10. 実装順序（PR 分割案）

各 PR で `python -m unittest discover -s tests -v`、`ruff check .`、`actionlint`、`python -m build` を通します。

1. **PR 1: エンジンと CLI** — `errors.py` / `evaluators.py` 新設、`core.py` / `settings.py` / `cli.py` の変更、
   `app.py` / `slack.py` / `action.py` は `route()` の引数変更に追従する最小限、`tests/test_evaluators.py`、
   `docs/local.md` / `docs/architecture.md`。この時点で `issue-model --evaluator clef`（段階別モデル指定を含む）が使えます。
   マージ前に Workers AI で 3 つの組み合わせ、Ollama で 1 回の疎通確認を合成 Issue で行い、結果を `examples/` に追加します。
2. **PR 2: macOS アプリ** — `app.py` の設定画面・settings.json・Keychain 一般化、`tests/test_app.py`、`docs/desktop.md`。
3. **PR 3: Action と Slack** — `action.py` / `action.yml` / ワークフローテンプレート / `recommend.yml`、`slack.py` の文書、
   `tests/test_adapters.py`、`docs/github.md` / `docs/slack.md`。
4. **PR 4: iOS** — `Evaluator.swift` / `SystemOneClient.swift` / 設定画面、`tests/test_ios.py`、`docs/ios.md`。
   シミュレータでのビルド確認まで（実機・実 API は既存どおり任意）。
5. **PR 5: 文書とスキル** — `README.md`、`SECURITY.md`、`AGENTS.md`、`SKILL.md`。

PR 1 と 3 が小さければ 1 つにまとめても構いません。iOS は Xcode が必要なため分けておきます。

## 11. 決定事項と残る論点

### 決定済み（2026-10-06）

| 論点 | 決定 |
| --- | --- |
| Clef のモデル | `clef` と `clef-flash` の両方に対応し、適性に応じて使い分ける（4.1 節）。評価段階と選定段階で別モデルを指定でき、既定は両段階とも `clef`（精度優先）。高速・段階分けは選択肢として提供し、既定への昇格は実 Issue での比較後に判断 |
| `needs_context` の並び順 | 現状維持（先頭）。Clef では完全同点のときだけ保留に倒れることを文書化 |

### 推奨のまま進める（実装者は推奨に従う。変更は利用者の指示があるときだけ）

| 論点 | 推奨 | 代替 |
| --- | --- | --- |
| `jev_calls` の名前 | 維持（schema 1 のまま、`evaluator` を追加） | `evaluator_calls` に改名して schema 2。利用先と iOS に波及 |
| local の LAN ホスト | https のみ許可（loopback 以外の http は拒否） | 明示的な opt-in フラグで http を許可。方針の例外が増えるため非推奨 |
| Slack のコマンド引数で評価モデル切替 | 行わない（起動時固定） | `/issue-model URL policy clef`。課金先を利用者が変えられる面が増える |
| Workers AI のトークン権限 | 実測して最小権限を文書化 | 公式どおり Read + Edit を案内 |
| 疎通確認結果の収録 | `examples/clef-*.md` を 3 つの組み合わせで追加 | 収録せず文書で「未検証」と明記 |

## 12. 参考: Workers AI の呼び出し例（設計どおりの本文）

```sh
curl "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/cloudflare/clef" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"clef","state":{"text":"ping"},
       "questions":{"ok":{"type":"choice","instructions":"Select yes.",
                          "criteria":{"yes":"Always select this.","no":"Never select this."}}}}'
```

```json
{"result": {"model": "clef",
            "answers": {"ok": {"type": "choice", "choice": "yes",
                               "probabilities": {"yes": 0.99, "no": 0.01}, "confidence": 0.98}},
            "usage": {"input_tokens": 41, "output_tokens": 0}},
 "success": true, "errors": [], "messages": []}
```

`unwrap_workers_ai` が `result` を取り出した後は、Jev の応答と同じ形なので `validate_response` をそのまま適用します。
Ollama の `/v1/systemone` はエンベロープ無しで `result` の中身と同じ形を返します。

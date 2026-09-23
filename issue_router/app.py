"""Local desktop app: a loopback-only page over the shared engine. Standard library only."""
import argparse
import datetime as dt
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

from .core import RouterError, evaluate, load_catalog, normalize_issue, render, route
from .github import fetch_issue
from .policies import POLICIES, POLICY_DESCRIPTIONS
from .repo import snapshot

KEYCHAIN_SERVICE = "local.jev.typesafe"
APP_NAME = "Jev Issue Router"
BUNDLE_ID = "local.jev.issue-router"
IDLE_SECONDS = 600
MAX_BODY = 300_000
DRAFT_FIELDS = ("url", "body", "context", "repo", "policy")
KEY_PATTERN = re.compile(r"[\x21-\x7e]{8,512}")

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Jev Issue Router</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark;--bg:#f6f6f4;--card:#fff;--fg:#1d1d1f;--mute:#6b6b70;--line:#d9d9d6;--accent:#2f5fd0}
@media(prefers-color-scheme:dark){:root{--bg:#1c1c1e;--card:#2a2a2d;--fg:#f2f2f2;--mute:#a0a0a6;--line:#3c3c40;--accent:#7da2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,sans-serif}
main{max-width:820px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0 0 4px}
p.sub{color:var(--mute);margin:0 0 20px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
h2{font-size:15px;margin:0 0 10px}label{display:block;font-size:13px;color:var(--mute);margin:10px 0 4px}
input,textarea,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);font:inherit}
textarea{min-height:130px;resize:vertical}.row{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.row>*{flex:1;min-width:160px}.row>button{flex:0 0 auto;min-width:0}
button{padding:8px 16px;border:0;border-radius:7px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer;flex:0 0 auto}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}button:disabled{opacity:.5;cursor:default}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:12px;margin:10px 0 0;font:13px/1.55 ui-monospace,Menlo,monospace}
.note{font-size:13px;color:var(--mute);margin:8px 0 0}.err{color:#d23c3c}
.state{display:flex;gap:8px;align-items:center;margin:6px 0 0;font-size:14px}.state b{font-weight:600;min-width:4.5em}
.dot{width:9px;height:9px;border-radius:50%;background:var(--mute);flex:0 0 auto}.dot.ok{background:#2e9d5b}.dot.ng{background:#d23c3c}.dot.wait{background:#d9a514}
</style></head><body><main>
<h1>Jev Issue Router</h1>
<p class="sub">Issueやタスクに適したモデルと推論設定を、OpenAI・Claude・Grokそれぞれについて選びます。</p>

<section><h2>APIキー</h2>
<div class="state"><span class="dot" id="savedDot"></span><b>保存状態</b><span id="keyState">確認中…</span></div>
<div class="state"><span class="dot" id="pingDot"></span><b>疎通</b><span id="pingState">未確認</span>
<button class="ghost" id="check" type="button" style="margin-left:auto;padding:4px 12px">疎通確認</button></div>
<div class="row"><div><label for="key">TypeSafe APIキー</label>
<input id="key" type="password" autocomplete="off" spellcheck="false" placeholder="貼り付けて保存"></div>
<button id="saveKey">Keychainに保存</button></div>
<p class="note">キーはmacOS Keychainにだけ保存します。ファイルやブラウザには残さず、保存後は画面にも表示しません。
疎通確認は、保存済みのキーでJev APIへごく小さな固定の問い合わせを1回送ります（わずかな利用量が発生。入力内容は送りません）。</p>
</section>

<section><h2>入力</h2>
<label for="url">GitHub Issue URL（任意。指定時はタイトルと本文を gh で取得）</label>
<input id="url" placeholder="https://github.com/OWNER/REPO/issues/123">
<label for="body">タスク・プロンプト（URLを使わない場合）</label>
<textarea id="body" placeholder="例: 設定画面の保存ボタンを「変更を保存」に変更し、画面テストを更新する。"></textarea>
<label for="context">追加コンテキスト（任意）</label>
<textarea id="context" style="min-height:70px" placeholder="対象範囲、完了条件、制約など"></textarea>
<label for="repo">リポジトリのフォルダ（任意。状態を読んで判断材料に加える）</label>
<div class="row"><input id="repo" spellcheck="false" placeholder="/Users/you/dev/your-repo">
<button class="ghost" id="pick" type="button">選択…</button></div>
<p class="note">指定すると、構成・テストやCIの有無・Gitの状態・Issueの語に一致するパスなどのメタデータをJevへ送信します。ファイルの中身は読みません。</p>
<div class="row"><div><label for="policy">方針</label><select id="policy"></select></div>
<button class="ghost" id="clear" type="button">入力をクリア</button><button id="run">評価する</button></div>
<p class="note" id="policyHelp" style="color:var(--fg)"></p>
<p class="note">入力内容はTypeSafeのJev APIへ送信されます。推薦先モデルは実行しません。
入力内容はこのMac内のファイルに自動保存され、次回起動時に復元されます（APIキーと結果は保存しません）。「入力をクリア」で消去できます。</p>
</section>

<section><h2>結果</h2>
<div class="row"><p class="note" id="status" style="flex:1">まだ実行していません。</p>
<button class="ghost" id="toggle" hidden>JSON表示</button><button class="ghost" id="copy" hidden>コピー</button></div>
<pre id="out" hidden></pre></section>
</main><script>
const TOKEN="__TOKEN__",POLICIES=__POLICIES__,DESCRIPTIONS=__DESCRIPTIONS__,$=id=>document.getElementById(id);
let last=null,showJson=false;
async function api(path,data){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-App-Token":TOKEN},body:JSON.stringify(data||{})});return r.json()}
for(const p of POLICIES){const o=document.createElement("option");o.value=o.textContent=p;$("policy").append(o)}
function showPolicy(){$("policyHelp").textContent=$("policy").value+": "+(DESCRIPTIONS[$("policy").value]||"")}
$("policy").addEventListener("change",showPolicy);showPolicy();
function mark(dot,text,cls,msg){$(dot).className="dot "+cls;$(text).textContent=msg;$(text).className=cls=="ng"?"err":""}
async function refreshKey(){const s=await api("/api/status");const at=s.saved_at?"（"+s.saved_at+" 保存）":"";
if(s.env)mark("savedDot","keyState","ok","環境変数 TYPESAFE_API_KEY を使用中（Keychainより優先）"+(s.keychain?"。Keychainにも保存済み"+at:""));
else if(s.keychain)mark("savedDot","keyState","ok","Keychainに保存済み"+at);
else mark("savedDot","keyState","ng","未設定。下に貼り付けて保存してください");
$("check").disabled=!(s.env||s.keychain);return s}
async function checkKey(){$("check").disabled=true;mark("pingDot","pingState","wait","確認中…");
const r=await api("/api/check").catch(()=>({error:"アプリとの通信に失敗しました"}));$("check").disabled=false;
if(r.error)mark("pingDot","pingState","ng",r.error);else mark("pingDot","pingState","ok","OK — Jev APIが応答しました（"+r.model+"、"+r.checked_at+" 確認）")}
$("check").onclick=checkKey;
$("saveKey").onclick=async()=>{const b=$("saveKey");b.disabled=true;const r=await api("/api/key",{key:$("key").value});$("key").value="";b.disabled=false;
if(r.error){mark("savedDot","keyState","ng",r.error);return}
await refreshKey();await checkKey()};
function show(){if(!last)return;$("out").textContent=showJson?JSON.stringify(last.result,null,2):last.text;$("toggle").textContent=showJson?"テキスト表示":"JSON表示"}
$("toggle").onclick=()=>{showJson=!showJson;show()};$("copy").onclick=()=>{const t=$("out").textContent;if(navigator.clipboard)navigator.clipboard.writeText(t).catch(()=>{});else{const r=document.createRange();r.selectNodeContents($("out"));const s=getSelection();s.removeAllRanges();s.addRange(r);document.execCommand("copy")}};
$("run").onclick=async()=>{const b=$("run");b.disabled=true;$("status").className="note";$("status").textContent="Jevで評価中…";
let r;try{r=await api("/api/route",{url:$("url").value,body:$("body").value,context:$("context").value,repo:$("repo").value,policy:$("policy").value})}catch(e){r={error:"アプリとの通信に失敗しました。起動し直してください。"}}
b.disabled=false;if(r.error){$("status").textContent=r.error;$("status").className="note err";return}
last=r;$("status").textContent="status: "+r.result.status;for(const id of["out","toggle","copy"])$(id).hidden=false;show()};
$("pick").onclick=async()=>{const b=$("pick");b.disabled=true;const r=await api("/api/choose-folder").catch(()=>({}));b.disabled=false;
if(r.path){$("repo").value=r.path;saveDraft()}else if(r.error){$("status").textContent=r.error;$("status").className="note err"}};
const FIELDS=__FIELDS__;let saveTimer=null;
function draft(){const d={};for(const f of FIELDS)d[f]=$(f).value;return d}
function saveDraft(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>api("/api/draft",{draft:draft()}).catch(()=>{}),500)}
for(const f of FIELDS){$(f).addEventListener("input",saveDraft);$(f).addEventListener("change",saveDraft)}
$("clear").onclick=()=>{for(const f of FIELDS)$(f).value=f=="policy"?POLICIES[0]:"";showPolicy();saveDraft()};
api("/api/draft").then(r=>{for(const f of FIELDS)if(r.draft&&typeof r.draft[f]=="string"&&(f!="policy"||POLICIES.includes(r.draft[f])))$(f).value=r.draft[f];showPolicy()}).catch(()=>{});
refreshKey();setInterval(()=>api("/api/ping").catch(()=>{}),20000);
</script></body></html>
"""


def keychain_entry():
    """(exists, local save time or None). Reads attributes only, never the secret."""
    if sys.platform != "darwin":
        return False, None
    try:
        proc = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                               "-a", getpass.getuser()], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    if proc.returncode != 0:
        return False, None
    match = re.search(r'"mdat"<timedate>=\S*\s+"(\d{14})Z', proc.stdout)
    if not match:
        return True, None
    saved = dt.datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    return True, saved.astimezone().strftime("%Y-%m-%d %H:%M")


def keychain_has_key():
    return keychain_entry()[0]


def check_key(call=evaluate):
    """One tiny fixed question proves the key is accepted; no user input is sent."""
    request = {"model": os.getenv("JEV_MODEL", "jev-latest"), "state": {"text": "ping"},
               "questions": {"ok": {"type": "choice", "instructions": "Select yes.",
                                    "criteria": {"yes": "Always select this.", "no": "Never select this."}}}}
    try:
        response = call(request)
    except RouterError as exc:
        message = str(exc)
        if "HTTP 401" in message or "HTTP 403" in message:
            raise RouterError("NG — キーが拒否されました（" + message.split(";")[0] + "）。キーとAPI利用権限を確認してください") from None
        if "HTTP 429" in message:
            raise RouterError("NG — キーは届きましたが利用制限中です（Jev HTTP 429）。残高・制限を確認してください") from None
        if "HTTP" in message:
            raise RouterError("NG — Jev APIがエラーを返しました（" + message.split(";")[0] + "）") from None
        if "network" in message:
            raise RouterError("NG — Jev APIに接続できません。ネットワークを確認してください") from None
        raise RouterError("NG — " + message) from None
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise RouterError("NG — Jev APIの応答形式が想定と異なります")
    return {"model": str(response.get("model") or "jev")[:60],
            "checked_at": dt.datetime.now().strftime("%H:%M")}


def save_key(key):
    if sys.platform != "darwin":
        raise RouterError("Keychainへの保存はmacOSのみ対応です。TYPESAFE_API_KEY を設定してください")
    key = key.strip()
    if not KEY_PATTERN.fullmatch(key) or any(char in key for char in "\"'\\"):
        raise RouterError("キーの形式が正しくありません")
    # Pass the secret on stdin, not argv, so it never appears in the process list.
    command = f'add-generic-password -U -s {KEYCHAIN_SERVICE} -a "{getpass.getuser()}" -w "{key}"\n'
    try:
        proc = subprocess.run(["/usr/bin/security", "-i"], input=command, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RouterError("Keychainへの保存に失敗しました") from None
    if proc.returncode != 0 or not keychain_has_key():
        raise RouterError("Keychainへの保存に失敗しました")


def draft_path():
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "jev-issue-router" / "draft.json"


def load_draft(path=None):
    try:
        data = json.loads((path or draft_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {field: data[field] for field in DRAFT_FIELDS if isinstance(data.get(field), str)}


def save_draft(data, path=None):
    """Keep the form inputs for the next launch: owner-only file, never the API key or results."""
    path = path or draft_path()
    draft = {field: data[field] for field in DRAFT_FIELDS
             if isinstance(data, dict) and isinstance(data.get(field), str)}
    if not any(value.strip() for field, value in draft.items() if field != "policy"):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(draft, handle, ensure_ascii=False)
    os.replace(temporary, path)


def choose_folder():
    if sys.platform != "darwin":
        raise RouterError("フォルダ選択はmacOSのみ対応です。パスを入力してください")
    try:
        proc = subprocess.run(["/usr/bin/osascript", "-e", 'POSIX path of (choose folder with prompt '
                               '"リポジトリのフォルダを選択")'], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise RouterError("フォルダを選択できませんでした。パスを入力してください") from None
    return proc.stdout.strip() if proc.returncode == 0 else ""  # non-zero: the user cancelled


def handle_route(data, call_route=route, fetch=fetch_issue, inspect=snapshot):
    policy = data.get("policy") or "balanced"
    if policy not in POLICIES:
        raise RouterError("Unknown policy")
    url, body = str(data.get("url") or "").strip(), str(data.get("body") or "")
    if bool(url) == bool(body.strip()):
        raise RouterError("Issue URLかタスク本文のどちらか一方を入力してください")
    issue = normalize_issue(fetch(url) if url else {"body": body})
    if str(data.get("context") or "").strip():
        issue["context"] = str(data["context"])
        issue = normalize_issue(issue)
    repo = str(data.get("repo") or "").strip()
    repository = inspect(repo, "\n".join(issue.values())) if repo else None
    result = call_route(issue, catalog=load_catalog(os.getenv("ISSUE_MODEL_CATALOG")), policy=policy,
                        jev_model=os.getenv("JEV_MODEL", "jev-latest"), repository=repository)
    return {"result": result, "text": render(result)}


def make_handler(token, state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # no request logging: bodies carry issue text and keys
            pass

        def reply(self, code, body, content_type="application/json"):
            payload = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def local(self):
            # Reject DNS-rebinding and cross-site requests.
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            state["seen"] = time.monotonic()
            if not self.local() or self.path != "/":
                return self.reply(404, {"error": "Not found"})
            page = PAGE.replace("__TOKEN__", token).replace("__POLICIES__", json.dumps(list(POLICIES))) \
                .replace("__FIELDS__", json.dumps(DRAFT_FIELDS)) \
                .replace("__DESCRIPTIONS__", json.dumps(POLICY_DESCRIPTIONS, ensure_ascii=False))
            self.reply(200, page, "text/html")

        def do_POST(self):
            state["seen"] = time.monotonic()
            supplied = self.headers.get("X-App-Token") or ""
            if not self.local() or not secrets.compare_digest(supplied, token):
                return self.reply(403, {"error": "Forbidden"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= MAX_BODY:
                    raise ValueError
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError
                if self.path == "/api/ping":
                    result = {}
                elif self.path == "/api/status":
                    exists, saved_at = keychain_entry()
                    result = {"env": bool(os.environ.get("TYPESAFE_API_KEY")), "keychain": exists,
                              "saved_at": saved_at}
                elif self.path == "/api/check":
                    result = check_key()
                elif self.path == "/api/key":
                    save_key(str(data.get("key") or ""))
                    result = {"ok": True}
                elif self.path == "/api/draft":
                    if "draft" in data:
                        save_draft(data["draft"])
                    result = {"draft": load_draft()}
                elif self.path == "/api/choose-folder":
                    result = {"path": choose_folder()}
                elif self.path == "/api/route":
                    result = handle_route(data)
                else:
                    return self.reply(404, {"error": "Not found"})
            except RouterError as exc:
                return self.reply(200, {"error": str(exc)})
            except (OSError, ValueError):
                return self.reply(200, {"error": "Input/configuration error"})
            self.reply(200, result)

    return Handler


def is_our_bundle(bundle):
    try:
        info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
        if info.get("CFBundleIdentifier") == BUNDLE_ID:
            return True
        proc = subprocess.run(["/usr/bin/osadecompile", str(bundle)], capture_output=True, text=True, timeout=30)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "issue_router.app" in proc.stdout


# JXA applet: starts the local server, shows it in its own WebKit window, stops it on quit.
APPLET = """ObjC.import('Cocoa');
ObjC.import('WebKit');
var app = Application.currentApplication();
app.includeStandardAdditions = true;
var win = null, web = null, pid = '', url = '', ticks = 0, failures = 0;
function startServer() {
  var dir = app.doShellScript('mktemp -d');
  var me = $.NSProcessInfo.processInfo.processIdentifier;
  pid = app.doShellScript(__COMMAND__ + ' --no-browser --url-file ' + dir + '/url --window-pid ' + me +
                          ' >/dev/null 2>&1 & echo $!');
  url = '';
  for (var i = 0; i < 150 && !url; i++) {
    delay(0.1);
    try { url = app.doShellScript('cat ' + dir + '/url'); } catch (e) {}
  }
  return url;
}
function load() {
  web.loadRequest($.NSURLRequest.requestWithURL($.NSURL.URLWithString(url)));
}
function run() {
  if (!startServer()) {
    app.displayAlert('Jev Issue Router', {message: '起動に失敗しました。ターミナルで issue-model-app を実行して確認してください。'});
    app.quit();
    return;
  }
  var rect = $.NSMakeRect(0, 0, 880, 860);
  win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(rect, 15, 2, false);
  web = $.WKWebView.alloc.initWithFrameConfiguration(rect, $.WKWebViewConfiguration.alloc.init);
  load();
  win.setContentView(web);
  win.setTitle($('Jev Issue Router'));
  win.setReleasedWhenClosed(false);
  win.center;
  win.makeKeyAndOrderFront(null);
  $.NSApp.activateIgnoringOtherApps(true);
}
function idle() {
  if (win && !win.isVisible) { app.quit(); return 1; }
  // Every 10 s, make sure the local server still answers; restart it and reload if it is gone.
  if (win && ++ticks % 10 == 0) {
    try { app.doShellScript('/usr/bin/curl -s -o /dev/null --max-time 3 ' + url); failures = 0; }
    catch (e) { failures++; }
    if (failures >= 2) { failures = 0; if (startServer()) load(); }
  }
  return 1;
}
function quit() {
  if (pid) { try { app.doShellScript('kill ' + pid); } catch (e) {} }
  return true;
}
"""


def install_mac_app(directory=None):
    if sys.platform != "darwin":
        raise RouterError("--install-mac-app is macOS only")
    bundle = Path(directory or Path.home() / "Applications") / f"{APP_NAME}.app"
    if bundle.exists():
        if not is_our_bundle(bundle):
            raise RouterError(f"{bundle} exists and was not created by this tool; move it first")
        shutil.rmtree(bundle)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    # Finder starts apps with a minimal PATH; add the usual gh locations for Issue URLs.
    command = ("PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; export PATH; "
               f"{shlex.quote(sys.executable)} -m issue_router.app")
    # A compiled applet has a universal binary. A shell-script executable makes Apple Silicon
    # Macs without Rosetta ask to install it, because its architecture cannot be read.
    try:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "applet.js"
            source.write_text(APPLET.replace("__COMMAND__", json.dumps(command)), encoding="utf-8")
            proc = subprocess.run(["/usr/bin/osacompile", "-l", "JavaScript", "-s", "-o", str(bundle),
                                   str(source)], capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RouterError("Could not create the app (osacompile failed)")
        # Allow the window to load the loopback page, then re-seal the ad-hoc signature.
        plist = bundle / "Contents" / "Info.plist"
        info = plistlib.loads(plist.read_bytes())
        info.update({"CFBundleName": APP_NAME, "CFBundleIdentifier": BUNDLE_ID,
                     "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}})
        plist.write_bytes(plistlib.dumps(info))
        proc = subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
                              capture_output=True, timeout=60)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RouterError("Could not create the app") from None
    if proc.returncode != 0:
        raise RouterError("Could not create the app (codesign failed)")
    return bundle


def process_alive(pid):
    if not pid:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        pass
    return True


def keep_running(last_seen, window_pid, now=None):
    """The app window owns the server's lifetime. macOS pauses the page's timers while the window is
    hidden, so its pings stop; the idle limit therefore applies only to the browser mode."""
    if window_pid:
        return process_alive(window_pid)
    return (time.monotonic() if now is None else now) - last_seen < IDLE_SECONDS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local desktop app for Jev Issue Router")
    parser.add_argument("--install-mac-app", action="store_true",
                        help="Create '~/Applications/Jev Issue Router.app' that launches this app")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL instead of opening it")
    # Used by the macOS app window: where to report the URL, and the window process to follow.
    parser.add_argument("--url-file", help=argparse.SUPPRESS)
    parser.add_argument("--window-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.install_mac_app:
            print(f"Created {install_mac_app()}")
            return 0
    except (RouterError, OSError) as exc:
        print(str(exc) if isinstance(exc, RouterError) else "Could not create the app", file=sys.stderr)
        return 1
    state = {"seen": time.monotonic()}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(secrets.token_urlsafe(32), state))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"{APP_NAME}: {url} (Ctrl+C to quit; stops {IDLE_SECONDS // 60} min after the page closes)")
    if args.url_file:
        Path(args.url_file).write_text(url, encoding="utf-8")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while keep_running(state["seen"], args.window_pid):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

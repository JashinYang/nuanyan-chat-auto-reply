from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import ctypes
import win32api
import win32con
import win32gui
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from urllib.parse import urlparse

from core import APP_DATA_DIR, APP_VERSION, GENDER_TYPES, LOG_PATH, ONLINE_REPLY_ENDPOINT, ONLINE_REPLY_MODEL, RELATIONSHIP_TYPES, VISION_MODEL, AutoReplyWorker, LLMClient, LocalVisionClient, Settings, create_bridge, detect_risk, normalize_reply, start_emergency_hotkey


HOST = "127.0.0.1"
INSTANCE_MUTEX_NAME = "Local\\NuanYanQQAutoReplyAssistant"
ERROR_ALREADY_EXISTS = 183


class ControlServer(ThreadingHTTPServer):
    # A request that is finishing must never keep the desktop process alive.
    daemon_threads = True
    block_on_close = False


class ControlApp:
    def __init__(self):
        self.settings = Settings.load()
        self.worker: AutoReplyWorker | None = None
        self.status = "未运行"
        self.logs: list[str] = []
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(24)
        self.server: ThreadingHTTPServer | None = None
        self.exit_requested = threading.Event()
        self.shutdown_thread: threading.Thread | None = None
        self.window = None
        self.tray_hwnd: int | None = None
        self.tray_thread: threading.Thread | None = None
        self.tray_ready_event = threading.Event()
        self.tray_error = ""
        try:
            if LOG_PATH.exists():
                self.logs = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
        except Exception:
            pass

    def log(self, text: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}"
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-120:]
            try:
                APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
                with LOG_PATH.open("a", encoding="utf-8") as output:
                    output.write(line + "\n")
            except Exception:
                pass

    def set_status(self, text: str) -> None:
        with self.lock:
            self.status = text

    def public_state(self) -> dict:
        with self.lock:
            running = bool(self.worker and self.worker.thread and self.worker.thread.is_alive() and not self.worker.stop_event.is_set())
            model_profiles = {}
            for platform in ("qq", "wechat"):
                model_profiles[platform] = {
                    "provider_mode": "online",
                    "online": self.settings.model_channel(platform, "online"),
                }
            return {
                "version": APP_VERSION,
                "settings": {
                    "platform": self.settings.platform,
                    "provider_mode": self.settings.provider_mode,
                    "target_name": self.settings.target_for_platform(),
                    "platform_targets": {
                        "qq": self.settings.target_for_platform("qq"),
                        "wechat": self.settings.target_for_platform("wechat"),
                    },
                    "model_profiles": model_profiles,
                    "wechat_send_shortcut": self.settings.wechat_send_shortcut,
                    "base_url": self.settings.base_url,
                    "model": self.settings.model,
                    "relationship_notes": self.settings.relationship_notes,
                    "owner_gender": self.settings.owner_gender,
                    "relationship_type": self.settings.relationship_type,
                    "platform_relationships": {
                        "qq": self.settings.relationship_for_platform("qq"),
                        "wechat": self.settings.relationship_for_platform("wechat"),
                    },
                    "min_delay_seconds": self.settings.min_delay_seconds,
                    "max_delay_seconds": self.settings.max_delay_seconds,
                    "has_api_key": bool(self.settings.get_api_key(self.settings.platform)),
                },
                "running": running,
                "status": self.status,
                "logs": list(self.logs),
            }

    def update_settings(self, data: dict) -> None:
        if self.worker and self.worker.thread and self.worker.thread.is_alive() and not self.worker.stop_event.is_set():
            raise RuntimeError("自动回复运行中，设置已锁定；请先停止后再修改")
        platform = str(data.get("platform") or "qq").strip().lower()
        if platform not in {"qq", "wechat"}:
            raise ValueError("聊天软件选择无效")
        provider_mode = "online"
        target = str(data.get("target_name") or "").strip()
        base_url = str(data.get("base_url") or "").strip()
        model = str(data.get("model") or "").strip()
        base_url = ONLINE_REPLY_ENDPOINT
        model = ONLINE_REPLY_MODEL
        if not target or not base_url or not model:
            raise ValueError("联系人备注名、接口地址和模型名称不能为空")
        api_key = str(data.get("api_key") or "").strip()
        profiles = data.get("model_profiles")
        profile_key = ""
        if isinstance(profiles, dict):
            selected_profile = profiles.get(platform)
            if isinstance(selected_profile, dict):
                selected_online = selected_profile.get("online")
                if isinstance(selected_online, dict):
                    profile_key = str(selected_online.get("api_key") or "").strip()
        if provider_mode == "online" and not (api_key or profile_key or self.settings.get_api_key(platform)):
            raise ValueError(f"请填写{'微信' if platform == 'wechat' else 'QQ'}在线通道的 API Key")
        try:
            min_delay = max(2, int(data.get("min_delay_seconds", 5)))
            max_delay = max(min_delay, int(data.get("max_delay_seconds", 12)))
        except (TypeError, ValueError) as exc:
            raise ValueError("等待时间必须是整数") from exc
        self.settings.platform = platform
        self.settings.set_target_for_platform(target)
        shortcut = str(data.get("wechat_send_shortcut") or self.settings.wechat_send_shortcut).strip().lower()
        if shortcut not in {"enter", "ctrl_enter"}:
            raise ValueError("微信发送快捷键设置无效")
        self.settings.wechat_send_shortcut = shortcut
        if isinstance(profiles, dict):
            for profile_platform in ("qq", "wechat"):
                profile = profiles.get(profile_platform)
                if not isinstance(profile, dict):
                    continue
                selected_mode = "online"
                for channel in ("online",):
                    config = profile.get(channel)
                    if not isinstance(config, dict):
                        continue
                    channel_base = str(config.get("base_url") or "").strip()
                    channel_model = str(config.get("model") or "").strip()
                    channel_base = ONLINE_REPLY_ENDPOINT
                    channel_model = ONLINE_REPLY_MODEL
                    if not channel_base or not channel_model:
                        raise ValueError("每个模型通道都必须填写接口地址和模型名称")
                    channel_key = str(config.get("api_key") or "").strip()
                    self.settings.set_model_channel(
                        profile_platform, channel, channel_base, channel_model, channel_key
                    )
                setattr(self.settings, f"{profile_platform}_provider_mode", selected_mode)
        self.settings.set_model_channel(platform, provider_mode, base_url, model, api_key)
        self.settings.relationship_notes = str(data.get("relationship_notes") or "").strip()[:1200]
        owner_gender = str(data.get("owner_gender") or self.settings.owner_gender).strip().lower()
        if owner_gender and owner_gender not in GENDER_TYPES:
            raise ValueError("使用者性别选择无效")
        self.settings.owner_gender = owner_gender
        relationship_type = str(
            data.get("relationship_type")
            if "relationship_type" in data
            else self.settings.relationship_for_platform(platform)
        ).strip().lower()
        if relationship_type and relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError("双方关系选择无效")
        self.settings.set_relationship_for_platform(relationship_type, platform)
        self.settings.min_delay_seconds = min_delay
        self.settings.max_delay_seconds = min(max_delay, 120)
        self.settings.save()

    def start(self) -> None:
        if self.worker and self.worker.thread and self.worker.thread.is_alive():
            return
        if self.settings.relationship_for_platform() not in RELATIONSHIP_TYPES:
            raise RuntimeError("开始自动回复前，请先选择你和对方是什么关系")
        if self.settings.owner_gender not in GENDER_TYPES:
            raise RuntimeError("开始自动回复前，请先选择你的性别")
        self.worker = AutoReplyWorker(self.settings, self.log, self.set_status)
        self.worker.start()
        platform_name = "微信" if self.settings.platform == "wechat" else "QQ"
        self.set_tray_title(f"暖言聊天自动回复助手（{platform_name}运行中）")
        self.log(f"已启动 {platform_name} 自动回复 v{APP_VERSION}；先结合当前可见历史检查是否需要简短回复，只处理锁定联系人。")

    def stop(self, emergency: bool = False) -> None:
        if self.worker:
            self.worker.stop()
        self.set_status("紧急停止" if emergency else "已停止")
        self.log("已紧急停止所有自动回复。" if emergency else "已停止自动回复。")
        self.set_tray_title("暖言聊天自动回复助手（未运行）")

    def hide_to_tray(self, *args):
        """Keep the process alive when the user closes the desktop window."""
        if self.exit_requested.is_set():
            return None
        if self.window is not None:
            self.window.hide()
        running = bool(self.worker and self.worker.thread and self.worker.thread.is_alive())
        self.set_status("后台自动回复运行中（右下角托盘）" if running else "已隐藏到右下角托盘（自动回复未运行）")
        self.log("主界面已隐藏到右下角托盘；自动回复状态未改变。")
        return False

    def set_tray_title(self, title: str) -> None:
        if self.tray_hwnd:
            try:
                win32gui.Shell_NotifyIcon(
                    win32gui.NIM_MODIFY,
                    (self.tray_hwnd, 1, win32gui.NIF_TIP, 0, 0, title[:127]),
                )
            except Exception:
                pass

    def run_tray(self) -> None:
        try:
            self.log("正在向 Windows 注册右下角托盘图标…")
            tray_message = win32con.WM_USER + 20
            command_show, command_stop, command_exit = 1001, 1002, 1003

            def window_proc(hwnd, message, wparam, lparam):
                if message == tray_message:
                    if lparam == win32con.WM_LBUTTONDBLCLK:
                        self.show_window()
                    elif lparam == win32con.WM_RBUTTONUP:
                        menu = win32gui.CreatePopupMenu()
                        win32gui.AppendMenu(menu, win32con.MF_STRING, command_show, "显示主界面")
                        win32gui.AppendMenu(menu, win32con.MF_STRING, command_stop, "停止自动回复")
                        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
                        win32gui.AppendMenu(menu, win32con.MF_STRING, command_exit, "退出程序")
                        x, y = win32gui.GetCursorPos()
                        win32gui.SetForegroundWindow(hwnd)
                        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
                        win32gui.DestroyMenu(menu)
                    return 0
                if message == win32con.WM_COMMAND:
                    command = wparam & 0xFFFF
                    if command == command_show:
                        self.show_window()
                    elif command == command_stop:
                        self.stop()
                    elif command == command_exit:
                        self.request_exit()
                    return 0
                if message == win32con.WM_CLOSE:
                    win32gui.DestroyWindow(hwnd)
                    return 0
                if message == win32con.WM_DESTROY:
                    try:
                        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 1))
                    finally:
                        win32gui.PostQuitMessage(0)
                    return 0
                return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

            class_name = f"NuanYanTrayWindow_{os.getpid()}"
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = window_proc
            atom = win32gui.RegisterClass(window_class)
            self.tray_hwnd = win32gui.CreateWindow(atom, class_name, 0, 0, 0, 0, 0, 0, 0, window_class.hInstance, None)
            icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app.ico"
            icon = win32gui.LoadImage(
                0, str(icon_path), win32con.IMAGE_ICON, 0, 0,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
            )
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD,
                (self.tray_hwnd, 1, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                 tray_message, icon, "暖言聊天自动回复助手（未运行）"),
            )
            self.tray_ready_event.set()
            self.log("右下角托盘图标已成功注册；双击图标可显示主界面。")
            win32gui.PumpMessages()
        except BaseException as exc:
            self.tray_error = f"{type(exc).__name__}: {exc}"
            self.tray_ready_event.set()
            self.log(f"托盘图标初始化失败：{self.tray_error}")

    def show_window(self, *args) -> None:
        if self.window is not None:
            self.window.show()
            self.window.restore()

    def request_exit(self, destroy_window: bool = True) -> None:
        """Stop work and wake serve_forever so main can finish the process."""
        if self.exit_requested.is_set():
            return
        self.exit_requested.set()
        self.stop()
        self.set_status("正在退出后台程序…")
        self.log("已收到退出指令，正在关闭后台程序。")
        if self.tray_hwnd:
            try:
                win32gui.PostMessage(self.tray_hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        server = self.server
        if server is not None:
            self.shutdown_thread = threading.Thread(
                target=server.shutdown,
                name="control-server-shutdown",
                daemon=True,
            )
            self.shutdown_thread.start()
        window = self.window
        if destroy_window and window is not None:
            try:
                window.destroy()
            except Exception:
                pass


APP = ControlApp()


HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>暖言聊天自动回复助手</title><style>
:root{--bg:#fff8f7;--ink:#33272a;--muted:#806c70;--rose:#df5671;--rose2:#b83954;--line:#eedde0}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#ffe2e7,transparent 28%),var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif}.wrap{max-width:940px;margin:auto;padding:30px 18px 60px}h1{font-size:35px;margin:6px 0 4px;letter-spacing:-1px}.sub{color:var(--muted);margin:0 0 20px}.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}.card{background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 14px 40px rgba(100,45,58,.07)}label{display:block;font-weight:700;margin:12px 0 5px}.hint{font-size:12px;color:var(--muted);font-weight:400}input,select,textarea{width:100%;border:1px solid #dbc8cc;border-radius:11px;padding:10px 11px;font:inherit;background:#fffdfd;color:var(--ink);outline:0}input:focus,select:focus,textarea:focus{border-color:var(--rose);box-shadow:0 0 0 3px #ffe4e9}input:read-only,textarea:read-only{background:#f3eeee;color:#76686b;border-color:#e2d7d9;cursor:not-allowed}textarea{height:85px;resize:vertical}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.buttons{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}button{border:1px solid #dbc8cc;background:white;color:var(--ink);border-radius:11px;padding:9px 13px;font-weight:700;cursor:pointer}button:hover{border-color:var(--rose)}button.primary{background:linear-gradient(135deg,var(--rose),var(--rose2));border:0;color:#fff}button.stop{color:#a32b42}button:disabled{opacity:.48;cursor:wait}.status{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:13px;margin-bottom:12px}.dot{width:10px;height:10px;border-radius:99px;background:#aaa;display:inline-block;margin-right:8px}.dot.on{background:#2ba875;box-shadow:0 0 0 5px #dcf5ea}.log{white-space:pre-wrap;background:#fffafa;border:1px solid var(--line);border-radius:12px;padding:12px;height:415px;overflow:auto;font:13px/1.6 ui-monospace,"Microsoft YaHei",monospace}.notice{font-size:13px;color:var(--muted);margin-top:13px;padding:10px;border-radius:10px;background:#fff7ec}.toast{position:fixed;right:18px;bottom:18px;padding:12px 16px;border-radius:12px;background:#302426;color:#fff;opacity:0;transform:translateY(12px);transition:.2s;pointer-events:none}.toast.show{opacity:1;transform:none}@media(max-width:760px){.grid{grid-template-columns:1fr}.log{height:260px}}
</style></head><body><div class="wrap"><h1>暖言聊天自动回复助手</h1><p class="sub">v__VERSION__ · QQ / 微信按选择运行 · 指定联系人精确锁定 · Ctrl+Alt+Q 紧急停止</p><div class="notice">本项目为独立第三方工具，不属于腾讯官方产品，与腾讯、QQ、微信不存在隶属、合作或认可关系。QQ、微信、WeChat 等名称仅用于描述兼容性，商标归相应权利人所有。请遵守平台规则；自动化可能导致功能限制或账号风控。</div><div class="grid"><section class="card">
<label>聊天软件</label><select id="platform"><option value="qq">QQ</option><option value="wechat">微信（实验模式）</option></select>
<label>你的性别 <span class="hint">必选，用于保持本人身份一致</span></label><select id="ownerGender"><option value="">请选择性别</option><option value="male">男性</option><option value="female">女性</option><option value="unspecified">其他或不愿说明</option></select>
<label><span id="targetPlatform">QQ</span> 联系人备注名 <span class="hint">必须与聊天窗口顶部完全一致</span></label><input id="target">
<label>你和对方的关系 <span class="hint">必选，开始聊天前用于确定身份和语气</span></label><select id="relationship"><option value="">请选择关系</option><option value="lover">恋人</option><option value="spouse">夫妻</option><option value="family">家人</option><option value="sibling">兄弟姐妹</option><option value="friend">朋友</option><option value="classmate">同学</option><option value="colleague">同事</option><option value="acquaintance">熟人</option><option value="stranger">陌生人</option><option value="other">其他</option></select>
<div id="wechatOptions" style="display:none"><label>微信发送快捷键 <span class="hint">应与微信“快捷键”设置一致；能识别发送按钮时优先点击按钮</span></label><select id="wechatShortcut"><option value="enter">Enter 发送</option><option value="ctrl_enter">Ctrl+Enter 发送</option></select></div>
<label><span id="modelPlatform">QQ</span> 模型通道 <span class="hint">公开版仅提供在线 API</span></label><select id="provider" disabled><option value="online">在线 API</option></select>
<label><span id="channelName">在线</span>接口地址 <span class="hint" id="baseLockHint"></span></label><input id="base" placeholder="https://api.deepseek.com">
<label><span id="channelModelName">在线</span>模型名称 <span class="hint" id="modelLockHint"></span></label><input id="model" placeholder="deepseek-v4-flash">
<label>API Key <span class="hint" id="keyHint">使用 Windows 凭据加密保存</span></label><input id="key" type="password" placeholder="请输入你自己的 API Key">
<div class="row"><div><label>静默缓冲（秒）</label><input id="minDelay" type="number" min="2" max="120"></div><div><label>最长缓冲（秒）</label><input id="maxDelay" type="number" min="2" max="120"></div></div>
<label>关系背景 <span class="hint">可选，只用于调整语气</span></label><textarea id="notes"></textarea>
<div class="buttons"><button id="saveSettings" onclick="save()">保存设置</button><button id="testAI" onclick="testAI()">测试 AI</button><button id="checkVision" onclick="checkVision()">检查视觉模型</button><button id="checkPlatform" onclick="checkSelectedPlatform()">检查 QQ</button><button class="primary" id="start" onclick="startBot()">启动 QQ 自动回复</button><button class="stop" id="stop" onclick="stopBot()">停止</button></div>
<div class="notice" id="platformNotice">运行时请保持电脑版 QQ 登录，并让锁定联系人的聊天窗口处于打开状态。回复所需聊天文字会发送至 DeepSeek 在线 API；API Key 以 Windows DPAPI 加密保存在当前用户账户下。API 账号、费用、输入内容和服务条款由使用者负责。</div></section><section class="card"><div class="status"><b><span class="dot" id="dot"></span><span id="runLabel">未运行</span></b><span id="status">未运行</span></div><div class="notice">关闭此窗口只会隐藏到右下角托盘，自动回复会继续运行。只有点击“彻底退出程序”才会关闭后台。本程序不主动收集遥测。</div><div class="log" id="logs">暂无日志</div><div class="buttons"><button class="stop" onclick="exitApp()">彻底退出程序</button></div></section></div></div><div class="toast" id="toast"></div>
<script>
const TOKEN='__TOKEN__',ONLINE_BASE='__ONLINE_REPLY_ENDPOINT__',ONLINE_MODEL='__ONLINE_REPLY_MODEL__';let initialized=false;let platformTargets={qq:'',wechat:''},platformRelationships={qq:'',wechat:''};let currentPlatform='qq',currentProvider='online';const defaultProfile=()=>({provider_mode:'online',online:{base_url:ONLINE_BASE,model:ONLINE_MODEL,has_api_key:false}});let modelProfiles={qq:defaultProfile(),wechat:defaultProfile()};const $=id=>document.getElementById(id);
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Token':TOKEN},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw new Error(d.error||'操作失败');return d}
function platformName(){return $('platform').value==='wechat'?'微信':'QQ'}
function ensureProfile(platform){if(!modelProfiles[platform])modelProfiles[platform]=defaultProfile();const p=modelProfiles[platform];if(!p.online)p.online=defaultProfile().online;p.provider_mode='online';return p}
function stashCurrent(){platformTargets[currentPlatform]=$('target').value;platformRelationships[currentPlatform]=$('relationship').value;const p=ensureProfile(currentPlatform);const cfg=p.online||{};const pendingKey=$('key').value||cfg.api_key||'';p.provider_mode='online';p.online={base_url:ONLINE_BASE,model:ONLINE_MODEL,has_api_key:!!(pendingKey||cfg.has_api_key),api_key:pendingKey}}
function loadProvider(){const p=ensureProfile(currentPlatform);const cfg=p.online||{};$('provider').value='online';$('base').value=ONLINE_BASE;$('model').value=ONLINE_MODEL;$('base').readOnly=true;$('model').readOnly=true;$('baseLockHint').textContent='系统锁定，只读';$('modelLockHint').textContent='系统锁定，只读';$('key').value=cfg.api_key||'';$('channelName').textContent='在线';$('channelModelName').textContent='在线';$('keyHint').textContent=cfg.has_api_key?'已保存该平台的加密密钥；留空即可保留':'使用 Windows 凭据加密保存';currentProvider='online'}
function syncProvider(){loadProvider()}
function syncPlatform(switching=false){if(switching)stashCurrent();const selected=$('platform').value;currentPlatform=selected;const name=platformName();$('target').value=platformTargets[selected]||'';$('relationship').value=platformRelationships[selected]||'';$('targetPlatform').textContent=name;$('modelPlatform').textContent=name;$('wechatOptions').style.display=selected==='wechat'?'block':'none';loadProvider();$('checkPlatform').textContent='检查 '+name;$('start').textContent='启动 '+name+' 自动回复';$('platformNotice').textContent=(selected==='wechat'?'微信个人号自动化属于实验功能，可能受客户端更新和账号风控影响。':'运行时请保持电脑版 QQ 登录，并让锁定联系人的聊天窗口处于打开状态。')+' 回复所需聊天文字会发送至 DeepSeek 在线 API；API Key、费用、输入内容和服务条款由使用者负责。'}
function values(){stashCurrent();const cfg=ensureProfile(currentPlatform)[currentProvider];return{platform:currentPlatform,owner_gender:$('ownerGender').value,provider_mode:currentProvider,target_name:$('target').value,relationship_type:$('relationship').value,wechat_send_shortcut:$('wechatShortcut').value,base_url:cfg.base_url,model:cfg.model,api_key:cfg.api_key||'',model_profiles:modelProfiles,min_delay_seconds:$('minDelay').value,max_delay_seconds:$('maxDelay').value,relationship_notes:$('notes').value}}
function toast(s){$('toast').textContent=s;$('toast').classList.add('show');setTimeout(()=>$('toast').classList.remove('show'),2600)}
async function save(silent=false){await api('/api/save',values());for(const p of Object.values(modelProfiles)){const cfg=p.online||{};if(cfg.api_key)cfg.has_api_key=true;delete cfg.api_key}$('key').value='';if(!silent)toast('QQ与微信在线模型设置已安全保存')}
async function testAI(){await save(true);toast('正在测试 AI…');const d=await api('/api/test-ai',{});toast(d.message)}
async function checkVision(){toast('正在检查本机视觉模型…');const d=await api('/api/check-vision',{});toast(d.message)}
async function checkSelectedPlatform(){await save(true);toast('正在检查 '+platformName()+'…');const d=await api('/api/check-platform',{});toast(d.message)}
async function startBot(){if(!$('ownerGender').value){toast('请先选择你的性别');$('ownerGender').focus();return}if(!$('relationship').value){toast('请先选择你和对方是什么关系');$('relationship').focus();return}await save(true);await api('/api/start',{});toast(platformName()+'自动回复已启动');refresh()}
async function stopBot(){await api('/api/stop',{});toast('已停止');refresh()}
async function exitApp(){if(!confirm('彻底退出会停止所有自动回复，确定吗？'))return;await api('/api/exit',{});document.body.innerHTML='<div class="wrap"><h1>程序正在退出</h1></div>'}
async function refresh(){try{const d=await api('/api/state');if(!initialized){platformTargets=d.settings.platform_targets||platformTargets;platformRelationships=d.settings.platform_relationships||platformRelationships;modelProfiles=d.settings.model_profiles||modelProfiles;$('platform').value=d.settings.platform||'qq';currentPlatform=$('platform').value;$('ownerGender').value=d.settings.owner_gender||'';$('wechatShortcut').value=d.settings.wechat_send_shortcut||'enter';$('minDelay').value=d.settings.min_delay_seconds;$('maxDelay').value=d.settings.max_delay_seconds;$('notes').value=d.settings.relationship_notes;syncPlatform(false);initialized=true}const locked=d.running;for(const id of ['platform','ownerGender','target','relationship','wechatShortcut','minDelay','maxDelay','notes','saveSettings','testAI','checkVision','checkPlatform'])$(id).disabled=locked;$('provider').disabled=true;$('base').readOnly=true;$('model').readOnly=true;$('key').disabled=locked;$('dot').className='dot'+(locked?' on':'');$('runLabel').textContent=locked?'运行中':'未运行';$('status').textContent=d.status;$('start').disabled=locked;$('stop').disabled=!locked;$('logs').textContent=d.logs.length?d.logs.join('\n\n'):'暂无日志';$('logs').scrollTop=$('logs').scrollHeight}catch(e){}}
$('platform').addEventListener('change',()=>syncPlatform(true));$('provider').addEventListener('change',()=>syncProvider(true));setInterval(refresh,1200);refresh();window.addEventListener('unhandledrejection',e=>toast(e.reason?.message||'操作失败'));
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-App-Token", "") == APP.token

    def _body(self) -> dict:
        length = min(int(self.headers.get("Content-Length", "0")), 20_000)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = (
                HTML.replace("__TOKEN__", APP.token)
                .replace("__VERSION__", APP_VERSION)
                .replace("__VISION_MODEL__", VISION_MODEL)
                .replace("__ONLINE_REPLY_ENDPOINT__", ONLINE_REPLY_ENDPOINT)
                .replace("__ONLINE_REPLY_MODEL__", ONLINE_REPLY_MODEL)
                .encode("utf-8")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/health":
            self._json({"ok": True})
        elif path == "/api/state" and self._authorized():
            self._json(APP.public_state())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            data = self._body()
            path = urlparse(self.path).path
            if path == "/api/save":
                APP.update_settings(data)
                self._json({"ok": True})
            elif path == "/api/test-ai":
                reply = LLMClient(APP.settings).test()
                self._json({"ok": True, "message": reply})
            elif path in {"/api/check-platform", "/api/check-qq"}:
                import uiautomation as auto
                with auto.UIAutomationInitializerInThread():
                    bridge = create_bridge(APP.settings)
                    bridge.open_target()
                    count = len(bridge.read_messages())
                self._json({
                    "ok": True,
                    "message": f"已锁定{bridge.platform_name}联系人，读取到 {count} 个当前可见消息项。模式：{bridge.read_mode}。",
                })
            elif path == "/api/check-vision":
                LocalVisionClient().ensure_available()
                self._json({"ok": True, "message": f"本机视觉模型 {VISION_MODEL} 已就绪。"})
            elif path == "/api/start":
                APP.start()
                self._json({"ok": True})
            elif path == "/api/stop":
                APP.stop()
                self._json({"ok": True})
            elif path == "/api/exit":
                self._json({"ok": True})
                APP.request_exit()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 400)

    def log_message(self, format, *args):
        return


def find_port() -> int:
    for port in range(8766, 8786):
        with socket() as probe:
            try:
                probe.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("无法找到可用的本机端口")


def acquire_instance_mutex():
    """Return a Windows mutex handle, or None when another copy owns it."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    create_mutex.restype = ctypes.c_void_p
    handle = create_mutex(None, True, INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def close_instance_mutex(handle) -> None:
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def packaged_self_test() -> None:
    import webview

    assert webview is not None and win32gui is not None
    assert "人身安全" in detect_risk("我不想活了")
    assert normalize_reply('回复："我在这里。"') == "我在这里。"
    probe = Settings()
    assert probe.provider_mode_for_platform("qq") == "online"
    assert probe.model_channel("wechat")["base_url"] == ONLINE_REPLY_ENDPOINT
    assert probe.model_channel("qq")["model"] == ONLINE_REPLY_MODEL
    assert APP_DATA_DIR.name == "暖言聊天助手公开版"
    assert not probe.get_api_key("qq")
    probe.set_api_key("packaged-test")
    assert probe.get_api_key() == "packaged-test"


def main():
    if "--self-test" in sys.argv or os.environ.get("NUANYAN_SELF_TEST") == "1":
        packaged_self_test()
        os._exit(0)
    mutex_handle = acquire_instance_mutex()
    if mutex_handle is None:
        if os.environ.get("NUANYAN_NO_BROWSER") != "1":
            ctypes.windll.user32.MessageBoxW(
                None,
                "暖言聊天自动回复助手已经在运行，请使用现有控制页面。",
                "暖言聊天自动回复助手",
                0x00000040,
            )
        return
    port = find_port()
    APP.server = ControlServer((HOST, port), Handler)
    start_emergency_hotkey(lambda: APP.stop(emergency=True))
    url = f"http://{HOST}:{port}/"
    headless = os.environ.get("NUANYAN_NO_BROWSER") == "1"
    server_thread = None
    try:
        if headless:
            APP.server.serve_forever()
        else:
            import webview

            server_thread = threading.Thread(
                target=APP.server.serve_forever,
                name="control-server",
                daemon=True,
            )
            server_thread.start()
            APP.tray_thread = threading.Thread(
                target=APP.run_tray,
                name="system-tray",
                daemon=True,
            )
            APP.tray_thread.start()
            if not APP.tray_ready_event.wait(timeout=8) or APP.tray_error:
                detail = APP.tray_error or "Windows 未在规定时间内完成注册"
                ctypes.windll.user32.MessageBoxW(
                    None,
                    f"系统托盘图标初始化失败，程序不会转入不可见后台。\n\n{detail}",
                    "暖言聊天自动回复助手",
                    0x00000010,
                )
                raise RuntimeError(f"托盘图标初始化失败：{detail}")
            APP.window = webview.create_window(
                "暖言聊天自动回复助手",
                url,
                width=1000,
                height=760,
                min_size=(760, 600),
                text_select=True,
            )
            APP.window.events.closing += APP.hide_to_tray
            webview.start(gui="edgechromium", debug=False, private_mode=True)
    finally:
        APP.request_exit()
        if APP.worker:
            APP.worker.stop()
        APP.server.server_close()
        if server_thread and server_thread.is_alive():
            server_thread.join(timeout=3)
        close_instance_mutex(mutex_handle)
    # Some Windows/PyInstaller support threads can outlive serve_forever.
    # At this point the response was sent, the worker was stopped and the
    # listening socket was closed, so a process-level exit is intentional.
    if APP.exit_requested.is_set() or not headless:
        os._exit(0)


if __name__ == "__main__":
    main()

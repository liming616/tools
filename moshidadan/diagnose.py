# -*- coding: utf-8 -*-
"""
产地快打 — 全链路诊断工具

在每个关键节点打印详细日志，帮助定位双击->复制->解析->弹窗全流程中的问题。
"""

import sys
import os
import time
import json
import ctypes
import ctypes.wintypes as w
import threading

# 修复 Windows 终端编码问题 — 多重策略
if sys.platform == "win32":
    # 策略 1: 重配置 stdout
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 策略 2: 如果 reconfigure 失败，尝试用 stderr 作为备选（stderr 通常更宽容）
    if not hasattr(sys.stdout, "reconfigure") and not getattr(sys.stdout, "encoding", "").lower() in ("utf-8", "utf8"):
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

# ========================= 辅助 =========================

def _safe_str(s) -> str:
    """安全地将值转为可打印字符串，替换无法编码的字符。"""
    if s is None:
        return "<None>"
    try:
        return str(s).encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        return repr(s)[:200]

def ts() -> str:
    """返回当前时间戳字符串"""
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"

def _raw_print(*args):
    """绕过编码直接写入（作为最后的兜底）。"""
    try:
        print(*args)
    except UnicodeEncodeError:
        # 逐字符安全打印
        for arg in args:
            try:
                print(arg, end="")
            except UnicodeEncodeError:
                print(_safe_str(arg), end="")
        print()

def banner(title: str):
    _raw_print(f"\n{'='*60}")
    _raw_print(f"  {title}")
    _raw_print(f"{'='*60}")

def ok(msg: str):
    _raw_print(f"  [OK] {_safe_str(msg)}")

def warn(msg: str):
    _raw_print(f"  [WARN] {_safe_str(msg)}")

def fail(msg: str):
    _raw_print(f"  [FAIL] {_safe_str(msg)}")

def info(msg: str):
    _raw_print(f"  [INFO] {_safe_str(msg)}")

def node(step: str, msg: str):
    _raw_print(f"  [{ts()}] 【{step}】 {_safe_str(msg)}")


# ========================= Step 0: 环境检查 =========================

banner("Step 0 — 环境检查")

print(f"  Python 版本: {sys.version}")
print(f"  平台:        {sys.platform}")
print(f"  CWD:         {os.getcwd()}")

# 配置文件
from paths import app_dir
config_path = os.path.join(app_dir(), "config.json")
if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    ok(f"config.json 已加载:")
    for k, v in cfg.items():
        print(f"    {k} = {v!r}")
else:
    warn(f"config.json 不存在: {config_path}")

# 关键模块导入
try:
    import tkinter as tk
    ok("tkinter 导入成功")
except Exception as e:
    fail(f"tkinter 导入失败: {e}")

try:
    from parser import parse_order, format_for_order_software, OrderInfo
    ok("parser 模块导入成功")
except Exception as e:
    fail(f"parser 导入失败: {e}")

try:
    from hook_engine import (MouseHook, send_ctrl_c, send_ctrl_v, is_wechat_active,
                             get_foreground_title, get_foreground_class, get_foreground_hwnd,
                             _copy_to_clip, activate_window, find_window_by_title,
                             POINT, MSLLHOOKSTRUCT, HOOKPROC)
    ok("hook_engine 模块导入成功")
except Exception as e:
    fail(f"hook_engine 导入失败: {e}")

# 常量（从 hook_engine 复用值避免重复定义）
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 修复 64 位 Windows 下 restype 默认 c_long (32-bit) 导致的句柄截断问题
user32.OpenClipboard.restype = w.BOOL
user32.OpenClipboard.argtypes = [w.HWND]
user32.CloseClipboard.restype = w.BOOL
user32.GetClipboardData.restype = w.HANDLE
user32.GetClipboardData.argtypes = [w.UINT]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalUnlock.restype = w.BOOL
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]


# ========================= Step 1: 窗口检测 =========================

banner("Step 1 — 前台窗口检测（请先切换到微信窗口）")

print("  请在 5 秒内点击微信窗口使其成为前台...")
time.sleep(5)

hwnd = get_foreground_hwnd()
title = get_foreground_title()
cls = get_foreground_class()
is_wx = is_wechat_active()

_raw_print(f"  前台窗口句柄: {hwnd}")
_raw_print(f"  窗口标题:     '{_safe_str(title)}'")
_raw_print(f"  窗口类名:     '{_safe_str(cls)}'")
_raw_print(f"  is_wechat_active(): {is_wx}")

if is_wx:
    ok("微信窗口检测成功")
else:
    fail("未检测到微信窗口！")
    # 分析为什么
    ti_match = any(kw.lower() in title.lower() for kw in ["微信", "WeChat"])
    cl_match = any(kw.lower() in cls.lower() for kw in ["WeChatMainWndForPC", "ChatWnd", "WeChat"])
    print(f"    标题匹配: {ti_match}  类名匹配: {cl_match}")
    print(f"    -> HINT: 关键问题：如果标题和类名都不包含微信关键词，钩子永远不会触发！")
    print(f"    -> HINT: 请在 config.json 中确认 wechat_title_keywords 包含 '{title}' 的关键词")
    print(f"    -> HINT: 或者修改 hook_engine.py 中 WECHAT_TITLE_KEYWORDS / WECHAT_CLASS_KEYWORDS")


# ========================= Step 2: 鼠标钩子安装测试 =========================

banner("Step 2 — 鼠标钩子安装测试")

hook_id = [None]
running = [True]
events = []  # 所有捕获的点击
dc_time = user32.GetDoubleClickTime()
info(f"系统双击时间阈值: {dc_time} ms")
info(f"[!!] 注意：MSLLHOOKSTRUCT.time 是系统 tick（毫秒级计数器），不是毫秒级时间戳")
info(f"   但与 GetDoubleClickTime() 的比较仍然有效，因为两者都是毫秒单位")

def hook_callback(nCode, wParam, lParam):
    if nCode >= 0 and wParam == WM_LBUTTONDOWN:
        p = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents

        # 检查是否微信窗口
        _is_wx = is_wechat_active()
        _title = get_foreground_title()
        _cls = get_foreground_class()

        events.append({
            "tick": p.time,
            "x": p.pt.x,
            "y": p.pt.y,
            "wechat": _is_wx,
            "title": _title[:60],
            "class": _cls[:60],
        })

        if _is_wx:
            node("钩子", f"在微信中捕获点击! 坐标=({p.pt.x},{p.pt.y}) tick={p.time}")
        else:
            node("钩子", f"点击 (非微信窗口) 坐标=({p.pt.x},{p.pt.y}) 标题='{_title[:40]}'")

    return user32.CallNextHookEx(hook_id[0], nCode, wParam, lParam) if hook_id[0] else 0

# PeekMessage 创建消息队列（否则 SetWindowsHookExW 返回 126）
dummy_msg = w.MSG()
user32.PeekMessageW(ctypes.byref(dummy_msg), 0, 0, 0, 0)  # PM_NOREMOVE
proc = HOOKPROC(hook_callback)
hook_id[0] = user32.SetWindowsHookExW(WH_MOUSE_LL, proc, 0, 0)  # hMod=0

if not hook_id[0]:
    err = kernel32.GetLastError()
    fail(f"SetWindowsHookExW 返回 NULL, GetLastError={err}")
    if err == 5:
        fail("  -> ERROR_ACCESS_DENIED (5): 权限不足或被安全软件拦截")
        info("  解决方法：以管理员身份运行，或检查杀毒软件")
    elif err == 8:
        fail("  -> ERROR_NOT_ENOUGH_MEMORY (8)")
    elif err == 87:
        fail("  -> ERROR_INVALID_PARAMETER (87)")
    else:
        fail(f"  -> 未知错误码: {err}")
    # 跳到解析测试
    running[0] = False
else:
    ok(f"钩子安装成功! hook_id={hook_id[0]}")
    print()
    print("  +================================================+")
    print("  |  请在微信中双击一条订单消息！                   |")
    print("  |  监控窗口将持续 15 秒                           |")
    print("  +================================================+")
    print()

    msg = w.MSG()
    start_time = time.time()
    while running[0] and (time.time() - start_time) < 15:
        ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
        if ret <= 0:
            warn(f"GetMessageW 返回 {ret}，钩子消息循环退出")
            break
        user32.DispatchMessageW(ctypes.byref(msg))

    user32.UnhookWindowsHookEx(hook_id[0])
    ok("钩子已卸载")

    # --- 双击分析 ---
    print(f"\n  共捕获 {len(events)} 次点击")
    print(f"  其中微信内点击: {sum(1 for e in events if e['wechat'])} 次")

    if len(events) == 0:
        fail("未捕获到任何点击！可能原因：")
        print("    1. 钩子虽然安装但未收到消息（线程消息队列问题）")
        print("    2. 系统过滤了低权限钩子")
        print("    3. 杀毒软件拦截")
    else:
        print()
        print("  双击检测分析（仅分析微信内的连续点击）：")
        wx_clicks = [e for e in events if e["wechat"]]

        for i, e in enumerate(wx_clicks):
            print(f"    点击[{i+1}]: tick={e['tick']} pos=({e['x']},{e['y']})")
            if i > 0:
                prev = wx_clicks[i-1]
                dt = e["tick"] - prev["tick"]
                dx = abs(e["x"] - prev["x"])
                dy = abs(e["y"] - prev["y"])
                within_time = 0 < dt <= dc_time
                within_pos = dx < 10 and dy < 10

                verdict = "[OK] 判定为双击!" if (within_time and within_pos) else "[!!] 不满足双击条件"
                print(f"         dt={dt}ms (阈值={dc_time}ms) {'[OK]' if within_time else '[!!]'}")
                print(f"         dx={dx} dy={dy} (阈值=10px) {'[OK]' if within_pos else '[!!]'}")
                print(f"         -> {verdict}")

        if len(wx_clicks) < 2:
            fail("微信内点击不足 2 次，无法检测双击")
            print("    -> HINT: 你是否在微信聊天区域双击了？")
            print("    -> HINT: 双击的位置是否在同一消息气泡内（dx/dy < 10px）？")
            print("    -> HINT: 两次点击间隔是否在系统双击时间阈值内？")


# ========================= Step 3: 剪贴板读取测试 =========================

banner("Step 3 — 剪贴板读取测试")

print("  请手动在微信中复制一条订单消息（选中文本，Ctrl+C），然后等待...")
print("  倒计时 8 秒...")
for i in range(8, 0, -1):
    print(f"  {i}...", end=" ", flush=True)
    time.sleep(1)
print()

# 用 main.py 的方式读取剪贴板
CF_UNICODETEXT = 13
text = ""
if user32.OpenClipboard(0):
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                try:
                    text = ctypes.wstring_at(ptr) or ""
                finally:
                    kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

if text:
    ok(f"剪贴板读取成功，长度={len(text)} 字符")
    print(f"  内容预览:")
    for line in text.strip().split("\n")[:10]:
        print(f"    | {line}")
else:
    fail("剪贴板为空或读取失败")
    print("    -> HINT: 请确认：")
    print("       1. 在微信中选中了文本")
    print("       2. 按了 Ctrl+C（或右键->复制）")
    print("       3. 微信没有阻止复制操作")


# ========================= Step 4: 解析器测试 =========================

banner("Step 4 — 订单解析测试")

if text:
    node("解析", f"开始解析，输入文本长度={len(text)}")

    order = parse_order(text)

    print(f"  raw        : '{order.raw[:80]}...' " if len(order.raw) > 80 else f"  raw        : '{order.raw}'")
    print(f"  name       : '{order.name}'")
    print(f"  phone      : '{order.phone}'")
    print(f"  address    : '{order.address[:50]}...' " if len(order.address) > 50 else f"  address    : '{order.address}'")
    print(f"  items      : {order.items}")
    print(f"  notes      : '{order.notes}'")

    # 关键判断：main.py 中的条件
    can_trigger = bool(order.name or order.phone)
    if can_trigger:
        ok(f"解析成功 — name='{order.name}' phone='{order.phone}' — 会触发弹窗")

        formatted = format_for_order_software(order)
        print(f"  格式化输出:")
        for line in formatted.split("\n"):
            print(f"    | {line}")

        # 检查 min_text_length
        cfg_min_len = cfg.get("min_text_length", 5) if 'cfg' in dir() else 5
        if len(text.strip()) < cfg_min_len:
            fail(f"文本长度={len(text.strip())} < min_text_length={cfg_min_len}，会被过滤！")
    else:
        fail("解析失败 — name 和 phone 都为空，不会触发弹窗")
        print("    -> HINT: 解析策略：")
        print("       1. 标签匹配: 收货人/收件人/姓名/电话/手机/地址 等关键词")
        print("       2. 无标签时: 首行中文字符作为姓名，手机号正则匹配")
        print("       3. 无姓名+无电话 -> 返回空 -> main.py 跳过")
else:
    warn("跳过解析测试（剪贴板为空）")


# ========================= Step 5: Ctrl+C 模拟测试 =========================

banner("Step 5 — Ctrl+C 模拟测试")

print("  此测试验证 send_ctrl_c() 能否在微信中复制选中文本")
print("  请在 5 秒内切换到微信，选中一条消息文本（单击选中整条）...")
time.sleep(5)

info("发送 Ctrl+C ...")
send_ctrl_c()
time.sleep(0.2)

# 读取剪贴板
text2 = ""
if user32.OpenClipboard(0):
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                try:
                    text2 = ctypes.wstring_at(ptr) or ""
                finally:
                    kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

if text2:
    ok(f"Ctrl+C 模拟成功! 复制到文本长度={len(text2)}")
    print(f"  内容: '{text2[:100]}{'...' if len(text2)>100 else ''}'")
else:
    fail("Ctrl+C 模拟后剪贴板为空！")
    print("    -> HINT: 可能原因：")
    print("       1. 微信中未选中任何文本（单击只能选中气泡，需要双击或手动选中）")
    print("       2. 微信拦截了模拟键盘输入")
    print("       3. 需要在 message 列表中双击消息气泡（而不是在聊天输入框）")

# 用实际微信消息再测试一次（打开聊天窗口，手动双击消息气泡）
banner("Step 5b — 实际微信双击模拟")

print("  现在请在微信聊天窗口中找到一条订单消息")
print("  双击该消息的气泡（不是输入框里的文本）")
print("  程序将在 1 秒后自动发送 Ctrl+C 复制...")
print()
print("  准备中: 3秒后开始...")
for i in range(3, 0, -1):
    print(f"  {i}...")
    time.sleep(1)

# 检查是否在微信中
wx_active = is_wechat_active()
if wx_active:
    ok("检测到微信窗口为前台")
else:
    warn(f"当前前台窗口不是微信: '{get_foreground_title()}'")
    print("   继续尝试...")

info("发送 Ctrl+C ...")
send_ctrl_c()
time.sleep(0.15)

text3 = ""
if user32.OpenClipboard(0):
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                try:
                    text3 = ctypes.wstring_at(ptr) or ""
                finally:
                    kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

if text3:
    ok(f"Ctrl+C 成功! 长度={len(text3)}")
    print(f"  内容: '{text3[:150]}{'...' if len(text3)>150 else ''}'")

    # 解析
    order3 = parse_order(text3)
    print(f"  解析: name='{order3.name}' phone='{order3.phone}' items={len(order3.items)}")
    if order3.name or order3.phone:
        ok("解析成功，订单信息有效！")
        print(f"  格式化: \n{format_for_order_software(order3)}")
    else:
        fail("解析失败，请检查文本格式是否被 parser 支持")
else:
    fail("剪贴板仍为空 — Ctrl+C 未能复制微信中的消息")

# ========================= Step 6: 完整流程模拟 =========================

banner("Step 6 — 端到端流程模拟（在钩子线程中触发）")

print("  现在模拟真实的钩子->复制->解析->弹窗流程")
print("  请在 5 秒内切换到微信，选中一条订单消息...")
time.sleep(5)

def full_pipeline():
    """模拟 _on_double_click 的完整流程"""
    node("流水线", "=== 全流程开始 ===")

    # 1. 等待选中
    node("流水线", "等待 50ms 让系统完成选中...")
    time.sleep(0.05)

    # 2. 发送 Ctrl+C
    node("流水线", "发送 Ctrl+C ...")
    send_ctrl_c()

    # 3. 等待剪贴板更新
    node("流水线", "等待 100ms 剪贴板更新...")
    time.sleep(0.1)

    # 4. 读取剪贴板
    node("流水线", "读取剪贴板...")
    clipboard_text = ""
    if user32.OpenClipboard(0):
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                ptr = kernel32.GlobalLock(handle)
                if ptr:
                    try:
                        clipboard_text = ctypes.wstring_at(ptr) or ""
                    finally:
                        kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    if not clipboard_text:
        fail("剪贴板为空 — 流程中断")
        return

    node("流水线", f"剪贴板内容 ({len(clipboard_text)} 字符): '{clipboard_text[:80]}{'...' if len(clipboard_text)>80 else ''}'")

    # 5. 长度检查
    min_len = cfg.get("min_text_length", 5) if 'cfg' in dir() else 5
    if len(clipboard_text.strip()) < min_len:
        fail(f"文本太短 ({len(clipboard_text.strip())} < {min_len}) — 流程中断")
        return
    ok(f"长度检查通过 ({len(clipboard_text.strip())} >= {min_len})")

    # 6. 解析
    node("流水线", "调用 parse_order() ...")
    order = parse_order(clipboard_text)

    node("流水线", f"解析结果: name='{order.name}' phone='{order.phone}' address='{order.address[:30]}...' items={len(order.items)}")

    if not order.name and not order.phone:
        fail("name 和 phone 均为空 — 流程中断（不会弹窗）")
        print(f"    raw text: {order.raw[:200]}")
        return

    ok("订单解析成功，即将弹窗！")

    # 7. 格式化
    formatted = format_for_order_software(order)
    item_count = len(order.items)
    item_summary = (
        f"{order.items[0]['name']}×{order.items[0]['qty']}"
        + (f" 等{item_count}件" if item_count > 1 else "")
        if order.items else ""
    )
    summary = f"{order.name} | {order.phone}\n{order.address[:20]}...\n{item_summary}"

    node("流水线", f"摘要: {summary}")
    node("流水线", f"格式化文本:\n{formatted}")

    ok("[OK] 全流程成功！如果实际运行中弹窗没有出现，问题不在解析层面。")
    node("流水线", "=== 全流程结束 ===")


# 在主线程中运行
full_pipeline()


# ========================= Step 7: TK 窗口创建测试 =========================

banner("Step 7 — tkinter 窗口和弹窗测试")

print("  测试悬浮弹窗能否正常创建...")

try:
    import tkinter as tk
    root_test = tk.Tk()
    root_test.withdraw()  # 隐藏主窗口

    from overlay import show_overlay
    overlay = show_overlay(
        summary="测试：张三 | 13812345678\n2件商品",
        formatted_text="收货人：张三\n电话：13812345678\n地址：测试地址\n商品：\n  1. 商品A ×2",
        on_send=lambda t: print(f"  [弹窗回调] 发送: {t[:50]}..."),
        on_dismiss=lambda: print("  [弹窗回调] 弹窗关闭"),
        auto_dismiss=10.0,
    )
    ok("悬浮弹窗已创建！应该在屏幕右下角可见。10秒后自动关闭。")
    print("  （请查看屏幕右下角...）")

    # 运行消息循环让弹窗显示
    root_test.after(10000, root_test.quit)
    root_test.mainloop()

except Exception as e:
    fail(f"弹窗创建失败: {e}")
    import traceback
    traceback.print_exc()


# ========================= 总结 =========================

banner("诊断总结")

print("""
  请回答以下关键问题，确定问题出在哪一个环节：

  Step 1 — 前台窗口检测:
    [*] is_wechat_active() 在微信为前台时返回 True 吗？

  Step 2 — 鼠标钩子:
    [*] 钩子是否安装成功？（有无权限错误？）
    [*] 在微信中点击时，是否捕获到事件？
    [*] 双击检测是否正确触发？（dt < 阈值 且 dx/dy < 10px）

  Step 3/5 — 剪贴板:
    [*] 手动 Ctrl+C 后能否读取剪贴板？
    [*] 程序模拟 Ctrl+C 后能否读取剪贴板？

  Step 4 — 解析器:
    [*] 复制到的文本能否正确解析出 name 和 phone？
    [*] 文本格式是否被 parser 支持？

  Step 7 — 弹窗:
    [*] 弹窗能否正常显示在屏幕上？

  ------------------------------------------

  常见问题和解决方案:

  问题1: is_wechat_active() 返回 False
    -> 修改 hook_engine.py 中 WECHAT_TITLE_KEYWORDS 或 WECHAT_CLASS_KEYWORDS
    -> 或在 config.json 中配置自定义关键词

  问题2: 钩子安装失败（权限错误）
    -> 以管理员身份运行 python
    -> 检查杀毒软件是否拦截了全局钩子

  问题3: 钩子工作但 Ctrl+C 复制不到内容
    -> 微信可能阻止了模拟键盘输入 -> 考虑用 SendInput 替代 keybd_event
    -> 或使用 UI Automation 直接读取聊天消息

  问题4: 解析失败 name 和 phone 都为空
    -> 查看实际文本格式，调整 parser.py 中的正则表达式
    -> 微信消息可能包含额外的格式字符
""")

print("=" * 60)
print("  诊断完成。请将以上输出反馈给我以进一步分析。")
print("=" * 60)

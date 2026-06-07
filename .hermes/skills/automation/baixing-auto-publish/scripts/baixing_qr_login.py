#!/usr/bin/env python3
"""
百姓网登录助手 - 使用 Windows Chrome 的已有登录态
通过 Chrome 远程调试端口连接，自动提取登录 cookies 并保存
"""
import sys, os, time, json, subprocess, re

sys.path.insert(0, '/home/zng/.hermes/hermes-agent/venv/lib/python3.11/site-packages')

from playwright.sync_api import sync_playwright

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"--user-data-dir=C:\Users\Administrator\AppData\Local\Google\Chrome\User Data"
DEBUG_PORT = 9222
STATE_PATH = "/tmp/baixing_state.json"
LOGIN_URL = "https://www.baixing.com/oz/login/"
PUBLISH_URL = "https://shenzhen.baixing.com/fabu/ershoufang/"

def find_free_port():
    import socket
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def launch_chrome_with_debug(port):
    """启动 Chrome 远程调试模式"""
    import platform
    system = platform.system()
    
    if system == "Linux":
        chrome_path = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
        user_data = "/mnt/c/Users/Administrator/AppData/Local/Google/Chrome/User Data"
        cmd = [
            "cmd.exe", "/c", "start", "", 
            f'"{chrome_path}"',
            f"--remote-debugging-port={port}",
            f'--user-data-dir="{user_data}"',
            "--no-first-run",
            "--no-default-browser-check"
        ]
    else:
        chrome_path = CHROME_EXE
        user_data = USER_DATA_DIR.replace("--user-data-dir=", "")
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
    
    print(f"启动 Chrome 远程调试，端口: {port}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    return port

def get_chrome_debugger_url(port):
    """获取 Chrome debugger WebSocket URL"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=5)
        data = json.loads(resp.read())
        return data.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"获取 Chrome debugger URL 失败: {e}")
        return None

def check_login_via_debugger(port):
    """通过 Chrome 调试端口检查登录状态"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/json", timeout=5)
        tabs = json.loads(resp.read())
        print(f"  当前打开的标签页: {len(tabs)}")
        for tab in tabs:
            print(f"    - {tab.get('title', '?')}: {tab.get('url', '?')[:80]}")
        return tabs
    except Exception as e:
        print(f"  检查标签页失败: {e}")
        return []

def do_login_via_chrome(port):
    """
    启动可见 Chrome，让用户在 Chrome 里完成登录，然后提取 cookies
    """
    ws_url = get_chrome_debugger_url(port)
    if not ws_url:
        print("无法连接 Chrome 调试端口！")
        return False
    
    print(f"  WebSocket URL: {ws_url[:60]}...")
    
    with sync_playwright() as p:
        # 连接到已有 Chrome
        browser = p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        
        print(f"  当前页面: {page.url}")
        
        # 先导航到登录页
        page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=15000)
        time.sleep(3)
        print(f"  登录页 URL: {page.url}")
        
        # 检查登录状态
        if 'oz/login' not in page.url:
            print("  ✅ 看起来已经登录！直接提取 cookies")
            save_cookies(context)
            return True
        
        # 等待用户登录 - 监听 URL 变化
        print("  等待用户在 Chrome 中完成登录...")
        try:
            page.wait_for_url(lambda u: 'oz/login' not in u, timeout=120000)
            print(f"  ✅ 登录成功！URL: {page.url}")
            time.sleep(2)
            save_cookies(context)
            return True
        except Exception as e:
            print(f"  等待登录超时: {e}")
            # 即使超时也尝试提取 cookies
            save_cookies(context)
            return False

def save_cookies(context):
    """从 context 保存 cookies 到 state file"""
    cookies = context.cookies()
    state = {
        "cookies": cookies,
        "origins": []
    }
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f)
    print(f"  ✅ Cookies 已保存到 {STATE_PATH}")
    print(f"     共 {len(cookies)} 个 cookies")
    for c in cookies:
        print(f"     {c['domain']:30} {c['name']:25} httpOnly={c.get('httpOnly', False)}")

def main():
    print("=" * 50)
    print("百姓网登录助手 - 使用 Windows Chrome")
    print("=" * 50)
    
    # 1. 启动带调试端口的 Chrome
    port = find_free_port()
    launch_chrome_with_debug(port)
    
    # 2. 等待 Chrome 启动
    time.sleep(5)
    
    # 3. 检查 Chrome 状态
    tabs = check_login_via_debugger(port)
    
    # 4. 执行登录/提取 cookies
    success = do_login_via_chrome(port)
    
    if success:
        print("\n✅ 登录完成！可以运行 baixing_publisher.py")
    else:
        print("\n⚠️ 登录状态未确认，但已保存现有 cookies")
    
    print("\n按回车键退出...")
    input()

if __name__ == "__main__":
    main()

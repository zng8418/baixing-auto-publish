#!/usr/bin/env python3
"""
百姓网房产自动发布脚本 v4
新增: AI图片生成 + 自动上传（封面图+配图集成到发布流程）
用法: python3 baixing_publisher.py [day_number]
      python3 baixing_publisher.py --skip-images [day_number]  # 跳过图片生成/上传
输出最后一行: LINK:xxx 或 FAILED:xxx（供cron脚本解析）
"""
import sys, json, os, time, random, re, subprocess, io
# Force UTF-8 output on Windows (GBK can't handle emoji)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from playwright.sync_api import sync_playwright

CONFIG_PATH = "/home/zng/baixing_publish_config.json"
STATE_PATH = "/tmp/baixing_state.json"
# 技能目录永久备份（永不过期，优先加载）
SKILL_STATE_PATH = "/home/zng/.hermes/skills/automation/baixing-auto-publish/data/baixing_state.json"
LOG_PATH = "/home/zng/baixing_publish_log.jsonl"
SCREENSHOT_DIR = "/tmp/baixing_screenshots"
PUBLISH_URL = "https://shenzhen.baixing.com/fabu/ershoufang/"
IMAGE_OUTPUT_DIR = "/home/zng/baixing_images"
IMAGE_GEN_SCRIPT = "/home/zng/baixing_image_gen.py"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_today_schedule(config):
    if len(sys.argv) > 1:
        day = int(sys.argv[1])
    else:
        day = time.localtime().tm_wday + 1
        if day > 7: day = 7

    # SEO 动态内容生成（优先）
    seo_cfg = config.get('seo_content', {})
    seo_mode = seo_cfg.get('mode', 'fixed')

    if seo_cfg.get('enabled') and seo_mode in ('dynamic', 'hybrid'):
        try:
            # 动态导入 SEO 生成器
            sys.path.insert(0, '/home/zng')
            from baixing_seo_content import SEOContentGenerator
            gen = SEOContentGenerator()
            seo_result = gen.generate(day)
            schedule = {
                'day': day,
                'day_name': ['周一','周二','周三','周四','周五','周六','周日'][day-1],
                'title': seo_result['title'],
                'title_id': f"SEO-{seo_result['content_hash']}",
                'description': seo_result['description'],
            }
            print(f"  📊 SEO动态内容: 评分{seo_result['seo_score']}/100, 指纹{seo_result['content_hash']}")
            for d in seo_result.get('seo_details', []):
                print(f"    {d}")
            return schedule, day
        except Exception as e:
            print(f"  ⚠️ SEO动态生成失败: {e}")
            if seo_mode == 'dynamic':
                # pure dynamic 模式下失败则退出
                print(f"  ❌ SEO模式为dynamic，无法回退到固定内容")
                sys.exit(4)
            # hybrid 模式下回退到固定内容
            print(f"  ↩️ 回退到固定内容模式")

    # 固定内容（fallback）
    for s in config['schedule']:
        if s['day'] == day:
            return s, day
    return config['schedule'][0], 1

def log_result(data):
    data['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')

def human_delay(min_s=0.05, max_s=0.2):
    time.sleep(random.uniform(min_s, max_s))

def check_login(page):
    """检查登录状态 - 多重验证，必须满足以下之一才算已登录：
    1. URL 是发布页且包含表单元素（input[name=title] / select[name=地区[]])
    2. URL 不包含 /oz/login 等登录路径
    3. 页面包含"总价"+"标题"文字
    4. 检测到"我的发布"入口
    """
    try:
        page.goto(PUBLISH_URL, wait_until='domcontentloaded', timeout=20000)
        time.sleep(3)
    except Exception as e:
        print(f"  导航失败: {e}")
        return False
    
    url = page.url
    
    # URL 跳转到登录页 → 未登录
    if '/oz/login' in url or '/oz/wap' in url or 'login' in url.lower():
        print(f"  未登录: URL跳转到登录页 {url}")
        return False
    
    # URL 是发布页 → 检查表单元素
    if 'fabu/ershoufang' in url:
        try:
            has_title   = page.locator('input[name="title"]').count() > 0
            has_area    = page.locator('select[name="地区[]"]').count() > 0
            has_price   = page.locator('input[name="价格"]').count() > 0
            has_content = page.locator('textarea[name="content"]').count() > 0
            has_form    = page.locator('#bxForm').count() > 0
            if has_title or has_area or (has_price and has_content) or has_form:
                print(f"  已登录: 表单元素存在 (title={has_title}, area={has_area})")
                return True
            print(f"  ⚠ URL是发布页但表单元素缺失，尝试继续...")
        except Exception as e:
            print(f"  表单检查异常: {e}")
    
    # 页面文本分析
    try:
        text = page.evaluate(
            "() => { const b = document.body; return b && b.innerText ? b.innerText.substring(0,1000) : ''; }"
        )
    except Exception:
        text = ""
    
    # 有登录表单文本但无发布内容 → 未登录
    if ('手机号' in text or '验证码' in text or '账号登录' in text) and ('总价' not in text):
        print(f"  未登录: 检测到登录表单文本")
        return False
    
    # 有发布页特征文本
    if '总价' in text and '标题' in text:
        print(f"  已登录: 发布页文本检测")
        return True
    
    # 检测"我的发布"入口
    try:
        if page.locator('a[href*="/wo/"], a[href*="/w/posts"]').count() > 0:
            print(f"  已登录: 检测到「我的发布」入口")
            return True
    except:
        pass
    
    # 兜底：有 bxForm 表单
    try:
        if page.locator('#bxForm').count() > 0:
            print(f"  已登录: bxForm 存在")
            return True
    except:
        pass
    
    print(f"  无法确认登录状态，URL={url}")
    return False


def do_qr_login(page, timeout=600):
    """
    通过微信扫码登录百姓网（不依赖任何已存储的Cookie）。
    成功登录后自动保存 storage_state 到 STATE_PATH。
    返回 True=登录成功，False=失败。
    """
    print("\n=== 开始微信扫码登录 ===")
    
    LOGIN_URL = "https://www.baixing.com/oz/login/"
    LOGIN_SUCCESS_PATTERNS = [
        '/wo/', '/w/posts', '/u/', 'baixing.com/wo', 'fabu/ershoufang',
    ]
    
    try:
        # 1. 直接导航到登录页（不要清除 cookies，让服务器生成有效 QR）
        page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=20000)
        time.sleep(5)  # 等待 QR 生成
        print(f"  当前URL: {page.url}")
        
        # 检查 QR 是否失效，如果失效则刷新
        try:
            qr_text = page.evaluate(
                "() => { const els = document.querySelectorAll('[class*=\"qr\"]'); return Array.from(els).map(e => e.textContent.trim()).join('|'); }"
            )
            if '已失效' in qr_text or '失效' in qr_text:
                print(f"  ⚠ 检测到 QR 失效，刷新页面重试...")
                page.reload(wait_until='domcontentloaded', timeout=20000)
                time.sleep(5)
                qr_text2 = page.evaluate(
                    "() => { const els = document.querySelectorAll('[class*=\"qr\"]'); return Array.from(els).map(e => e.textContent.trim()).join('|'); }"
                )
                print(f"  刷新后 QR 状态: {qr_text2[:100]}")
        except Exception as e:
            print(f"  QR 状态检查异常: {e}")
        
        # 3. 尝试找微信登录二维码
        # 百姓网的扫码登录：找包含二维码图片的元素或扫码相关的 div
        qr_found = False
        
        # 尝试方法1：找 img 标签（常见于二维码）
        try:
            imgs = page.locator('img').all()
            for idx, img in enumerate(imgs):
                src = img.get_attribute('src') or ''
                alt = img.get_attribute('alt') or ''
                parent = ''
                try:
                    parent = img.locator('..').get_attribute('class') or ''
                except:
                    pass
                if 'qr' in src.lower() or 'qr' in alt.lower() or 'qr' in parent.lower():
                    print(f"  找到二维码 img[{idx}]: src={src[:80]}")
                    qr_found = True
                    break
            if not qr_found:
                print(f"  页面共有 {len(imgs)} 个 img，未发现二维码")
        except Exception as e:
            print(f"  查找二维码 img 异常: {e}")
        
        # 尝试方法2：找扫码相关的 section/div
        if not qr_found:
            try:
                scan_elements = page.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('[class*="scan"], [class*="qrcode"], [class*="qr-code"], [id*="scan"], [id*="qr"]').forEach(el => {
                        result.push({tag: el.tagName, cls: el.className, id: el.id, text: el.textContent.trim().substring(0, 50)});
                    });
                    return result;
                }""")
                if scan_elements:
                    print(f"  找到扫码相关元素: {scan_elements}")
                    qr_found = True
            except Exception as e:
                print(f"  查找扫码元素异常: {e}")
        
        # 尝试方法3：找微信登录 tab/按钮
        if not qr_found:
            try:
                wechat_tabs = page.locator('text=/微信|扫码|wechat|scan/i').all()
                if wechat_tabs:
                    print(f"  找到 {len(wechat_tabs)} 个微信/扫码相关元素")
                    for t in wechat_tabs[:3]:
                        t.click()
                        time.sleep(2)
                        print(f"    点击: {t.text_content()}")
                    qr_found = True
            except Exception as e:
                print(f"  找微信tab异常: {e}")
        
        # 尝试方法4：直接在页面查找扫码登录的链接或tab
        if not qr_found:
            try:
                scan_tabs = page.locator('a[href*="scan"], [data-type="scan"], [class*="scan-code"]').all()
                if scan_tabs:
                    scan_tabs[0].click()
                    time.sleep(2)
                    qr_found = True
                    print(f"  点击扫码入口成功")
            except Exception as e:
                print(f"  扫码入口点击异常: {e}")
        
        if not qr_found:
            # 最后手段：截屏看实际页面
            ts = time.strftime('%Y%m%d_%H%M%S')
            page.screenshot(path=f"{SCREENSHOT_DIR}/qr_login_page_{ts}.png")
            
            # 看看页面有什么 tab
            tabs = page.evaluate("""() => {
                const tabs = [];
                document.querySelectorAll('[class*="tab"], [class*="login-type"], [class*="method"]').forEach(el => {
                    tabs.push({cls: el.className, text: el.textContent.trim().substring(0, 100)});
                });
                return tabs;
            }""")
            print(f"  登录页 tab/方法: {tabs}")
            
            print(f"  ⚠ 无法自动找到二维码，请在截屏 {SCREENSHOT_DIR}/qr_login_page_{ts}.png 中确认")
            print(f"  等待人工扫码（{timeout}秒）...")
        else:
            ts = time.strftime('%Y%m%d_%H%M%S')
            page.screenshot(path=f"{SCREENSHOT_DIR}/qr_code_{ts}.png")
            print(f"  截屏已保存: {SCREENSHOT_DIR}/qr_code_{ts}.png")
            print(f"  ⏳ 等待微信扫码（{timeout}秒）...")
        
        # 4. 等待扫码成功 - 监听 URL 变化
        start_time = time.time()
        last_url = page.url
        
        while time.time() - start_time < timeout:
            current_url = page.url
            
            # 检测登录成功特征
            if any(pat in current_url for pat in LOGIN_SUCCESS_PATTERNS):
                elapsed = int(time.time() - start_time)
                print(f"  ✅ 扫码成功! ({elapsed}秒) URL: {current_url}")
                
                # 额外检查页面内容确认
                try:
                    text = page.evaluate("() => document.body.innerText.substring(0, 500)")
                    if '我的发布' in text or '发布' in text or '总价' in text:
                        print(f"  ✅ 页面内容确认已登录")
                except:
                    pass
                
                # 等待一下让 Cookies 完全写入
                time.sleep(3)
                
                # 保存登录状态（同时保存到技能目录永久备份）
                try:
                    page.context.storage_state(path=STATE_PATH)
                    print(f"  ✅ 登录状态已保存到 {STATE_PATH}")
                except Exception as e:
                    print(f"  ⚠ 保存登录状态失败: {e}")
                try:
                    # 同步到技能目录永久备份
                    import shutil
                    shutil.copy2(STATE_PATH, SKILL_STATE_PATH)
                    print(f"  ✅ 已同步到技能目录永久备份")
                except Exception as e:
                    print(f"  ⚠ 同步技能目录失败: {e}")
                
                return True
            
            # URL 变了（跳转）
            if current_url != last_url:
                print(f"  URL 变化: {last_url} → {current_url}")
                last_url = current_url
            
            time.sleep(2)
        
        print(f"  ❌ 扫码超时（{timeout}秒）")
        return False
        
    except Exception as e:
        print(f"  ❌ 扫码登录异常: {e}")
        return False


def select_area(page):
    """选择地区: 宝安区 > 石岩（使用 Playwright 原生 + 等待 AJAX 双重保障）"""
    # 先等待 select[name="地区[]"] 出现
    try:
        page.wait_for_selector('select[name="地区[]"]', timeout=10000)
    except Exception as e:
        print(f"  地区: 未找到下拉框: {e}")
        # 尝试 JS 注入方案
        _select_area_by_js(page)
        return
    
    # 第1步：选"宝安"区
    selected_baoan = False
    try:
        page.select_option('select[name="地区[]"]', label='宝安区', timeout=5000)
        print("  地区: 已选宝安区")
        selected_baoan = True
    except Exception as e:
        print(f"  地区选择失败(第1步): {e}")
        selected_baoan = _select_area_by_js(page)
    
    if not selected_baoan:
        return
    
    # 第2步：等 AJAX 加载石岩选项（最多等15秒，每2秒轮询）
    print("  等待石岩选项加载...")
    try:
        # 等待条件：第二个 select 存在 且 options 包含"石岩"
        page.wait_for_function(
            """() => {
                const selects = document.querySelectorAll('select[name="地区[]"]');
                if (selects.length < 2) return false;
                const opts = selects[1].options;
                for (let i = 0; i < opts.length; i++) {
                    if (opts[i].textContent.includes('石岩')) return true;
                }
                return false;
            }""",
            timeout=15000
        )
        
        # 找到了，选石岩
        second_selects = page.query_selector_all('select[name="地区[]"]')
        opts_html = second_selects[1].inner_html()
        
        if '石岩街道' in opts_html:
            second_selects[1].select_option(label='石岩街道')
            print("  地区: 宝安 > 石岩街道 ✓")
        elif '石岩' in opts_html:
            second_selects[1].select_option(label='石岩')
            print("  地区: 宝安 > 石岩 ✓")
        else:
            print(f"  地区: 宝安(石岩选项未找到)")
            
    except Exception as e:
        print(f"  地区: 等待石岩选项超时: {e}")
        # 截屏供调试
        ts = time.strftime('%Y%m%d_%H%M%S')
        try:
            page.screenshot(path=f"{SCREENSHOT_DIR}/area_select_{ts}.png")
            print(f"  截屏: {SCREENSHOT_DIR}/area_select_{ts}.png")
        except:
            pass


def _select_area_by_js(page):
    """JS 备选方案：直接操作 DOM 选地区"""
    try:
        page.evaluate("""() => {
            const selects = document.querySelectorAll('select[name="地区[]"]');
            if (selects.length < 1) return;
            // 选宝安
            for (const opt of selects[0].options) {
                if (opt.textContent.includes('宝安')) {
                    selects[0].value = opt.value;
                    selects[0].dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }""")
        time.sleep(4)  # 等待AJAX
        
        # 选石岩
        page.evaluate("""() => {
            const selects = document.querySelectorAll('select[name="地区[]"]');
            if (selects.length < 2) return;
            for (const opt of selects[1].options) {
                if (opt.textContent.includes('石岩')) {
                    selects[1].value = opt.value;
                    selects[1].dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }""")
        print("  地区: JS备选方案已执行")
        return True
    except Exception as e:
        print(f"  地区: JS备选失败 {e}")
        return False

# =============================================================================
# 图片生成与上传模块 (v4 新增)
# =============================================================================

def ensure_images_for_day(day):
    """
    确保指定日期的图片已生成。如果图片已存在则跳过，否则调用 baixing_image_gen.py 生成。
    返回: dict { 'cover': path_or_None, 'transport': path_or_None, 'feature': path_or_None }
    """
    day_dir = os.path.join(IMAGE_OUTPUT_DIR, f"day{day}")
    cover_path = os.path.join(day_dir, "cover.png")
    transport_path = os.path.join(day_dir, "illust_transport.png")
    feature_path = os.path.join(day_dir, "illust_feature.png")

    result = {
        'cover': cover_path if os.path.exists(cover_path) else None,
        'transport': transport_path if os.path.exists(transport_path) else None,
        'feature': feature_path if os.path.exists(feature_path) else None,
    }

    # 如果所有图片都存在，直接返回
    if all(result.values()):
        print(f"  ✓ 图片已存在: day{day}/ ({', '.join(os.path.basename(p) for p in result.values())})")
        return result

    # 需要生成图片
    missing = [k for k, v in result.items() if not v]
    print(f"  ⏳ 图片缺失 {missing}，正在生成...")
    try:
        gen_result = subprocess.run(
            ["python3", IMAGE_GEN_SCRIPT, str(day)],
            capture_output=True, text=True, timeout=300,
            env={**os.environ}
        )
        if gen_result.returncode == 0:
            print(f"  ✓ 图片生成成功")
        else:
            print(f"  ⚠ 图片生成返回非零: {gen_result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"  ⚠ 图片生成超时(5min)，继续无图发布")
    except Exception as e:
        print(f"  ⚠ 图片生成异常: {e}")

    # 重新检查
    result['cover'] = cover_path if os.path.exists(cover_path) else None
    result['transport'] = transport_path if os.path.exists(transport_path) else None
    result['feature'] = feature_path if os.path.exists(feature_path) else None

    found = sum(1 for v in result.values() if v)
    print(f"  📊 可用图片: {found}/3 (封面={'✓' if result['cover'] else '✗'}, 交通={'✓' if result['transport'] else '✗'}, 亮点={'✓' if result['feature'] else '✗'})")
    return result


def upload_images_to_form(page, images, schedule):
    """
    在已填写的发布表单上上传图片。
    
    策略:
    1. 封面图 → 上传到表单的第一个图片上传框（主图）
    2. 交通配图 + 亮点配图 → 上传到额外图片上传框
    3. 如果表单有图片描述/备注字段，添加图片说明
    
    参数:
        page: Playwright page 对象（已在发布页面）
        images: dict from ensure_images_for_day()
        schedule: 当前发布计划
    """
    print("\n上传图片...")
    uploaded_count = 0

    # 收集所有待上传图片（按优先级：封面 > 交通 > 亮点）
    upload_list = []
    if images.get('cover'):
        upload_list.append(('封面图', images['cover']))
    if images.get('transport'):
        upload_list.append(('交通配图', images['transport']))
    if images.get('feature'):
        upload_list.append(('亮点配图', images['feature']))

    if not upload_list:
        print("  ⚠ 没有可用图片，跳过上传")
        return 0

    # 等待页面图片上传区域完全加载
    time.sleep(2)

    # 百姓网发布页的图片上传方式：查找 file input 或上传按钮
    # 方案1: 查找 <input type="file"> 并直接设置文件
    # 方案2: 查找上传按钮区域，用 Playwright 的 set_input_files
    
    for idx, (label, img_path) in enumerate(upload_list):
        try:
            # 尝试找到图片上传的 file input
            file_inputs = page.locator('input[type="file"]').all()
            
            if idx < len(file_inputs):
                # 直接用对应的 file input
                file_inputs[idx].set_input_files(img_path)
                print(f"  ✓ {label} 已上传: {os.path.basename(img_path)}")
                uploaded_count += 1
                time.sleep(1.5)  # 等待上传完成
            else:
                # 尝试点击上传区域触发 file chooser
                # 百姓网常见: .upload-area, [class*="upload"], .image-upload
                upload_areas = page.evaluate("""() => {
                    const areas = [];
                    // 查找所有看起来像上传区域的元素
                    document.querySelectorAll(
                        '[class*="upload"], [class*="image-add"], [class*="photo-add"], ' +
                        '[class*="pic-add"], [data-action="upload"], .image-item.empty'
                    ).forEach(el => {
                        areas.push({
                            selector: el.className,
                            tag: el.tagName,
                            text: el.textContent.trim().substring(0, 30)
                        });
                    });
                    return areas;
                }""")
                
                if upload_areas:
                    # 使用 file chooser 事件
                    with page.expect_file_chooser(timeout=5000) as fc_info:
                        # 尝试各种可能的上传触发器
                        clicked = False
                        for sel in ['.upload-area', '[class*="image-add"]', '[class*="upload"]', '.image-item.empty']:
                            try:
                                loc = page.locator(sel).first
                                if loc.count() > 0:
                                    loc.click()
                                    clicked = True
                                    break
                            except:
                                continue
                        
                        if not clicked:
                            raise Exception("未找到上传区域")
                    
                    file_chooser = fc_info.value
                    file_chooser.set_files(img_path)
                    print(f"  ✓ {label} 已上传(file_chooser): {os.path.basename(img_path)}")
                    uploaded_count += 1
                    time.sleep(1.5)
                else:
                    print(f"  ⚠ {label}: 未找到上传入口，跳过")
                    
        except Exception as e:
            # 非致命错误：图片上传失败不应阻止发布
            print(f"  ⚠ {label} 上传失败: {str(e)[:100]}")
            continue

    # 如果有图片描述字段，添加说明
    if uploaded_count > 0:
        try:
            img_desc_field = page.locator('input[name="imageDesc"], textarea[name="imageDesc"], input[placeholder*="图片"]')
            if img_desc_field.count() > 0:
                desc = f"实景拍摄，{schedule.get('day_name', '')}房源实拍"
                img_desc_field.first.fill(desc)
                print(f"  ✓ 图片描述: {desc}")
        except:
            pass

    print(f"  📊 图片上传完成: {uploaded_count}/{len(upload_list)}")
    return uploaded_count


def enhance_description_with_images(schedule, images):
    """
    如果有配图，在描述文本中嵌入图片说明（增强可信度）。
    注意：百姓网的描述是纯文本 textarea，不支持 HTML img 标签。
    但可以在描述中加入图片引用提示文字。
    """
    desc = schedule['description']
    
    # 如果有配图，在描述末尾追加图片说明
    image_notes = []
    if images.get('transport'):
        image_notes.append("📍 交通配套图见上方图片，双地铁口出行便利")
    if images.get('feature'):
        image_notes.append("🏠 房源亮点图见上方图片，户型方正通透")
    
    if image_notes:
        # 在描述末尾追加，确保不超过5000字限制
        addition = "\n\n" + "\n".join(image_notes)
        if len(desc) + len(addition) <= 4950:
            desc = desc + addition
            print(f"  ✓ 描述已增强（+图片说明 {len(addition)}字）")
    
    return desc

def fill_form(page, schedule, prop):
    """填写发布表单"""
    print("填写表单...")
    page.wait_for_load_state('domcontentloaded')
    time.sleep(1)

    # 身份
    try:
        page.locator('input[name="posterType"][value="个人"]').click()
    except: pass
    human_delay()

    # 小区名
    try:
        inp = page.locator('input[name="小区名"]')
        if inp.count() > 0:
            inp.click()
            inp.fill(prop['community'])
            time.sleep(0.5)
            page.keyboard.press('Escape')
            page.evaluate("() => { const o = document.getElementById('community-overlay'); if(o) o.style.display='none'; }")
            print(f"  ✓ 小区名")
    except: pass
    human_delay()

    # 地区
    select_area(page)
    human_delay()

    # 具体地点
    page.evaluate("(v) => { const e = document.querySelector('input[name=\"具体地点\"]'); if(e){e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));} }", prop['address'])
    human_delay()

    # 面积、楼层、总楼层
    for field, val in [('面积', prop['area']), ('楼层', prop['floor']), ('总楼层', prop['total_floor'])]:
        try:
            inp = page.locator(f'input[name="{field}"]')
            if inp.count() > 0:
                inp.fill(str(val))
        except: pass
    human_delay()

    # 朝向、装修、房屋类型
    for sel_name, val in [('房间朝向', prop.get('orientation', '')), ('装修情况', prop['decoration']), ('房屋类型', prop['house_type'])]:
        try:
            if val:
                page.locator(f'select[name="{sel_name}"]').select_option(label=val)
        except: pass
    human_delay()

    # 建筑年代
    try:
        page.locator('input[name="建筑年代"]').fill(str(prop['build_year']))
    except: pass

    # 是否满二、唯一住房
    try: page.locator('input[name="是否满二"][value="0"]').click()
    except: pass
    try: page.locator('input[name="唯一住房"][value="0"]').click()
    except: pass
    human_delay()

    # 总价
    try:
        page.locator('input[name="价格"]').fill(str(prop['price']))
    except: pass
    human_delay()

    # 标题
    try:
        page.locator('input[name="title"]').fill(schedule['title'])
        print(f"  ✓ 标题: {schedule['title']}")
    except: pass

    # 描述
    try:
        desc = page.locator('textarea[name="content"][maxlength="5000"]').first
        desc.fill(schedule['description'])
        print(f"  ✓ 描述: {len(schedule['description'])}字")
    except: pass

    # 联系电话
    try:
        page.locator('input[name="contact"]').fill(prop['contact'])
    except: pass

    time.sleep(1)
    print("  ✓ 表单填写完成")

def submit_form(page):
    """提交发布 - 收集表单数据后直接POST"""
    print("\n提交发布...")

    # 等待 contactchecker 完成
    time.sleep(2)

    # 1. 先勾选隐私协议（如果有checkbox）
    page.evaluate("""() => {
        const checkboxes = document.querySelectorAll('#bxForm input[type="checkbox"]');
        checkboxes.forEach(cb => { if(!cb.checked) cb.click(); });
        // 也试 class 包含 agreement 的
        const agree = document.querySelectorAll('[class*="agreement"] input, [id*="agreement"] input');
        agree.forEach(cb => { if(cb.type === 'checkbox' && !cb.checked) cb.click(); });
    }""")
    print("  ✓ 勾选协议")

    # 2. 收集表单数据
    form_data = page.evaluate("""() => {
        const form = document.getElementById('bxForm');
        const fd = new FormData(form);
        const data = {};
        for (const [key, value] of fd.entries()) {
            if (data[key]) {
                // 多值字段用数组
                if (!Array.isArray(data[key])) data[key] = [data[key]];
                data[key].push(value);
            } else {
                data[key] = value;
            }
        }
        return data;
    }""")

    # 检查关键字段
    print(f"  表单字段: {len(form_data)}个")
    for k in ['title', 'contact', 'content', 'posterType']:
        v = form_data.get(k, '')
        print(f"    {k} = {str(v)[:50]}")

    if not form_data.get('title'):
        print("  ❌ 标题为空，提交会失败")
    if not form_data.get('contact'):
        print("  ❌ 联系电话为空，提交会失败")
    if not form_data.get('content'):
        print("  ❌ 描述为空，提交会失败")

    # 3. 用 fetch POST 提交表单（不走页面跳转）
    print("  用fetch提交...")
    submit_result = page.evaluate("""async (formData) => {
        try {
            const body = new URLSearchParams();
            for (const [key, value] of Object.entries(formData)) {
                if (Array.isArray(value)) {
                    value.forEach(v => body.append(key, v));
                } else {
                    body.append(key, value);
                }
            }
            
            const resp = await fetch('https://shenzhen.baixing.com/fabu/ershoufang/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: body.toString(),
                credentials: 'include',
                redirect: 'follow'
            });
            
            const text = await resp.text();
            const finalUrl = resp.url;
            
            return {
                status: resp.status,
                url: finalUrl,
                redirected: resp.redirected,
                hasPublishSuccess: text.includes('发布成功') || text.includes('恭喜'),
                hasAudit: text.includes('审核'),
                titleInResponse: text.includes('随缘人生随缘'),
                textPreview: text.substring(0, 800)
            };
        } catch(e) {
            return {error: e.message};
        }
    }""", form_data)

    print(f"  提交响应: status={submit_result.get('status')} url={submit_result.get('url','')[:80]}")
    print(f"  redirected={submit_result.get('redirected')} hasPublishSuccess={submit_result.get('hasPublishSuccess')}")

    # 如果 fetch 返回了成功页面，导航过去
    if submit_result.get('redirected') or submit_result.get('hasPublishSuccess'):
        target_url = submit_result.get('url', '')
        if target_url and 'fabu/ershoufang' not in target_url:
            print(f"  跳转到: {target_url}")
            page.goto(target_url, wait_until='domcontentloaded', timeout=10000)
            time.sleep(3)

    # 4. 如果fetch方式不行，试试页面内 form.submit
    if not submit_result.get('hasPublishSuccess') and not submit_result.get('url', '').replace('fabu/ershoufang', ''):
        print("  fetch未成功，尝试页面内form提交...")
        try:
            # 给表单加一个隐藏的submit按钮
            page.evaluate("""() => {
                const form = document.getElementById('bxForm');
                const btn = document.createElement('input');
                btn.type = 'submit';
                btn.id = 'hermes-submit-btn';
                btn.style.display = 'none';
                form.appendChild(btn);
            }""")
            with page.expect_navigation(timeout=15000, wait_until='domcontentloaded'):
                page.evaluate("() => document.getElementById('hermes-submit-btn').click()")
        except:
            page.evaluate("() => document.getElementById('bxForm').submit()")
        time.sleep(3)

    # 等待页面跳转或响应（最多20秒）
    time.sleep(3)
    for i in range(17):
        current_url = page.url
        if 'fabu/ershoufang' not in current_url:
            print(f"  页面已跳转: {current_url}")
            break
        time.sleep(1)
    else:
        print(f"  仍在发布页: {current_url}")

    # 截图
    ts = time.strftime('%Y%m%d_%H%M%S')
    page.screenshot(path=f"{SCREENSHOT_DIR}/submit_result_{ts}.png")

    url = page.url
    text = page.evaluate("()=>document.body.innerText.substring(0,1500)")
    print(f"  当前URL: {url}")

    # 判断结果
    if '发布成功' in text or '恭喜' in text:
        return True, "发布成功", url
    if '审核' in text:
        return True, "已提交审核", url
    if 'fabu/ershoufang' not in url:
        return True, f"页面跳转: {url}", url
    if 'fabu/ershoufang' in url:
        # 检查错误
        errors = page.evaluate("""() => {
            const errs = [];
            document.querySelectorAll('.error, .err, .warn, [class*="error"], .field-error').forEach(el => {
                const t = el.textContent.trim();
                if (t && t.length < 100 && !t.includes('×')) errs.push(t);
            });
            return errs.join('; ');
        }""")
        if errors:
            return False, f"表单错误: {errors}", url
        return False, "提交后仍在发布页", url
    return False, f"未知结果: {url}", url

def get_published_links(page):
    """从'我的发布'页面获取最新发布的文章链接"""
    print("\n获取已发布文章链接...")

    page.goto('https://www.baixing.com/wo/posts', wait_until='domcontentloaded', timeout=15000)
    time.sleep(5)

    # 找帖子链接 - 优先找文章详情页链接（含adId的.html）
    links = page.evaluate("""() => {
        const results = [];
        const seen = new Set();
        // 优先找 /ershoufang/aXXXXX.html 格式的文章链接
        document.querySelectorAll('a[href*=\"ershoufang/a\"][href$=\".html\"]').forEach(a => {
            const href = a.href;
            if (!seen.has(href)) {
                seen.add(href);
                results.push({text: a.textContent.trim().substring(0, 60), href});
            }
        });
        // 补充其他文章链接
        document.querySelectorAll('a[href$=\".html\"]').forEach(a => {
            if (a.href.includes('baixing.com') && a.href.includes('/a') && !a.href.includes('fabu')) {
                const href = a.href;
                if (!seen.has(href)) {
                    seen.add(href);
                    results.push({text: a.textContent.trim().substring(0, 60), href});
                }
            }
        });
        return results;
    }""")

    if links:
        print(f"  找到 {len(links)} 个链接:")
        for l in links[:5]:
            print(f"    {l['text'][:40]} -> {l['href']}")
        return links
    else:
        # 没找到结构化链接，尝试搜索页面内容
        html = page.content()
        # 匹配 shenzhen.baixing.com/ershoufang/xxxxx.html 格式
        article_urls = re.findall(r'https?://shenzhen\.baixing\.com/ershoufang/[a-zA-Z0-9]+\.html', html)
        if not article_urls:
            article_urls = re.findall(r'https?://\w+\.baixing\.com/\w+/\w+\.html', html)
        if article_urls:
            print(f"  从HTML中提取到 {len(article_urls)} 个文章链接")
            for u in article_urls[:5]:
                print(f"    {u}")
            return [{'href': u, 'text': ''} for u in article_urls]

        # 最后手段 - 搜索我的帖子API
        print("  尝试API获取...")
        page.goto('https://www.baixing.com/w/posts/myPosts/all', wait_until='domcontentloaded', timeout=15000)
        time.sleep(3)
        api_links = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('a[href]').forEach(a => {
                if (a.href && a.href.includes('baixing.com') && !a.href.includes('fabu') &&
                    !a.href.includes('/wo/') && !a.href.includes('/w/posts') &&
                    !a.href.includes('javascript') && !a.href.includes('.css') &&
                    (a.href.includes('.html') || a.href.includes('/ershoufang/'))) {
                    results.push({text: a.textContent.trim().substring(0, 60), href: a.href});
                }
            });
            return results;
        }""")
        if api_links:
            print(f"  API方式找到 {len(api_links)} 个链接")
            for l in api_links[:5]:
                print(f"    {l['text'][:40]} -> {l['href']}")
            return api_links

        print("  ⚠ 未找到文章链接")
        return []

def check_free_quota(page):
    """检查当前类目是否有免费发布额度
    返回: True=有免费额度可发布, False=额度已用完需付费
    """
    try:
        page.wait_for_load_state('domcontentloaded', timeout=15000)
        time.sleep(3)
        
        # 检查是否出现"付费发布提醒"（额度用完的标志）
        body_text = page.inner_text('body')
        heading = page.locator('h3').all()
        heading_texts = [h.inner_text() for h in heading]
        
        # 特征1: 有"付费发布提醒"标题
        has_pay_wall = any('付费发布提醒' in t for t in heading_texts)
        
        # 特征2: 有"额度已用完"或"需支付"字样
        has_quota_exhausted = '额度已用完' in body_text or '需支付2元' in body_text
        
        if has_pay_wall and has_quota_exhausted:
            # 提取余额信息
            import re
            balance_match = re.search(r'余额[：:]\s*(\d+)元', body_text)
            balance = int(balance_match.group(1)) if balance_match else 0
            print(f"⚠️ 免费额度已用完！账户余额: {balance}元，需充值才能发布")
            return False
        
        print("✅ 免费额度检查通过，可以发布")
        return True
        
    except Exception as e:
        print(f"  ⚠️ 额度检查异常: {e}，继续尝试发布")
        return True

def main():
    # 解析 --skip-images 参数
    skip_images = '--skip-images' in sys.argv
    sys.argv = [a for a in sys.argv if a != '--skip-images']

    config = load_config()
    schedule, day = get_today_schedule(config)
    prop = config['property']

    # 检查图片功能是否启用
    img_cfg = config.get('image_generation', {})
    images_enabled = img_cfg.get('enabled', True) and not skip_images

    print(f"{'='*50}")
    print(f"百姓网自动发布 v4 - Day{day} ({schedule['day_name']})")
    print(f"标题: {schedule['title']}")
    print(f"AI图片: {'启用' if images_enabled else '禁用'}")
    print(f"{'='*50}\n")

    # ===== Phase 1: 图片预生成（浏览器启动前） =====
    images = {'cover': None, 'transport': None, 'feature': None}
    if images_enabled:
        print("[图片] 预生成检查...")
        images = ensure_images_for_day(day)
        print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])

        # 智能加载 cookie：优先用技能目录永久备份，其次用 /tmp
        effective_state = SKILL_STATE_PATH if os.path.exists(SKILL_STATE_PATH) else STATE_PATH
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 720}
        )
        if os.path.exists(effective_state):
            try:
                with open(effective_state) as f:
                    state = json.load(f)
                # 修复 sameSite 格式（no_restriction → None）
                for c in state.get('cookies', []):
                    if c.get('sameSite') == 'no_restriction':
                        c['sameSite'] = 'None'
                    elif c.get('sameSite') is None:
                        c['sameSite'] = 'Lax'
                ctx.add_cookies(state['cookies'])
                print(f"  ✅ 已从技能目录加载 cookies（{len(state['cookies'])} 个）")
            except Exception as e:
                print(f"  ⚠️ Cookie加载失败({e})，将尝试重新登录")


        page = ctx.new_page()

        # 检查登录
        print("检查登录...")
        logged_in = check_login(page)
        if not logged_in:
            print("❌ Cookie已过期或未登录！启动微信扫码登录...")
            qr_success = do_qr_login(page, timeout=120)
            if not qr_success:
                print("❌ 扫码登录失败！")
                log_result({'day': day, 'title': schedule['title'], 'status': 'FAILED', 'reason': '扫码登录失败'})
                browser.close()
                print("NEED_RELOGIN")
                sys.exit(2)
            print("✅ 扫码登录成功！")
            # 重新导航到发布页
            page.goto(PUBLISH_URL, wait_until='domcontentloaded', timeout=20000)
            time.sleep(3)

        print("✅ 已登录\n")

        # ===== Phase 0: 免费额度检查 =====
        print("[额度检查] 检查免费发布额度...")
        if not check_free_quota(page):
            print("❌ 免费额度已用完，跳过本次发布")
            log_result({'day': day, 'title': schedule['title'], 'status': 'SKIPPED', 'reason': '免费额度已用完'})
            browser.close()
            print("QUOTA_EXHAUSTED")
            sys.exit(3)
        print()

        # 如果check_login跳到了发布页，需要重新加载确保表单干净
        if 'fabu/ershoufang' in page.url:
            page.goto(PUBLISH_URL, wait_until='domcontentloaded', timeout=15000)
            time.sleep(3)

        # ===== Phase 2: 填写表单（含增强描述） =====
        # 如果有配图，增强描述文本
        if images_enabled and any(images.values()):
            schedule = dict(schedule)  # 不修改原始配置
            schedule['description'] = enhance_description_with_images(schedule, images)

        fill_form(page, schedule, prop)

        # ===== Phase 3: 上传图片 =====
        uploaded = 0
        if images_enabled and any(images.values()):
            uploaded = upload_images_to_form(page, images, schedule)

        # ===== Phase 4: 提交 =====
        success, reason, final_url = submit_form(page)

        # 获取文章链接 — 优先从成功页URL提取adId构造
        article_link = ""
        if success:
            # 方法1: 从成功页URL直接提取adId
            ad_id_match = re.search(r'adId=(\d+)', final_url)
            if ad_id_match:
                article_link = f"https://shenzhen.baixing.com/ershoufang/a{ad_id_match.group(1)}.html"
                print(f"  ✅ 文章链接（从adId构造）: {article_link}")
            else:
                # 方法2: 从"我的发布"页面提取
                links = get_published_links(page)
                if links:
                    article_link = links[0]['href']

        # 保存cookie（同时同步到技能目录永久备份）
        ctx.storage_state(path=STATE_PATH)
        try:
            import shutil
            shutil.copy2(STATE_PATH, SKILL_STATE_PATH)
        except:
            pass

        # 记录结果（含图片信息）
        result = {
            'day': day,
            'title': schedule['title'],
            'title_id': schedule.get('title_id', ''),
            'status': 'SUCCESS' if success else 'FAILED',
            'reason': reason,
            'url': final_url,
            'article_link': article_link,
            'images_uploaded': uploaded,
            'images_available': sum(1 for v in images.values() if v),
            'cover_uploaded': images.get('cover') is not None and uploaded > 0,
        }
        log_result(result)

        print(f"\n{'='*50}")
        if success:
            print(f"✅ {reason}")
            print(f"📸 图片: {uploaded}/{result['images_available']}张已上传")
            if article_link:
                print(f"📎 文章链接: {article_link}")
                print(f"LINK:{article_link}")
            else:
                print(f"LINK:NONE")
        else:
            print(f"❌ {reason}")
            print(f"FAILED:{reason}")
        print(f"{'='*50}")

        ts = time.strftime('%Y%m%d_%H%M%S')
        page.screenshot(path=f"{SCREENSHOT_DIR}/final_{ts}.png")

        browser.close()
        sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()

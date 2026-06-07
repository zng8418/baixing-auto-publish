#!/usr/bin/env python3
"""
百姓网房产自动发布系统 - 图片生成模块
根据7天发布配置，为每天生成1张封面图和2张文章配图。

用法:
    python3 baixing_image_gen.py           # 生成今天的图片
    python3 baixing_image_gen.py all       # 生成全部7天图片
    python3 baixing_image_gen.py 3         # 生成第3天图片
    python3 baixing_image_gen.py --dry-run # 只打印prompt不生成
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime

# =============================================================================
# 常量
# =============================================================================
BASE_DIR = "/home/zng"
CONFIG_PATH = os.path.join(BASE_DIR, "baixing_publish_config.json")
OUTPUT_BASE = os.path.join(BASE_DIR, "baixing_images")
LOG_PATH = os.path.join(BASE_DIR, "baixing_image_gen.log")
IMAGINE_SCRIPT = os.path.expanduser(
    "~/.hermes/skills/creative/baoyu-imagine/scripts/main.ts"
)
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# 每天封面图的关键卖点定制
DAY_COVER_KEYWORDS = {
    1: "Dual metro station access — highlighted with two converging transit lines",
    2: "Property certificate and village committee transfer — emphasizing legal ownership security",
    3: "Elevator building high floor 11th level — showcasing panoramic city views from elevation",
    4: "Low price 1.28 million yuan for metro-adjacent property — emphasizing unbeatable value",
    5: "Green certificate with guaranteed village transfer — emphasizing property rights protection",
    6: "Premium village-built residential complex — showcasing quality unified construction",
    7: "Owner direct sale no agency fee — highlighting zero-commission transparent dealing",
}

# 每天封面图的额外视觉定制
DAY_COVER_VISUALS = {
    1: "Two glowing metro line indicators converging at the building location, transit-focused composition",
    2: "Prominent certificate document icon with security seal, trust and authority theme",
    3: "Elevator shaft exterior with floor number display, upward perspective from street level",
    4: "Price tag overlay graphic, value-oriented composition with cost comparison elements",
    5: "Official document and stamp motif with protective shield, security and legitimacy theme",
    6: "Well-maintained multi-story residential complex with landscaped entrance, quality construction focus",
    7: "For-sale-by-owner sign with direct contact, person-to-person handshake visual element",
}

# 配图1: 交通优势（所有天通用，微调）
TRANSPORT_BASE = (
    "Infographic illustration showing dual metro line connectivity for a Shenzhen Baoan property. "
    "Metro Line 6 (Shangwu station 250m walk) and upcoming Line 13 (Shiyan station). "
    "Clean flat vector style with route map visualization. "
    "Warm cream background. Key distances and station names labeled. "
    "Walking distance icons, transit route lines in blue and orange. "
    "Real estate transport highlight card."
)

# 每天交通配图微调
TRANSPORT_DAY_HINTS = {
    1: "Emphasize dual metro convergence with bold route lines.",
    2: "Include location pin with certificate badge overlay on the map.",
    3: "Show elevation indicator alongside metro proximity.",
    4: "Highlight distance markers with price-per-sqm comparison nearby.",
    5: "Add security checkpoint icons near station markers.",
    6: "Show building complex footprint on the transit map.",
    7: "Include 'direct access' walking path illustration from building to station.",
}

# 配图2: 房源亮点（所有天通用，微调）
FEATURE_BASE = (
    "Infographic card showcasing property highlights: "
    "4-bedroom 120sqm apartment, elevator 11th floor, raw condition with gas pipeline installed, "
    "large green certificate with village committee transfer. "
    "Flat vector icons, warm palette, clean layout with generous white space. "
    "Real estate feature comparison card."
)

FEATURE_DAY_HINTS = {
    1: "Lead with dual-metro badge as primary highlight.",
    2: "Lead with green certificate and village transfer as primary highlight.",
    3: "Lead with elevator and 11th floor as primary highlight.",
    4: "Lead with price tag 1.28M yuan as primary highlight.",
    5: "Lead with property rights and legal safety as primary highlight.",
    6: "Lead with unified construction quality and building standard as primary highlight.",
    7: "Lead with 'no agency fee' savings badge as primary highlight.",
}

# =============================================================================
# 日志配置
# =============================================================================
logger = logging.getLogger("baixing_image_gen")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(console_handler)


# =============================================================================
# 工具函数
# =============================================================================
def load_env():
    """从 ~/.hermes/.env 加载环境变量"""
    env_path = os.path.expanduser("~/.hermes/.env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def load_config():
    """加载发布配置"""
    if not os.path.exists(CONFIG_PATH):
        logger.error("配置文件不存在: %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_cover_prompt(day, title):
    """构建封面图 prompt"""
    keyword = DAY_COVER_KEYWORDS.get(day, "Premium real estate listing")
    visual = DAY_COVER_VISUALS.get(day, "")
    return (
        f"Professional real estate listing cover image. {keyword}. "
        f"Modern residential building exterior with metro station nearby "
        f"in Shenzhen Baoan district. {visual}. "
        f"Warm color palette with golden hour lighting. "
        f"Clean architectural illustration style. "
        f"Generous white space. "
        f"High quality real estate photography aesthetic."
    )


def build_transport_prompt(day):
    """构建交通配图 prompt"""
    hint = TRANSPORT_DAY_HINTS.get(day, "")
    return f"{TRANSPORT_BASE} {hint}"


def build_feature_prompt(day):
    """构建房源亮点配图 prompt"""
    hint = FEATURE_DAY_HINTS.get(day, "")
    return f"{FEATURE_BASE} {hint}"


# =============================================================================
# V2 Prompt 构建函数
# =============================================================================
def build_cover_prompt_v2(day, title, config):
    """构建 V2 封面图 prompt — baoyu-cover-image 5维度 (type/palette/rendering/text/mood)"""
    keyword = DAY_COVER_KEYWORDS.get(day, "Premium real estate listing")
    visual = DAY_COVER_VISUALS.get(day, "")
    return (
        f"Hero-type real estate cover image for a Shenzhen Baoan property listing.\n"
        f"{keyword}\n"
        f"Modern residential building exterior with metro station proximity.\n"
        f"{visual}\n"
        f"Warm color palette: golden hour lighting, amber and cream tones, soft terracotta accents.\n"
        f"Digital rendering: photorealistic architectural illustration with clean edges.\n"
        f"No text overlay. Clean composition with 50% breathing room.\n"
        f"Balanced mood: soft shadows, natural warmth, inviting atmosphere.\n"
        f"High quality real estate photography aesthetic. Professional listing standard."
    )


def build_illustration_prompt_v2(day, category, config):
    """构建 V2 配图 prompt — baoyu-article-illustrator Type×Style×Palette

    Args:
        day: 天数编号 (1-7)
        category: 'transport' 或 'feature'
        config: image_generation 配置字典
    """
    if category == "transport":
        hint = TRANSPORT_DAY_HINTS.get(day, "")
        return (
            f"Infographic illustration showing dual metro line connectivity for a Shenzhen Baoan property.\n"
            f"Metro Line 6 (Shangwu station 250m walk) and upcoming Line 13 (Shiyan station).\n"
            f"{hint}\n"
            f"Notion-style: warm cream background with subtle dot grid texture.\n"
            f"Warm palette: cream background (#FFF8F0), blue route lines (#4A90D9), orange accent (#E8913A).\n"
            f"Key distances and station names labeled with clean sans-serif font.\n"
            f"Walking distance icons, transit route lines in blue and orange.\n"
            f"Generous white space, information hierarchy with visual anchors.\n"
            f"Real estate transport highlight card, infographic format."
        )
    elif category == "feature":
        hint = FEATURE_DAY_HINTS.get(day, "")
        return (
            f"Comparison infographic card showcasing property highlights.\n"
            f"{hint}\n"
            f"Property specs: 4-bedroom 120sqm apartment, elevator 11th floor, raw condition with gas pipeline installed, "
            f"large green certificate with village committee transfer.\n"
            f"Minimal flat vector icons in warm palette: cream background, soft shadows, amber highlights.\n"
            f"Clean layout with generous white space, icon + label pairs arranged in grid.\n"
            f"Feature comparison with checkmark indicators and value highlights.\n"
            f"Real estate feature comparison card, comparison infographic format."
        )
    else:
        logger.warning("未知的 illustration category: %s, 回退到 transport", category)
        return build_illustration_prompt_v2(day, "transport", config)


# =============================================================================
# V3 动态 Prompt（V5.18.70 新增）
# 根据当天 description 抽取卖点，动态生成场景
# =============================================================================

# 卖点检测规则：(tag, keywords)
SELLING_POINT_RULES = [
    ("metro", ["地铁", "6号线", "13号线", "上屋站", "石岩站", "双地铁"]),
    ("property_rights", ["大绿本", "村委过户", "权属", "村委", "过户"]),
    ("price", ["128", "128万", "1.07万", "1.0万", "1.06万", "单价"]),
    ("layout", ["4房", "4室", "120平", "4室1厅", "120平方米", "大户型"]),
    ("elevator", ["电梯", "11楼", "11层", "高层", "18层"]),
    ("decoration", ["毛坯", "天然气", "管道", "装修"]),
    ("direct_sale", ["业主直售", "无中介", "自己名下", "看中可谈"]),
    ("surrounding", ["湿地公园", "体育中心", "沃尔玛", "天虹", "医院", "学校", "配套"]),
    ("convenience", ["生活配套", "出行便利", "成熟社区", "配套齐全"]),
    ("appreciation", ["升值", "投资", "未来", "潜力"]),
]

# 每个卖点对应的英文场景描述
SCENE_BY_POINT = {
    "metro": "modern high-rise residential building exterior with two intersecting metro line indicators, Shenzhen metro Line 6 (orange) and Line 13 (blue) routes converging, transit station platform visible in foreground with bilingual signage, evening urban Shenzhen skyline backdrop",
    "property_rights": "official property certificate document with prominent green cover and gold security seal, hands holding the certificate in trust gesture, legal document authenticity theme with stamp and signature elements",
    "price": "modern apartment building exterior with elegant price comparison overlay showing 1.28M yuan prominently, value-realization composition with subtle currency symbols and home icon",
    "layout": "spacious 4-bedroom apartment interior view: large open living room with floor-to-ceiling windows, separate bedroom doors visible, 120 square meter floor plan visualization from above with furniture arrangement, bright natural daylight",
    "elevator": "modern residential elevator interior with floor display showing 11, polished metal doors, building lobby with security desk and mailboxes, high-rise perspective looking up",
    "decoration": "empty raw apartment interior showing bare concrete walls and visible gas pipeline along ceiling, renovation-ready space with large windows letting in sunlight, potential showcase",
    "direct_sale": "property for-sale signboard in front of residential building, person holding key with confident smile, handshake element representing direct owner-to-buyer transaction, transparent dealing visual",
    "surrounding": "lush residential neighborhood scene: park with walking paths, shopping mall facade, hospital building with cross symbol, school with playground, all within walking distance from residential tower",
    "convenience": "vibrant mature community lifestyle: elderly people in park, families shopping at supermarket, morning commute scene, layered daily life illustration showing convenience",
    "appreciation": "upward trending graph overlay on city skyline with metro lines and value indicators, future potential visualization with sunrise lighting and growth arrow",
}


def extract_selling_points(description):
    """从 description 抽取关键卖点（按出现顺序，去重）

    Args:
        description: 当天 description 文本

    Returns:
        list of (tag, count) tuples, 按 count 降序
    """
    if not description:
        return []
    point_count = {}
    for tag, keywords in SELLING_POINT_RULES:
        count = sum(1 for k in keywords if k in description)
        if count > 0:
            point_count[tag] = count
    # 按 count 降序
    sorted_points = sorted(point_count.items(), key=lambda x: -x[1])
    return sorted_points


def build_cover_prompt_v3(day, title, description, config):
    """V3 动态 cover prompt — 从 description 抽取卖点动态生成场景

    Args:
        day: 天数 (1-7)
        title: 当天标题
        description: 当天描述（用于卖点抽取）
        config: image_generation 配置
    """
    points = extract_selling_points(description)
    # 最多取前 2 个卖点
    primary_tag = points[0][0] if points else "metro"
    secondary_tag = points[1][0] if len(points) > 1 else "layout"

    primary_scene = SCENE_BY_POINT.get(primary_tag, SCENE_BY_POINT["metro"])
    secondary_scene = SCENE_BY_POINT.get(secondary_tag, SCENE_BY_POINT["layout"])

    # 补充：原 DAY_COVER_VISUALS 作为视觉风格参考（保留品牌一致性）
    day_visual = DAY_COVER_VISUALS.get(day, "")

    return (
        f"Hero-type real estate cover image for a Shenzhen Baoan property listing.\n"
        f"PRIMARY selling point focus: {primary_scene}.\n"
        f"SECONDARY element: {secondary_scene}.\n"
        f"Day visual style: {day_visual}\n"
        f"Location: Shenzhen Baoan Shiyan district, near Shangwu station (Line 6) and upcoming Shiyan station (Line 13).\n"
        f"Warm color palette: golden hour lighting, amber and cream tones, soft terracotta accents.\n"
        f"Digital rendering: photorealistic architectural illustration with clean edges.\n"
        f"No text overlay. Clean composition with 50% breathing room.\n"
        f"Balanced mood: soft shadows, natural warmth, inviting atmosphere.\n"
        f"High quality real estate photography aesthetic. Professional listing standard."
    )


def build_illustration_prompt_v3(day, category, description, config):
    """V3 动态配图 prompt — 从 description 抽取场景

    Args:
        day: 天数
        category: 'transport' | 'feature'
        description: 当天描述
        config: 配置
    """
    points = extract_selling_points(description)
    point_tags = [p[0] for p in points[:3]] if points else ["metro"]

    if category == "transport":
        # 交通配图：focus metro
        metro_focus = "metro" in point_tags
        hint = TRANSPORT_DAY_HINTS.get(day, "")
        return (
            f"Infographic illustration showing dual metro line connectivity for a Shenzhen Baoan property.\n"
            f"Metro Line 6 (Shangwu station 250m walk) and upcoming Line 13 (Shiyan station).\n"
            f"{hint}\n"
            f"Notion-style: warm cream background with subtle dot grid texture.\n"
            f"Warm palette: cream background (#FFF8F0), blue route lines (#4A90D9), orange accent (#E8913A).\n"
            f"Key distances and station names labeled with clean sans-serif font.\n"
            f"Walking distance icons, transit route lines in blue and orange.\n"
            f"{'Emphasis: Metro convenience is the primary selling point today.' if metro_focus else ''}\n"
            f"Generous white space, information hierarchy with visual anchors.\n"
            f"Real estate transport highlight card, infographic format."
        )
    elif category == "feature":
        # 亮点配图：focus 当天 top 3 卖点
        top_points = ", ".join(point_tags[:3]) if point_tags else "metro, layout, elevator"
        hint = FEATURE_DAY_HINTS.get(day, "")
        return (
            f"Comparison infographic card showcasing property highlights.\n"
            f"Today's top selling points (from listing): {top_points}.\n"
            f"{hint}\n"
            f"Property specs: 4-bedroom 120sqm apartment, elevator 11th floor, raw condition with gas pipeline installed, "
            f"large green certificate with village committee transfer.\n"
            f"Minimal flat vector icons in warm palette: cream background, soft shadows, amber highlights.\n"
            f"Clean layout with generous white space, icon + label pairs arranged in grid.\n"
            f"Feature comparison with checkmark indicators and value highlights.\n"
            f"Real estate feature comparison card, comparison infographic format."
        )
    else:
        logger.warning("未知的 illustration category: %s, 回退到 transport", category)
        return build_illustration_prompt_v3(day, "transport", description, config)


def progress_bar(current, total, prefix="", width=40):
    """简易进度条"""
    pct = current / total
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {current}/{total} ({pct:.0%})")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


def generate_image(prompt, output_path, aspect, quality, minimax_key, dry_run=False):
    """
    调用 baoyu-imagine CLI 生成单张图片。
    返回 (success: bool, output_path or None)
    """
    if dry_run:
        logger.info("[DRY-RUN] prompt: %s", prompt)
        logger.info("[DRY-RUN] output: %s  aspect: %s  quality: %s", output_path, aspect, quality)
        return True, output_path

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "npx", "-y", "bun",
        IMAGINE_SCRIPT,
        "--prompt", prompt,
        "--image", output_path,
        "--provider", "minimax",
        "--ar", aspect,
        "--quality", quality,
    ]

    env = os.environ.copy()
    env["MINIMAX_API_KEY"] = minimax_key
    env["MINIMAX_BASE_URL"] = "https://api.minimax.chat/v1"

    for attempt in range(1, MAX_RETRIES + 1):
        logger.debug(
            "生成图片 attempt %d/%d: %s", attempt, MAX_RETRIES, output_path
        )
        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                size_kb = os.path.getsize(output_path) / 1024
                logger.info(
                    "✓ 生成成功: %s (%.0fKB)", output_path, size_kb
                )
                return True, output_path
            else:
                logger.warning(
                    "✗ 生成失败 (attempt %d): %s\nstdout: %s\nstderr: %s",
                    attempt, output_path,
                    result.stdout[:500] if result.stdout else "",
                    result.stderr[:500] if result.stderr else "",
                )
        except subprocess.TimeoutExpired:
            logger.warning("✗ 超时 (attempt %d): %s", attempt, output_path)
        except Exception as e:
            logger.warning("✗ 异常 (attempt %d): %s - %s", attempt, output_path, e)

        if attempt < MAX_RETRIES:
            logger.debug("等待 %d 秒后重试...", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    logger.error("✗ 放弃生成 (已重试%d次): %s", MAX_RETRIES, output_path)
    return False, None


def generate_day(day_num, config, minimax_key, dry_run=False):
    """为指定日期生成所有图片，返回成功生成的路径列表"""
    schedule = config.get("schedule", [])
    day_entry = None
    for s in schedule:
        if s.get("day") == day_num:
            day_entry = s
            break

    if not day_entry:
        logger.error("未找到第 %d 天的配置", day_num)
        return []

    title = day_entry.get("title", "")
    img_cfg = config.get("image_generation", {})
    cover_cfg = img_cfg.get("cover", {})
    illust_cfg = img_cfg.get("illustrations", {})

    cover_aspect = cover_cfg.get("aspect", "16:9")
    cover_quality = cover_cfg.get("quality", "2k")
    illust_aspect = illust_cfg.get("aspect", "4:3")
    illust_quality = illust_cfg.get("quality", "normal")

    day_dir = os.path.join(OUTPUT_BASE, f"day{day_num}")
    generated = []

    # prompt 版本切换 (v1=原始, v2=5维度/Type×Style×Palette, v3_dynamic=动态卖点)
    prompt_version = img_cfg.get("prompt_version", "v1")

    # 任务列表: (name, prompt, filename, aspect, quality)
    if prompt_version == "v3_dynamic":
        cover_prompt = build_cover_prompt_v3(day_num, title, day_entry.get("description", ""), img_cfg)
        transport_prompt = build_illustration_prompt_v3(day_num, "transport", day_entry.get("description", ""), img_cfg)
        feature_prompt = build_illustration_prompt_v3(day_num, "feature", day_entry.get("description", ""), img_cfg)
    elif prompt_version == "v2":
        cover_prompt = build_cover_prompt_v2(day_num, title, img_cfg)
        transport_prompt = build_illustration_prompt_v2(day_num, "transport", img_cfg)
        feature_prompt = build_illustration_prompt_v2(day_num, "feature", img_cfg)
    else:
        cover_prompt = build_cover_prompt(day_num, title)
        transport_prompt = build_transport_prompt(day_num)
        feature_prompt = build_feature_prompt(day_num)

    tasks = [
        (
            "封面图",
            cover_prompt,
            os.path.join(day_dir, "cover.png"),
            cover_aspect,
            cover_quality,
        ),
        (
            "交通配图",
            transport_prompt,
            os.path.join(day_dir, "illust_transport.png"),
            illust_aspect,
            illust_quality,
        ),
        (
            "亮点配图",
            feature_prompt,
            os.path.join(day_dir, "illust_feature.png"),
            illust_aspect,
            illust_quality,
        ),
    ]

    logger.info("=" * 60)
    logger.info("Day %d: %s", day_num, title)
    logger.info("=" * 60)

    for i, (name, prompt, path, aspect, quality) in enumerate(tasks):
        progress_bar(i, len(tasks), prefix=f"Day{day_num}")
        logger.info("生成 %s → %s", name, os.path.basename(path))
        success, result_path = generate_image(
            prompt, path, aspect, quality, minimax_key, dry_run=dry_run
        )
        if success:
            generated.append(result_path)
        progress_bar(i + 1, len(tasks), prefix=f"Day{day_num}")

    return generated


def get_today_day_number(config):
    """根据星期几确定今天的 day 编号 (1=周一, 7=周日)"""
    weekday = datetime.now().weekday()  # 0=Monday
    day_num = weekday + 1
    schedule = config.get("schedule", [])
    valid_days = {s.get("day") for s in schedule}
    if day_num in valid_days:
        return day_num
    # 如果今天不在计划中，返回最近的
    if valid_days:
        return min(valid_days, key=lambda d: abs(d - day_num))
    return 1


def main():
    # 解析命令行参数
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # 加载配置和环境
    config = load_config()
    env = load_env()

    minimax_key = env.get("MINIMAX_CN_API_KEY", "")
    if not minimax_key and not dry_run:
        logger.error("未找到 MINIMAX_CN_API_KEY，请在 ~/.hermes/.env 中配置")
        sys.exit(1)

    # 检查 image_generation 是否启用
    img_cfg = config.get("image_generation", {})
    if not img_cfg.get("enabled", True) and not dry_run:
        logger.info("图片生成未启用 (image_generation.enabled=false)")
        sys.exit(0)

    # 确定要生成的天数
    if not args:
        # 默认: 生成今天
        target_days = [get_today_day_number(config)]
    elif args[0] == "all":
        target_days = list(range(1, 8))
    else:
        try:
            target_days = [int(args[0])]
        except ValueError:
            logger.error("无效参数: %s (使用 all 或 1-7)", args[0])
            sys.exit(1)

    # 验证天数
    schedule_days = {s.get("day") for s in config.get("schedule", [])}
    for d in target_days:
        if d not in schedule_days:
            logger.warning("第 %d 天不在配置中，跳过", d)
    target_days = [d for d in target_days if d in schedule_days]

    if not target_days:
        logger.error("没有有效的生成目标")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("百姓网图片生成器")
    logger.info("目标: Day %s", ", ".join(str(d) for d in target_days))
    logger.info("模式: %s", "DRY-RUN" if dry_run else "生成")
    logger.info("输出目录: %s", OUTPUT_BASE)
    logger.info("=" * 60)

    # 生成图片
    total_tasks = len(target_days) * 3
    all_generated = []
    total_done = 0

    for day_num in target_days:
        generated = generate_day(day_num, config, minimax_key, dry_run=dry_run)
        all_generated.extend(generated)
        total_done += 3

    # 总结
    logger.info("")
    logger.info("=" * 60)
    logger.info("生成完毕！成功 %d/%d 张图片", len(all_generated), total_tasks)
    logger.info("=" * 60)

    if all_generated:
        logger.info("生成的图片路径:")
        for p in all_generated:
            logger.info("  %s", p)

    # 输出 JSON 路径列表供 publisher 脚本读取
    if not dry_run and all_generated:
        list_path = os.path.join(OUTPUT_BASE, "generated_images.json")
        os.makedirs(OUTPUT_BASE, exist_ok=True)
        # 按天组织
        images_by_day = {}
        for p in all_generated:
            # 从路径提取 day 编号: .../day3/cover.png
            parts = p.split(os.sep)
            for part in parts:
                if part.startswith("day") and part[3:].isdigit():
                    d = int(part[3:])
                    images_by_day.setdefault(d, []).append(p)
                    break
        with open(list_path, "w", encoding="utf-8") as f:
            json.dump(images_by_day, f, ensure_ascii=False, indent=2)
        logger.info("图片列表已保存到: %s", list_path)

    return 0 if len(all_generated) == total_tasks else 1


if __name__ == "__main__":
    sys.exit(main())

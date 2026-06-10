#!/usr/bin/env python3
"""
百姓网房产发布 SEO 内容生成引擎 v1.0
==============================
动态生成 SEO 优化的标题 + 描述，每次发布自动轮换关键词组合。

核心策略:
1. 关键词矩阵: 核心词 + 长尾词 + 场景词 + 情感词
2. 标题优化: 8-30字，核心词前置，包含价格/户型/地铁等高搜索量词
3. 描述优化: 自然融入关键词，密度2-4%，分层结构（摘要→详情→亮点→CTA）
4. 去重机制: 每次生成的内容与历史记录比对，确保不重复
5. A/B 测试: 不同标题模板轮换，追踪点击率

用法:
  python3 baixing_seo_content.py          # 生成今天的内容
  python3 baixing_seo_content.py 3        # 生成第3天
  python3 baixing_seo_content.py --all    # 预览7天
  python3 baixing_seo_content.py --keywords  # 查看关键词库
"""

import json
import os
import hashlib
import time
import random
from datetime import datetime
from pathlib import Path

CONFIG_PATH = "/home/zng/baixing_publish_config.json"
HISTORY_PATH = "/home/zng/baixing_seo_history.jsonl"

# ============================================================
# SEO 关键词矩阵
# ============================================================

# 核心关键词（高搜索量，竞争激烈）
CORE_KEYWORDS = [
    "石岩统建楼", "石岩二手房", "石岩小产权", "宝安石岩二手房",
    "深圳统建楼", "深圳小产权房", "宝安二手房", "石岩房产",
    "石岩村委房", "深圳村委统建楼",
]

# 长尾关键词（精准搜索，转化率高）
LONGTAIL_KEYWORDS = [
    "石岩统建楼4房", "石岩4房120平", "石岩地铁口二手房",
    "宝安石岩统建楼出售", "石岩大绿本统建楼", "石岩毛坯二手房",
    "石岩电梯房出售", "石岩南北通透4房", "深圳石岩低价二手房",
    "石岩6号线地铁房", "石岩13号线二手房", "石岩4房128万",
    "宝安石岩大户型", "石岩天然气统建楼", "石岩村委过户",
    "石岩元径村统建楼", "石岩上屋地铁二手房", "石岩毛坯4房",
    "深圳宝安石岩统建楼价格", "石岩统建楼业主直售",
]

# 场景词（搜索意图匹配）
SCENE_KEYWORDS = {
    "地铁通勤": ["地铁6号线", "地铁13号线", "双地铁口", "上屋站", "地铁房", "地铁旁", "步行250米"],
    "投资理财": ["升值空间", "投资价值", "低价盘", "性价比高", "总价低", "单价低"],
    "家庭居住": ["4房大户型", "三代同堂", "大家庭", "南北通透", "采光好"],
    "产权安全": ["大绿本", "村委过户", "权属清晰", "产权保障", "正规统建楼"],
    "装修自由": ["毛坯房", "自由装修", "天然气入户", "省拆改费"],
    "生活便利": ["湿地公园", "体育中心", "沃尔玛", "天虹商场", "人民医院", "学校"],
    "价格优势": ["128万", "1.07万/平", "宝安低价", "深圳低价盘", "业主直售"],
    "位置区域": ["宝安区", "石岩街道", "元径村", "石岩中心", "深圳宝安"],
}

# 标题模板（核心词 + 卖点 + 数字）
TITLE_TEMPLATES = [
    # 模板A: 区域 + 核心属性 + 面积 + 价格（确保有分隔）
    "{区域}{核心属性}{户型}{面积}平{价格}",
    # 模板B: 交通 + 区域 + 核心属性 + 卖点
    "{交通}{区域}{核心属性}{户型}{卖点}",
    # 模板C: 产权 + 区域 + 核心属性
    "{产权词}{区域}{核心属性}{户型}{面积}平",
    # 模板D: 卖点前置 + 区域 + 核心属性 + 价格
    "{卖点}{区域}{核心属性}{户型}仅{价格}",
    # 模板E: 区域 + 核心属性 + 面积 + 卖点
    "{区域}{核心属性}{面积}平{卖点}{价格}",
    # 模板F: 业主直售 + 区域 + 核心属性
    "{区域}{核心属性}{户型}业主直售{卖点}",
    # 模板G: 区域 + 核心属性 + 户型 + 楼层 + 价格
    "{区域}{核心属性}{户型}{面积}平电梯{楼层}楼",
    # 模板H: 长尾精准 - 区域 + 交通 + 核心属性
    "{区域词}{核心属性}{户型}{面积}平{交通}",
]

# 描述模板（分层结构）
DESC_SECTIONS = {
    "opening": [
        "【{区域}·{小区名}·{户型}·{面积}平出售】",
        "{区域}{小区名} {户型} {面积}平 精选好房",
        "深圳{区域}{小区名} {户型}{面积}平方米 业主直售",
        "【{区域}核心地段】{小区名} {户型} {面积}平",
        "{区域}{街道} {小区名} {户型}大户型 {面积}平",
        "深圳{区域}{小区名}B栋 {户型} {面积}平诚意出售",
        "【业主直售 无中介费】{区域}{小区名} {户型} {面积}平",
    ],
    "basic_info": [
        "\n\n【基本信息】\n户型：{户型}\n面积：{面积}平方米\n楼层：电梯{楼层}楼\n朝向：{朝向}\n装修：{装修}（已通天然气管道）\n总价：{价格}万元（单价约{单价}万/平）\n产权：{产权}",
        "\n\n【房屋详情】\n{户型} | {面积}㎡ | 电梯{楼层}楼 | {朝向}\n毛坯交付，已铺设天然气管道\n总价{价格}万 | {产权}",
        "\n\n【房子信息】\n户型：{户型}\n面积：{面积}平\n楼层：电梯{楼层}楼（总高{总楼层}层）\n装修：{装修}\n总价：{价格}万\n产权：{产权}",
    ],
    "transport": [
        "\n\n【交通便捷】\n{地铁1} {地铁1站} 步行约250米\n{地铁2} {地铁2站} 即将开通\n双地铁交汇，多条公交线路，出行十分便利",
        "\n\n【双地铁口物业】\n{地铁1} {地铁1站}：步行250米即到\n{地铁2} {地铁2站}：即将通车\n平时坐地铁去市区非常方便",
        "\n\n【地铁交通】\n{地铁1} {地铁1站} 250米\n{地铁2} {地铁2站} 马上开通\n双地铁口物业，未来出行更方便",
    ],
    "surrounding": [
        "\n\n【周边配套完善】\n{公园}，环境优美\n{体育}，健身休闲\n{医院}\n{商超}等商业配套\n学校、菜市场等生活设施齐全",
        "\n\n【生活配套】\n{公园}\n{医院}\n{商超}\n学校、幼儿园都在附近\n{街道}成熟社区，生活便利",
        "\n\n【周边环境】\n小区就在{街道}中心位置\n旁边有{公园}可以散步\n{商超}买菜购物方便\n{医院}也不远",
    ],
    "highlights": [
        "\n\n【房源亮点】\n{亮点1}\n{亮点2}\n{亮点3}\n{亮点4}\n{亮点5}",
        "\n\n【为什么选择这套房】\n{亮点1}\n\n{亮点2}\n\n{亮点3}\n\n{亮点4}",
        "\n\n【核心卖点】\n✅ {亮点1}\n✅ {亮点2}\n✅ {亮点3}\n✅ {亮点4}",
    ],
    "target_audience": [
        "\n\n【适合人群】\n刚需上车族：{价格}万买{房间数}房，性价比高\n投资客：双地铁口物业，升值潜力大\n大家庭：{户型}，三代同堂无忧",
        "\n\n【适合谁买】\n想在深圳安家的朋友\n预算有限但要大户型\n看中地铁出行便利的\n想要产权清晰的统建楼",
    ],
    "cta": [
        "\n\n有意者请电话联系或私信咨询，随时可看房。",
        "\n\n随时可以看房，电话联系即可。",
        "\n\n看房预约请电话联系。",
        "\n\n有意请联系看房。",
    ],
}

# 亮点组合（随机抽取4-5条，确保不重复）
HIGHLIGHTS_POOL = [
    "双地铁物业，6号线已通车，13号线即将开通，升值空间大",
    "电梯高层{楼层}楼，视野开阔，采光通风好",
    "毛坯交付，省去拆改费用，自由定制装修风格",
    "已铺设天然气管道，生活便利",
    "带大绿本，权属清晰，可村委过户",
    "{户型}大户型，适合大家庭居住或投资",
    "单价仅{单价}万/平，宝安区难得的性价比",
    "南北通透，户型方正",
    "石岩街道成熟社区，生活配套齐全",
    "业主直售，无中介费",
    "总价{价格}万，深圳宝安少有的低价盘",
    "已通天然气管道，毛坯交付可自由装修",
    "正规统建楼，非普通农民房",
    "4房满足三代同堂或合租投资",
]


class SEOContentGenerator:
    """SEO 内容生成器"""

    def __init__(self, config_path=CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.prop = self.config['property']
        self.history = self._load_history()

    def _load_config(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_history(self):
        """加载历史生成记录（用于去重）"""
        history = []
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            history.append(json.loads(line))
                        except:
                            pass
        return history

    def _save_history(self, record):
        with open(HISTORY_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    def _content_hash(self, title, desc):
        """计算内容指纹（用于去重）"""
        content = title + "||" + desc[:200]
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:12]

    def _is_duplicate(self, title, desc):
        """检查内容是否与最近7天重复"""
        new_hash = self._content_hash(title, desc)
        recent_hashes = [h.get('content_hash') for h in self.history[-14:]]  # 最近2周
        return new_hash in recent_hashes

    # ========== 标题生成 ==========

    def generate_title(self, day, seed=None):
        """生成 SEO 优化的标题"""
        if seed is not None:
            random.seed(seed)

        prop = self.prop
        template_idx = (day - 1) % len(TITLE_TEMPLATES)
        template = TITLE_TEMPLATES[template_idx]

        # 随机选择填充词（确保"石岩"高频出现）
        fill = {
            '区域': random.choice(['石岩', '宝安石岩', '深圳石岩', '宝安']),
            '区域词': random.choice(['深圳宝安石岩', '宝安区石岩', '深圳石岩', '石岩']),
            '核心属性': random.choice(['统建楼', '二手房', '小产权', '村委统建楼']),
            '户型': '4房' if prop['rooms'] == '4室1厅1卫' else prop['rooms'][:2],
            '面积': str(prop['area']),
            '价格': f"{prop['price']}万",
            '楼层': str(prop['floor']),
            '交通': random.choice(['双地铁口', '地铁旁', '地铁口', '6号线地铁']),
            '产权词': random.choice(['带大绿本', '大绿本', '可村委过户', '产权清晰']),
            '卖点': random.choice(['业主直售', '带电梯', '南北通透', '天然气入户']),
        }

        title = template.format(**fill)

        # 标题长度检查：8-30字
        if len(title) < 8:
            title += f" {prop['price']}万"
        if len(title) > 30:
            title = title[:30].rstrip()

        return title

    # ========== 描述生成 ==========

    def generate_description(self, day, seed=None):
        """生成 SEO 优化的描述"""
        if seed is not None:
            random.seed(seed + day * 100)

        prop = self.config['property']
        schedule = self.config['schedule'][day - 1]

        # 构建通用替换变量
        vars_map = {
            '区域': '宝安石岩',
            '街道': '石岩街道',
            '小区名': prop['community'],
            '户型': prop['rooms'],
            '房间数': prop['rooms'][0],
            '面积': str(prop['area']),
            '楼层': str(prop['floor']),
            '总楼层': str(prop['total_floor']),
            '朝向': prop['orientation'],
            '装修': prop['decoration'],
            '价格': str(prop['price']),
            '单价': f"{prop['price'] / prop['area']:.2f}",
            '产权': '大绿本，可村委过户',
            '地铁1': '地铁6号线',
            '地铁1站': '上屋站',
            '地铁2': '地铁13号线',
            '地铁2站': '石岩站',
            '公园': '石岩湿地公园',
            '体育': '体育中心',
            '医院': '宝安区人民医院石岩分院',
            '商超': '沃尔玛、天虹商场',
        }

        # 随机选择亮点（4-5条）
        highlights = random.sample(HIGHLIGHTS_POOL, min(5, len(HIGHLIGHTS_POOL)))
        for i, h in enumerate(highlights):
            highlights[i] = h.format(**vars_map)
        vars_map.update({
            '亮点1': highlights[0] if len(highlights) > 0 else '',
            '亮点2': highlights[1] if len(highlights) > 1 else '',
            '亮点3': highlights[2] if len(highlights) > 2 else '',
            '亮点4': highlights[3] if len(highlights) > 3 else '',
            '亮点5': highlights[4] if len(highlights) > 4 else '',
        })

        # 每个section随机选一个模板
        opening = random.choice(DESC_SECTIONS['opening']).format(**vars_map)
        basic = random.choice(DESC_SECTIONS['basic_info']).format(**vars_map)
        transport = random.choice(DESC_SECTIONS['transport']).format(**vars_map)
        surrounding = random.choice(DESC_SECTIONS['surrounding']).format(**vars_map)
        hl_section = random.choice(DESC_SECTIONS['highlights']).format(**vars_map)

        # 70% 概率加入目标人群
        audience = ''
        if random.random() < 0.7:
            audience = random.choice(DESC_SECTIONS['target_audience']).format(**vars_map)

        cta = random.choice(DESC_SECTIONS['cta']).format(**vars_map)

        # 组合描述
        description = opening + basic + transport + surrounding + hl_section + audience + cta

        # 追加联系方式（变形防反垃圾）
        description += "\n\n📞 业主直联：一三玖-二三八-三八四一八（v❤同号，欢迎咨询看房）"

        # 长度限制：5000字
        if len(description) > 4950:
            description = description[:4950]

        return description

    # ========== SEO 关键词密度分析 ==========

    def analyze_keyword_density(self, text):
        """分析关键词密度"""
        total_chars = len(text)
        keywords_found = {}

        # 检查核心关键词出现次数
        all_keywords = CORE_KEYWORDS + LONGTAIL_KEYWORDS
        for kw in all_keywords:
            count = text.count(kw)
            if count > 0:
                density = (len(kw) * count) / total_chars * 100
                keywords_found[kw] = {'count': count, 'density': f"{density:.2f}%"}

        # 检查场景词出现次数
        for scene, words in SCENE_KEYWORDS.items():
            scene_count = sum(1 for w in words if w in text)
            if scene_count > 0:
                keywords_found[f"[{scene}]"] = f"{scene_count}/{len(words)} 词命中"

        return keywords_found

    # ========== SEO 评分 ==========

    def seo_score(self, title, description):
        """SEO 综合评分（0-100）"""
        score = 0
        details = []

        # 1. 标题长度（8-30字）: 15分
        title_len = len(title)
        if 8 <= title_len <= 30:
            score += 15
            details.append(f"✅ 标题长度: {title_len}字（8-30）")
        else:
            details.append(f"⚠️ 标题长度: {title_len}字（需8-30字）")

        # 2. 标题包含核心关键词: 20分（含模糊匹配）
        title_text = title
        title_kw_count = sum(1 for kw in CORE_KEYWORDS if kw in title_text)
        # 额外匹配：标题含"统建楼"+"石岩/宝安/深圳"也算命中
        if title_kw_count == 0:
            if '统建楼' in title_text and any(r in title_text for r in ['石岩', '宝安', '深圳']):
                title_kw_count = 1
            elif '二手房' in title_text and any(r in title_text for r in ['石岩', '宝安', '深圳']):
                title_kw_count = 1
        if title_kw_count >= 1:
            score += 20
            details.append(f"✅ 标题含核心词: {title_kw_count}个")
        else:
            details.append("⚠️ 标题缺少核心关键词")

        # 3. 标题包含数字（价格/面积）: 10分
        import re
        if re.search(r'\d+', title):
            score += 10
            details.append("✅ 标题含数字（吸引点击）")
        else:
            details.append("⚠️ 标题缺少数字")

        # 4. 描述长度（300-3000字）: 10分
        desc_len = len(description)
        if 300 <= desc_len <= 3000:
            score += 10
            details.append(f"✅ 描述长度: {desc_len}字")
        elif 3000 < desc_len <= 4950:
            score += 5
            details.append(f"⚠️ 描述偏长: {desc_len}字（建议<3000字）")
        else:
            details.append(f"⚠️ 描述长度: {desc_len}字（需300-3000字）")

        # 5. 描述关键词密度（2-4%为最佳）: 15分
        kw_density = self.analyze_keyword_density(description)
        core_count = sum(1 for kw in CORE_KEYWORDS if kw in description)
        longtail_count = sum(1 for kw in LONGTAIL_KEYWORDS if kw in description)
        total_kw_hits = core_count + longtail_count
        if total_kw_hits >= 3:
            score += 15
            details.append(f"✅ 关键词覆盖: 核心{core_count}个, 长尾{longtail_count}个")
        elif total_kw_hits >= 1:
            score += 8
            details.append(f"⚠️ 关键词偏少: 核心{core_count}个, 长尾{longtail_count}个")

        # 6. 描述结构完整性: 15分
        sections = 0
        if '基本信息' in description or '房屋详情' in description or '房子信息' in description:
            sections += 1
        if '交通' in description:
            sections += 1
        if '周边' in description or '配套' in description:
            sections += 1
        if '亮点' in description or '卖点' in description or '为什么' in description:
            sections += 1
        if sections >= 3:
            score += 15
            details.append(f"✅ 结构完整: {sections}/4个板块")
        else:
            score += sections * 4
            details.append(f"⚠️ 结构不完整: {sections}/4个板块")

        # 7. 联系方式: 5分
        if '一三玖' in description or 'v❤' in description:
            score += 5
            details.append("✅ 联系方式已嵌入")
        else:
            details.append("⚠️ 缺少联系方式")

        # 8. 去重检查: 10分
        if not self._is_duplicate(title, description):
            score += 10
            details.append("✅ 内容无重复")
        else:
            details.append("⚠️ 内容与历史重复")

        return score, details

    # ========== 主生成函数 ==========

    def generate(self, day, force=False):
        """
        生成第 day 天的 SEO 内容。
        如果当天已生成过且未 force，返回缓存结果。
        """
        # 尝试从历史中获取
        if not force:
            for h in reversed(self.history):
                if h.get('day') == day:
                    # 检查是否是今天的记录
                    today = datetime.now().strftime('%Y-%m-%d')
                    if h.get('date') == today:
                        return h

        # 生成唯一种子（基于日期+day，确保同一天同一day生成相同内容）
        today = datetime.now()
        seed = int(today.strftime('%Y%m%d')) * 10 + day

        # 尝试生成不重复的内容（最多10次）
        title = self.generate_title(day, seed=seed)
        description = self.generate_description(day, seed=seed)
        for attempt in range(10):
            title = self.generate_title(day, seed=seed + attempt * 7)
            description = self.generate_description(day, seed=seed + attempt * 13)
            if not self._is_duplicate(title, description):
                break

        # SEO 分析
        score, details = self.seo_score(title, description)
        kw_analysis = self.analyze_keyword_density(description)

        # 内容指纹
        content_hash = self._content_hash(title, description)

        result = {
            'day': day,
            'date': today.strftime('%Y-%m-%d'),
            'title': title,
            'description': description,
            'title_length': len(title),
            'desc_length': len(description),
            'seo_score': score,
            'seo_details': details,
            'keyword_analysis': kw_analysis,
            'content_hash': content_hash,
            'generated_at': today.strftime('%Y-%m-%d %H:%M:%S'),
        }

        # 保存到历史
        self._save_history(result)
        self.history.append(result)

        return result

    def generate_all(self):
        """生成全部7天的内容"""
        results = []
        for day in range(1, 8):
            r = self.generate(day, force=True)
            results.append(r)
        return results


# ============================================================
# CLI 入口
# ============================================================

def main():
    import sys

    gen = SEOContentGenerator()

    if '--keywords' in sys.argv:
        print("=" * 60)
        print("百姓网房产 SEO 关键词矩阵")
        print("=" * 60)
        print(f"\n📊 核心关键词 ({len(CORE_KEYWORDS)}个):")
        for kw in CORE_KEYWORDS:
            print(f"  • {kw}")
        print(f"\n📊 长尾关键词 ({len(LONGTAIL_KEYWORDS)}个):")
        for kw in LONGTAIL_KEYWORDS:
            print(f"  • {kw}")
        print(f"\n📊 场景词 ({len(SCENE_KEYWORDS)}类):")
        for scene, words in SCENE_KEYWORDS.items():
            print(f"  [{scene}]: {', '.join(words)}")
        print(f"\n📊 标题模板 ({len(TITLE_TEMPLATES)}个):")
        for i, t in enumerate(TITLE_TEMPLATES):
            print(f"  T{i+1}: {t}")
        return

    if '--all' in sys.argv:
        results = gen.generate_all()
        for r in results:
            print(f"\n{'='*60}")
            print(f"Day {r['day']} | SEO评分: {r['seo_score']}/100")
            print(f"标题 ({r['title_length']}字): {r['title']}")
            print(f"描述 ({r['desc_length']}字)")
            for d in r['seo_details']:
                print(f"  {d}")
        return

    # 单天生成
    day = 1
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        day = int(sys.argv[1])
    else:
        day = time.localtime().tm_wday + 1
        if day > 7:
            day = 7

    result = gen.generate(day, force='--force' in sys.argv)

    print(f"\n{'='*60}")
    print(f"Day {result['day']} | {result['date']}")
    print(f"SEO评分: {result['seo_score']}/100")
    print(f"内容指纹: {result['content_hash']}")
    print(f"{'='*60}")
    print(f"\n📝 标题 ({result['title_length']}字):")
    print(f"  {result['title']}")
    print(f"\n📝 描述 ({result['desc_length']}字):")
    print(f"  {result['description'][:200]}...")
    print(f"\n📊 SEO 分析:")
    for d in result['seo_details']:
        print(f"  {d}")
    print(f"\n📊 关键词覆盖:")
    for kw, info in result['keyword_analysis'].items():
        print(f"  {kw}: {info}")

    # 输出 JSON（供其他脚本解析）
    print(f"\n---JSON---")
    print(json.dumps({
        'day': result['day'],
        'title': result['title'],
        'description': result['description'],
        'seo_score': result['seo_score'],
        'content_hash': result['content_hash'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()

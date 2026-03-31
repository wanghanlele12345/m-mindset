import time
import random
import sqlite3
import hashlib
import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import uiautomator2 as u2

# ======================== 配置 ========================
DEVICE_SERIAL = "127.0.0.1:16384"
OUTPUT_DIR = Path("output")
DB_FILE = OUTPUT_DIR / "books.db"
LOG_FILE = OUTPUT_DIR / "progress.log"

SCROLL_WAIT = 2.5
MAX_SCROLLS_PER_RANGE = 2000
DEFAULT_RANGES = [f"{i}-{i+1}" for i in range(9, -1, -1)]


# ======================== Shell 级触控操作 ========================
# 使用 adb shell input 命令，避免 INJECT_EVENTS 权限问题

def shell_tap(d, x, y):
    d.shell(f"input tap {int(x)} {int(y)}")

def shell_swipe(d, x1, y1, x2, y2, duration_ms=2000):
    d.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

def get_node_center(element):
    info = element.info
    bounds = info.get('bounds') or info.get('visibleBounds')
    if bounds:
        return (bounds['left'] + bounds['right']) // 2, (bounds['top'] + bounds['bottom']) // 2
    return None, None

def click_element(d, element):
    cx, cy = get_node_center(element)
    if cx is not None:
        shell_tap(d, cx, cy)
        return True
    return False


# ======================== pub_info 解析 ========================

def parse_pub_info(pub_info):
    """
    智能解析豆瓣出版信息字符串。
    格式多变，常见模式:
      - 作者 / 出版社 / 日期 / 价格      (4段)
      - 作者 / 译者 / 出版社 / 日期 / 价格 (5段)
      - 作者 / 出版社 / 日期              (3段)
      - 作者 / 日期 / 出版社              (3段，顺序不固定)
    """
    result = {"author": "", "publisher": "", "pub_date": "", "price": ""}
    if not pub_info:
        return result

    parts = [p.strip() for p in pub_info.split("/")]
    if not parts:
        return result

    # 辅助函数：判断是否像日期
    def looks_like_date(s):
        return bool(re.search(r'(19|20)\d{2}', s))

    # 辅助函数：判断是否像价格
    def looks_like_price(s):
        return bool(re.search(r'[\d.]+\s*(元|¥|￥|CNY)?', s) and not looks_like_date(s))

    # 辅助函数：判断是否像出版社
    def looks_like_publisher(s):
        keywords = ['出版', '书局', '书社', '书店', '书院', '印书馆', '文艺', '文化',
                     'Press', 'Publisher', '三联', '中华', '商务', '人民', '大学',
                     '译文', '世纪', '读书', '新知', '联合', '中信', '新星']
        return any(k in s for k in keywords)

    if len(parts) == 1:
        result["author"] = parts[0]
    elif len(parts) == 2:
        result["author"] = parts[0]
        if looks_like_date(parts[1]):
            result["pub_date"] = parts[1]
        else:
            result["publisher"] = parts[1]
    elif len(parts) == 3:
        # 作者 / 出版社 / 日期  或  作者 / 日期 / 出版社
        result["author"] = parts[0]
        if looks_like_date(parts[1]):
            result["pub_date"] = parts[1]
            result["publisher"] = parts[2]
        elif looks_like_date(parts[2]):
            result["publisher"] = parts[1]
            result["pub_date"] = parts[2]
        else:
            result["publisher"] = parts[1]
            result["pub_date"] = parts[2]
    elif len(parts) >= 4:
        # 从右侧开始识别：价格(可选) / 日期 / 出版社 / 剩余为作者(+译者)
        idx = len(parts) - 1

        # 最右边：如果像价格就是价格
        if looks_like_price(parts[idx]):
            result["price"] = parts[idx]
            idx -= 1

        # 日期
        if idx >= 1 and looks_like_date(parts[idx]):
            result["pub_date"] = parts[idx]
            idx -= 1

        # 出版社
        if idx >= 1:
            result["publisher"] = parts[idx]
            idx -= 1

        # 剩余部分全部作为作者（可能含译者）
        if idx >= 0:
            result["author"] = " / ".join(parts[:idx + 1])

    return result


# ======================== 排序与筛选 ========================

def set_sort_by_time(d):
    """点击"时间"排序按钮"""
    print("--- 设置排序方式: 按时间 ---")
    time_btn = d(text="时间", className="android.widget.TextView")
    if time_btn.exists(timeout=3):
        click_element(d, time_btn)
        time.sleep(2)
        print("✓ 已切换为按时间排序")
    else:
        print("⚠ 未找到时间排序按钮")


def open_filter_panel(d):
    """点击筛选图标打开筛选面板"""
    filter_bar = d(resourceId="com.douban.frodo:id/filter_bar")
    if filter_bar.exists(timeout=3):
        bar_bounds = filter_bar.info.get('bounds', {})
        icon_x = bar_bounds.get('right', 2112) - 56
        icon_y = (bar_bounds.get('top', 962) + bar_bounds.get('bottom', 1074)) // 2
        shell_tap(d, icon_x, icon_y)
        time.sleep(2)
        return True
    return False


def set_rating_range(d, score_range):
    """在筛选面板中设置评分区间"""
    print(f"--- 正在设置筛选评分区间: {score_range} ---")

    if not open_filter_panel(d):
        return

    seek_bar = d(resourceId="com.douban.frodo:id/range_seek_bar")
    if not seek_bar.exists(timeout=3):
        print("⚠ 未找到评分滑块")
        cancel = d(resourceId="com.douban.frodo:id/tvCancel")
        if cancel.exists:
            click_element(d, cancel)
        return

    bounds = seek_bar.info.get('bounds') or seek_bar.info.get('visibleBounds')
    bar_left = bounds['left']
    bar_right = bounds['right']
    bar_y = (bounds['top'] + bounds['bottom']) // 2

    # 滑块 thumb 半径约 40px，实际可拖动范围在 thumb 中心之间
    thumb_r = 40
    usable_left = bar_left + thumb_r   # 左 thumb 初始中心 (0分)
    usable_right = bar_right - thumb_r  # 右 thumb 初始中心 (10分)
    usable_width = usable_right - usable_left

    low, high = map(int, score_range.split("-"))

    # 第一步：先把两个 thumb 复位到两端 (以防上一轮的位置残留)
    # 把左 thumb 拖到最左端
    shell_swipe(d, usable_left + usable_width // 2, bar_y, usable_left, bar_y, duration_ms=1500)
    time.sleep(0.3)
    # 把右 thumb 拖到最右端
    shell_swipe(d, usable_right - usable_width // 2, bar_y, usable_right, bar_y, duration_ms=1500)
    time.sleep(0.5)

    # 第二步：从左 thumb 的当前位置 (0分=usable_left) 拖到目标低分位置
    target_low_x = int(usable_left + (low / 10.0) * usable_width)
    shell_swipe(d, usable_left, bar_y, target_low_x, bar_y, duration_ms=2000)
    time.sleep(0.5)

    # 第三步：从右 thumb 的当前位置 (10分=usable_right) 拖到目标高分位置
    if high < 10:
        target_high_x = int(usable_left + (high / 10.0) * usable_width)
        shell_swipe(d, usable_right, bar_y, target_high_x, bar_y, duration_ms=2000)
    time.sleep(1)

    confirm = d(resourceId="com.douban.frodo:id/tvConfirm")
    if confirm.exists(timeout=2):
        click_element(d, confirm)
        print(f"✓ 评分区间已设为 {score_range}")
    else:
        w, h = d.window_size()
        shell_tap(d, int(w * 0.8), int(h * 0.96))
    time.sleep(3)


# ======================== URL 提取 ========================

def get_book_url_via_share(d):
    """
    通过 分享 → 复制链接 获取当前详情页的豆瓣链接。
    返回 (url, subject_id) 或 (None, None)
    """
    share_btn = d(resourceId="com.douban.frodo:id/ic_share")
    if not share_btn.exists(timeout=2):
        return None, None

    click_element(d, share_btn)
    time.sleep(1.5)

    copy_btn = d(text="复制链接")
    if copy_btn.exists(timeout=2):
        click_element(d, copy_btn)
        time.sleep(1)
        url = d.clipboard or ""
        # 提取 subject_id: https://www.douban.com/doubanapp/dispatch/book/26980487
        match = re.search(r'/book/(\d+)', url)
        subject_id = match.group(1) if match else None
        # 转换为标准 URL
        if subject_id:
            standard_url = f"https://book.douban.com/subject/{subject_id}/"
            return standard_url, subject_id
        return url, None
    else:
        # 关闭分享面板
        d.shell("input keyevent BACK")
        time.sleep(0.5)
        return None, None


# ======================== 数据库逻辑 ========================

def init_db():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 检查是否需要新增列
    cursor.execute("PRAGMA table_info(books)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    if not existing_cols:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT,
                publisher TEXT,
                pub_date TEXT,
                price TEXT,
                rating TEXT,
                rating_count TEXT,
                description TEXT,
                url TEXT UNIQUE,
                cover_url TEXT,
                cover_local TEXT,
                pub_info TEXT,
                subtitle TEXT,
                subject_id TEXT,
                detail_url TEXT,
                meta_info TEXT,
                catalog TEXT,
                excerpt TEXT,
                cover_screenshot TEXT,
                translator TEXT,
                pages TEXT,
                detail_scraped INTEGER DEFAULT 0,
                detail_updated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # 按需增加新列
        new_cols = {
            "subtitle": "TEXT",
            "subject_id": "TEXT",
            "detail_url": "TEXT",
            "meta_info": "TEXT",
            "catalog": "TEXT",
            "excerpt": "TEXT",
            "cover_screenshot": "TEXT",
            "translator": "TEXT",
            "pages": "TEXT",
            "detail_scraped": "INTEGER DEFAULT 0",
            "detail_updated_at": "TIMESTAMP",
            "root_category": "TEXT",
        }
        for col_name, col_type in new_cols.items():
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
                print(f"  ✓ 新增数据库列: {col_name}")

    conn.commit()
    return conn


def save_book(conn, book):
    cursor = conn.cursor()
    # 既然此时的 url 后续会被网页 url 覆盖，我们就不能单靠 url 的 UNIQUE 约束来去重了
    # 这里通过 title 和 pub_info 精确查重
    cursor.execute("SELECT id FROM books WHERE title = ? AND pub_info = ?", (book['title'], book['pub_info']))
    if cursor.fetchone():
        return False

    uid = hashlib.md5(f"{book['title']}_{book['pub_info']}".encode()).hexdigest()
    url = book.get('detail_url') or f"android_app://book/{uid}"
    subject_id = book.get('subject_id', '')
    root_category = book.get('root_category', '')

    try:
        cursor.execute(
            """INSERT OR IGNORE INTO books
               (title, author, publisher, pub_date, price, rating, url, pub_info, subtitle, subject_id, detail_url, root_category)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (book['title'], book['author'], book['publisher'], book['pub_date'],
             book['price'], book['rating'], url, book['pub_info'],
             book.get('subtitle', ''), subject_id, book.get('detail_url', ''), root_category)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False


def update_book_detail(conn, title, pub_info, detail_data):
    """用详情页数据更新已有的书籍记录"""
    cursor = conn.cursor()
    # 列表抓取时生成的默认 URL
    uid = hashlib.md5(f"{title}_{pub_info}".encode()).hexdigest()
    old_url = f"android_app://book/{uid}"

    # 如果抓到了网页版详情链接，覆盖默认的 url 字段
    if detail_data.get('detail_url'):
        detail_data['url'] = detail_data['detail_url']

    fields = []
    values = []
    for key in ['rating', 'rating_count', 'description', 'subtitle', 'subject_id',
                'detail_url', 'url', 'meta_info', 'catalog', 'excerpt', 'cover_screenshot',
                'translator', 'pages', 'pub_date']:
        if detail_data.get(key):
            fields.append(f"{key} = ?")
            values.append(detail_data[key])
            
    fields.append("detail_scraped = 1")
    fields.append("detail_updated_at = CURRENT_TIMESTAMP")
    fields.append("updated_at = CURRENT_TIMESTAMP")

    if not values:
        return False

    try:
        # 优先用旧的 url (android_app://...) 匹配
        sql = f"UPDATE books SET {', '.join(fields)} WHERE url = ?"
        cursor.execute(sql, values + [old_url])
        
        if cursor.rowcount == 0:
            # 或者尝试用 title 匹配
            sql = f"UPDATE books SET {', '.join(fields)} WHERE title = ? AND (detail_scraped IS NULL OR detail_scraped = 0)"
            cursor.execute(sql, values + [title])
            
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"  ⚠ 更新详情失败: {e}")
        return False


# ======================== 详情页抓取 ========================

def scrape_detail_page(d, w, h):
    """
    在当前打开的详情页中提取所有信息。
    返回 dict 或 None (如果不是书籍详情页)。
    """
    curr = d.app_current()
    if 'BookActivity' not in curr.get('activity', ''):
        return None  # 不是书籍详情页（可能是书单）

    detail = {
        'rating': '', 'rating_count': '', 'description': '',
        'subtitle': '', 'meta_info': '', 'catalog': '', 'excerpt': '',
        'subject_id': '', 'detail_url': '', 'cover_screenshot': '',
        'translator': '', 'pages': '', 'pub_date': '',
    }

    # --- 第一屏：基本信息 ---
    xml = d.dump_hierarchy()
    root = ET.fromstring(xml)

    def find_text(rid):
        node = root.find(f".//node[@resource-id='com.douban.frodo:id/{rid}']")
        return node.get('text', '').strip() if node is not None else ''

    detail['rating'] = find_text('rating_grade')
    detail['rating_count'] = find_text('score_count')  # e.g. "173461人评分"
    detail['subtitle'] = find_text('sub_title')
    detail['meta_info'] = find_text('meta_info')
    detail['description'] = find_text('brief_content')

    # --- 从 meta_info 解析译者、页数、精确出版日期 ---
    mi = detail['meta_info']
    if mi:
        # 译者: "夏莹 译" 或 "周晓亮 译"
        tm = re.search(r'([\u4e00-\u9fff·\w]+(?:\s+[\u4e00-\u9fff·\w]+)*)\s*译', mi)
        if tm:
            detail['translator'] = tm.group(1).strip()
        # 页数: "680页"
        pm = re.search(r'(\d+)\s*页', mi)
        if pm:
            detail['pages'] = pm.group(1)
        # 精确出版日期: "2026-1出版" 或 "1998年出版"
        dm = re.search(r'(\d{4}[-/]?\d{0,2})\s*出版', mi)
        if dm:
            detail['pub_date'] = dm.group(1)

    # --- 保存封面截图（最高清晰度） ---
    cover_node = root.find(".//node[@resource-id='com.douban.frodo:id/cover']")
    if cover_node is not None:
        cb = cover_node.get('bounds', '')
        nums = list(map(int, re.findall(r'\d+', cb)))
        if len(nums) == 4:
            title_text = find_text('title') or 'unknown'
            safe_name = re.sub(r'[^\w]', '_', title_text)[:30]
            cover_dir = OUTPUT_DIR / 'covers'
            cover_dir.mkdir(exist_ok=True)
            cover_path = cover_dir / f"{safe_name}.png"
            try:
                # 用 adb screencap 获取原始分辨率截图，避免任何压缩
                d.shell("screencap -p /sdcard/cover_tmp.png")
                import subprocess, io
                from PIL import Image
                raw = subprocess.check_output(
                    ["adb", "-s", d.serial, "pull", "/sdcard/cover_tmp.png", "/tmp/cover_tmp.png"],
                    stderr=subprocess.DEVNULL
                )
                img = Image.open("/tmp/cover_tmp.png")
                cropped = img.crop((nums[0], nums[1], nums[2], nums[3]))
                cropped.save(str(cover_path), format="PNG")
                detail['cover_screenshot'] = str(cover_path)
                d.shell("rm /sdcard/cover_tmp.png")
            except Exception as e:
                # fallback: 用 u2 截图
                try:
                    img = d.screenshot()
                    cropped = img.crop((nums[0], nums[1], nums[2], nums[3]))
                    cropped.save(str(cover_path), format="PNG")
                    detail['cover_screenshot'] = str(cover_path)
                except Exception as e2:
                    print(f"  ⚠ 封面截图失败: {e2}")

    # --- 获取 URL (分享 → 复制链接) ---
    share_btn = root.find(".//node[@resource-id='com.douban.frodo:id/ic_share']")
    if share_btn is not None:
        sb = share_btn.get('bounds', '')
        sn = list(map(int, re.findall(r'\d+', sb)))
        if sn:
            shell_tap(d, (sn[0]+sn[2])//2, (sn[1]+sn[3])//2)
            time.sleep(1.5)
            # 找 '复制链接' 并点击
            xml_share = d.dump_hierarchy()
            root_share = ET.fromstring(xml_share)
            for node in root_share.iter('node'):
                if '复制链接' in node.get('text', ''):
                    b = node.get('bounds', '')
                    n = list(map(int, re.findall(r'\d+', b)))
                    shell_tap(d, (n[0]+n[2])//2, (n[1]+n[3])//2)
                    time.sleep(1)
                    clip = d.clipboard or ''
                    match = re.search(r'/book/(\d+)', clip)
                    if match:
                        detail['subject_id'] = match.group(1)
                        detail['detail_url'] = f"https://book.douban.com/subject/{match.group(1)}/"
                    break
            else:
                # 没找到复制链接，关闭分享面板
                d.shell('input keyevent BACK')
                time.sleep(0.5)

    # --- 滑动到下方获取目录/摘录 ---
    shell_swipe(d, w//2, int(h*0.8), w//2, int(h*0.2), duration_ms=800)
    time.sleep(1)

    xml2 = d.dump_hierarchy()
    root2 = ET.fromstring(xml2)

    # 简介可能在滑动后显示更完整
    brief2 = root2.find(".//node[@resource-id='com.douban.frodo:id/brief_content']")
    if brief2 is not None:
        full_desc = brief2.get('text', '').strip()
        if len(full_desc) > len(detail['description']):
            detail['description'] = full_desc

    # 目录/摘录
    chapters_node = root2.find(".//node[@resource-id='com.douban.frodo:id/chapters_title']")
    if chapters_node is not None:
        # 目录和摘录是 chapters_title 同级或下级的 title/subtitle 节点
        parent = None
        for node in root2.iter('node'):
            ch = node.find(".//node[@resource-id='com.douban.frodo:id/chapters_title']")
            if ch is not None:
                parent = node
                break

        if parent is not None:
            catalog_parts = []
            excerpt_parts = []
            current_section = None
            for child in parent.iter('node'):
                rid = child.get('resource-id', '').split('/')[-1] if child.get('resource-id') else ''
                text = child.get('text', '').strip()
                if rid == 'title' and text:
                    catalog_parts.append(text)
                    current_section = text
                if rid == 'subtitle' and text:
                    if text == '完整目录':
                        continue
                    if '引自' in text:
                        # 上一个 title 是摘录内容
                        if catalog_parts:
                            excerpt_parts.append(f"{catalog_parts.pop()}\n  —— {text}")
                    else:
                        excerpt_parts.append(text)

            if catalog_parts:
                detail['catalog'] = '\n'.join(catalog_parts)
            if excerpt_parts:
                detail['excerpt'] = '\n\n'.join(excerpt_parts)

    return detail


# ======================== 数据提取 ========================

def extract_books_from_screen(d, score_range):
    """从当前屏幕提取所有书籍信息（使用 XML 解析避免多次 RPC）"""
    import xml.etree.ElementTree as ET

    books = []
    xml = d.dump_hierarchy()
    root = ET.fromstring(xml)

    # 遍历所有可点击的卡片容器
    for card in root.iter('node'):
        clickable = card.get('clickable', 'false')
        if clickable != 'true':
            continue
        bounds = card.get('bounds', '')
        if not bounds:
            continue
        nums = list(map(int, re.findall(r'\d+', bounds)))
        if len(nums) != 4 or nums[1] < 900:
            continue

        # 查找 title 和 info 子节点
        title_node = card.find(".//node[@resource-id='com.douban.frodo:id/title']")
        info_node = card.find(".//node[@resource-id='com.douban.frodo:id/info']")

        if title_node is None:
            continue

        title = title_node.get('text', '').strip()
        if not title:
            continue

        # 没有 info 的可能是书单，跳过
        if info_node is None:
            continue

        pub_info = info_node.get('text', '').strip()

        # 书单的 info 通常含 "人关注" 或 "读过X / Y本"，跳过
        if '人关注' in pub_info or re.search(r'读过\d+\s*/\s*\d+本', pub_info):
            continue

        # 提取副标题
        subtitle_node = card.find(".//node[@resource-id='com.douban.frodo:id/subtitle']")
        subtitle = subtitle_node.get('text', '').strip() if subtitle_node is not None else ""

        # 提取评分（RatingBar 旁的 TextView 显示精确分数）
        rating = ""
        rating_container = card.find(".//node[@resource-id='com.douban.frodo:id/rating_container']")
        if rating_container is None:
            # 没有 rating_container 的是书单，跳过
            continue
        for child in rating_container.iter('node'):
            cls = child.get('class', '')
            text = child.get('text', '').strip()
            if 'TextView' in cls and re.match(r'\d+\.\d+', text):
                rating = text
                break
        if not rating:
            rating = score_range

        # 解析出版信息
        parsed = parse_pub_info(pub_info)

        book = {
            "title": title,
            "subtitle": subtitle,
            "pub_info": pub_info,
            "rating": rating,
            "author": parsed["author"],
            "publisher": parsed["publisher"],
            "pub_date": parsed["pub_date"],
            "price": parsed["price"],
            "subject_id": "",
            "detail_url": "",
            "root_category": getattr(d, 'current_root_category', ""),
        }

        books.append(book)

    return books


# ======================== 主循环 ========================

def get_saved_titles(conn):
    """获取数据库中所有已保存的书名集合（用于断点续传判断）"""
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM books")
    return {row[0] for row in cursor.fetchall()}


def get_detail_scraped_titles(conn):
    """获取已抓取过详情的书名集合"""
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM books WHERE detail_scraped = 1")
    return {row[0] for row in cursor.fetchall()}


def human_scroll(d, w, h):
    """模拟人类快速浏览的滑动"""
    start_y = int(h * random.uniform(0.75, 0.85))
    end_y = int(h * random.uniform(0.15, 0.25))
    swipe_x = int(w * random.uniform(0.4, 0.6))
    duration = random.randint(300, 800)
    shell_swipe(d, swipe_x, start_y, swipe_x, end_y, duration_ms=duration)

    wait = random.uniform(1.0, 2.0)
    if random.random() < 0.05:
        wait = random.uniform(3.0, 5.0)
    time.sleep(wait)


def fast_forward_past_saved(d, w, h, saved_titles, score_range, label="已保存"):
    """
    断点续传：快速滑过已处理的内容，直到发现未处理的书。
    saved_titles: 需要跳过的书名集合
    返回跳过的轮次数。
    """
    print(f"[{score_range}] 检测到已有 {len(saved_titles)} 本{label}书，尝试断点续传...")

    for skip_round in range(MAX_SCROLLS_PER_RANGE):
        xml = d.dump_hierarchy()
        root = ET.fromstring(xml)

        # 检查当前屏幕中的书是否都已处理（过滤掉书单）
        screen_titles = []
        for card in root.iter('node'):
            if card.get('clickable') != 'true':
                continue
            bounds = card.get('bounds', '')
            if not bounds:
                continue
            nums = list(map(int, re.findall(r'\d+', bounds)))
            if len(nums) != 4 or nums[1] < 900:
                continue
            title_node = card.find(".//node[@resource-id='com.douban.frodo:id/title']")
            info_node = card.find(".//node[@resource-id='com.douban.frodo:id/info']")
            rating_container = card.find(".//node[@resource-id='com.douban.frodo:id/rating_container']")
            if title_node is None or info_node is None:
                continue
            # 过滤书单：没有 rating_container 或 info 含 "人关注"
            if rating_container is None:
                continue
            info_text = info_node.get('text', '')
            if '人关注' in info_text or re.search(r'读过\d+\s*/\s*\d+本', info_text):
                continue
            t = title_node.get('text', '').strip()
            if t:
                screen_titles.append(t)

        if not screen_titles:
            # 空屏幕，继续滑
            human_scroll(d, w, h)
            continue

        # 如果屏幕上有任何一本书不在已保存集合中 → 到达新内容区
        new_on_screen = [t for t in screen_titles if t not in saved_titles]
        if new_on_screen:
            print(f"[{score_range}] ⏩ 跳过 {skip_round} 轮，发现新书: 《{new_on_screen[0]}》")
            return skip_round

        # 全部已保存，快速滑过
        if skip_round % 10 == 0:
            print(f"[{score_range}] ⏩ 快进中... 已跳过 {skip_round} 轮")

        # 快进用更快的速度滑动
        start_y = int(h * 0.8)
        end_y = int(h * 0.2)
        swipe_x = int(w * 0.5)
        shell_swipe(d, swipe_x, start_y, swipe_x, end_y, duration_ms=random.randint(200, 500))
        time.sleep(random.uniform(0.5, 1.0))

    print(f"[{score_range}] ⚠ 快进到达最大轮次，未找到新内容")
    return MAX_SCROLLS_PER_RANGE


def main():
    parser = argparse.ArgumentParser(description="使用 uiautomator2 抓取豆瓣 App 书籍数据")
    parser.add_argument("--range", type=str, help="指定评分区间，如 8-9")
    parser.add_argument("--device", type=str, default=DEVICE_SERIAL, help="设备地址")
    parser.add_argument("--detail", action="store_true", help="启用详情页抓取（评分人数/简介/目录/封面/URL）")
    parser.add_argument("--force-update", action="store_true", help="强制重新抓取已有详情的书")
    parser.add_argument("--category", type=str, default="", help="抓取书籍的全局根分类，如: 哲学、心理学")
    args = parser.parse_args()

    d = u2.connect(args.device)
    print(f"✓ 已连接设备: {d.serial}")
    w, h = d.window_size()
    print(f"  屏幕分辨率: {w}x{h}")
    if args.detail:
        print("  📖 详情页抓取模式已启用")
        if args.force_update:
            print("  ⚠ 强制更新模式：将重新抓取所有详情")

    if args.category:
        print(f"  🏷️ 将所有抓取到的书归入全局分类: 【{args.category}】")
        d.current_root_category = args.category
    else:
        d.current_root_category = ""

    curr = d.app_current()
    print(f"  当前 Activity: {curr['activity']}")
    if 'TagSubjects' not in curr.get('activity', ''):
        print("⚠ 请先导航到豆瓣 App 的「分类找图书」页面！")
        return

    db_conn = init_db()
    ranges_to_run = [args.range] if args.range else DEFAULT_RANGES

    # 先设置按时间排序
    set_sort_by_time(d)

    for score_range in ranges_to_run:
        set_rating_range(d, score_range)
        range_count = 0
        consecutive_no_new = 0

        print(f"\n=== 开始抓取 [{score_range}] (按时间排序) ===")

        # ---- 断点续传：快速跳过已处理的内容 ----
        if args.detail:
            # 详情模式：跳过已抓取详情的书，停在需要抓详情的位置
            detail_done = get_detail_scraped_titles(db_conn)
            if detail_done:
                fast_forward_past_saved(d, w, h, detail_done, score_range, label="已有详情")
        else:
            # 列表模式：跳过已保存的书，停在新书位置
            saved_titles = get_saved_titles(db_conn)
            if saved_titles:
                fast_forward_past_saved(d, w, h, saved_titles, score_range)

        # ---- 正常抓取 ----
        for i in range(MAX_SCROLLS_PER_RANGE):
            books = extract_books_from_screen(d, score_range)
            new_found = 0

            for book in books:
                if save_book(db_conn, book):
                    new_found += 1
                    range_count += 1

            print(f"[{score_range}] 轮次 {i+1}: 发现 {len(books)} 本, 新增 {new_found} 本. 累计: {range_count}")

            # ---- 详情页模式：依次点进每本书抓取详情 ----
            if args.detail and books:
                scrape_details_for_screen(d, db_conn, books, w, h, score_range, force_update=args.force_update)

            if new_found == 0:
                consecutive_no_new += 1
            else:
                consecutive_no_new = 0

            if consecutive_no_new > 120000:
                print(f"[{score_range}] 连续 {consecutive_no_new} 轮无新数据，跳过此区间")
                break

            human_scroll(d, w, h)

        finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat_suffix = f" '{args.category}'分类." if args.category else "."
        with open(LOG_FILE, "a") as f:
            f.write(f"At {finish_time} {range_count} books finished adding {score_range} points{cat_suffix}\n")

    db_conn.close()
    print("\n✓ 抓取完成!")


def scrape_details_for_screen(d, db_conn, books, w, h, score_range, force_update=False):
    """
    对当前屏幕上的书，逐本点击进入详情页抓取信息。
    只处理尚未抓取过详情的书，除非 force_update=True。
    """
    cursor = db_conn.cursor()
    for book in books:
        title = book['title']
        pub_info = book['pub_info']
        # 检查是否已抓取详情
        if not force_update:
            cursor.execute("SELECT detail_scraped FROM books WHERE title = ? AND pub_info = ?", (title, pub_info))
            row = cursor.fetchone()
            if row and row[0]:
                continue  # 已有详情，跳过

        # 在屏幕上找到这本书并点击
        xml = d.dump_hierarchy()
        root = ET.fromstring(xml)
        clicked = False
        for card in root.iter('node'):
            if card.get('clickable') != 'true':
                continue
            title_node = card.find(".//node[@resource-id='com.douban.frodo:id/title']")
            if title_node is not None and title_node.get('text', '').strip() == title:
                bounds = card.get('bounds', '')
                nums = list(map(int, re.findall(r'\d+', bounds)))
                if len(nums) == 4:
                    cx = (nums[0] + nums[2]) // 2
                    cy = (nums[1] + nums[3]) // 2
                    shell_tap(d, cx, cy)
                    clicked = True
                    break

        if not clicked:
            continue

        time.sleep(random.uniform(2.0, 3.0))

        # 检查是否进入了书籍详情页
        curr = d.app_current()
        if 'BookActivity' not in curr.get('activity', ''):
            # 可能是书单或其他页面，直接返回
            print(f"    ⏭ 《{title}》不是书籍页面，跳过")
            d.shell('input keyevent BACK')
            time.sleep(1)
            continue

        # 抓取详情
        print(f"    📖 抓取详情: 《{title}》")
        detail = scrape_detail_page(d, w, h)

        if detail:
            update_book_detail(db_conn, title, pub_info, detail)
            print(f"    ✓ 详情已保存 (评分:{detail.get('rating','')} 评分人数:{detail.get('rating_count','')} URL:{detail.get('detail_url','')})")

        # 返回列表
        d.shell('input keyevent BACK')
        time.sleep(random.uniform(1.5, 2.5))

        # 确认回到了列表页
        for _ in range(3):
            curr = d.app_current()
            if 'TagSubjects' in curr.get('activity', ''):
                break
            d.shell('input keyevent BACK')
            time.sleep(1)


if __name__ == "__main__":
    main()

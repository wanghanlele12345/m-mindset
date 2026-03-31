#!/usr/bin/env python3
"""
哲学图书馆 LLM 自动分类脚本
使用 DeepSeek API 为豆瓣哲学书籍数据库自动分配主分类和多维标签。
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error

# ============================================================
# 配置
# ============================================================

DB_PATH = os.path.join(os.path.dirname(__file__), "output", "books.db")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
BATCH_SIZE = 5         # 每批处理几本书
REQUEST_DELAY = 1.5    # 每批之间的延迟（秒）
MAX_RETRIES = 3        # 最大重试次数

# ============================================================
# 分类体系与系统提示词
# ============================================================

def get_system_prompt(category: str) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{category}.md")
    if not os.path.exists(prompt_path):
        print(f"❌ 提示词文件不存在: {prompt_path}")
        sys.exit(1)
        
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# 数据库操作
# ============================================================

def init_db(conn):
    """创建分类相关的表（不修改 books 表）"""
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS book_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL UNIQUE,
            category_code TEXT NOT NULL,
            category_name TEXT,
            confidence TEXT,
            belongs_to_category INTEGER,
            suggested_category TEXT,
            reason TEXT,
            classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            model_version TEXT,
            FOREIGN KEY (book_id) REFERENCES books(id)
        );
        CREATE INDEX IF NOT EXISTS idx_cls_book ON book_classifications(book_id);
        CREATE INDEX IF NOT EXISTS idx_cls_category ON book_classifications(category_code);

        CREATE TABLE IF NOT EXISTS book_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            dimension TEXT NOT NULL,
            tag_value TEXT NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(id)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_book ON book_tags(book_id);
        CREATE INDEX IF NOT EXISTS idx_tags_dim ON book_tags(dimension);
        CREATE INDEX IF NOT EXISTS idx_tags_value ON book_tags(tag_value);
    """)

    # 尝试为已存在的表添加新字段
    for col, col_type in [("belongs_to_category", "INTEGER"), ("suggested_category", "TEXT"), ("reason", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE book_classifications ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    print("✅ 分类表初始化完成")


def get_unclassified_books(conn, filter_category, limit=None):
    """获取尚未分类的书籍"""
    params = []
    
    # 构建基础查询
    query = """
        SELECT b.id, b.title, b.author, b.description
        FROM books b
        LEFT JOIN book_classifications bc ON b.id = bc.book_id
        WHERE bc.id IS NULL
          AND b.detail_scraped = 1
          AND b.description IS NOT NULL
          AND b.description != ''
    """
    
    # 如果指定了过滤条件，只查询该 root_category 的书籍
    if filter_category:
        query += " AND (b.root_category = ? OR b.root_category LIKE ?)"
        params.extend([filter_category, f"%{filter_category}%"])
        
    if limit:
        query += f" LIMIT ?"
        params.append(limit)
        
    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


def save_classification(conn, book_id, result, model_version):
    """保存单本书的分类和标签结果"""
    cursor = conn.cursor()

    other_details = result.get("other_details") or {}
    belongs_to_category = other_details.get("belongs_to_category")
    # 兼容老的哲学格式
    if belongs_to_category is None and "is_philosophy" in other_details:
        belongs_to_category = other_details.get("is_philosophy")
        
    if belongs_to_category is not None:
        belongs_to_category = 1 if belongs_to_category else 0
    suggested_category = other_details.get("suggested_category")
    reason = other_details.get("reason")

    # 保存主分类
    cursor.execute("""
        INSERT OR REPLACE INTO book_classifications
            (book_id, category_code, category_name, confidence, belongs_to_category, suggested_category, reason, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        book_id,
        result.get("category", "其他"),
        result.get("category_name", ""),
        result.get("confidence", "medium"),
        belongs_to_category,
        suggested_category,
        reason,
        model_version
    ))

    # 保存标签
    tags = result.get("tags", {})
    for dimension, values in tags.items():
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if value:
                cursor.execute("""
                    INSERT INTO book_tags (book_id, dimension, tag_value)
                    VALUES (?, ?, ?)
                """, (book_id, dimension, value))


# ============================================================
# DeepSeek API 调用
# ============================================================

def call_deepseek(api_key, books_batch, system_prompt):
    """调用 DeepSeek API 对一批书籍进行分类"""
    print(f"  🔄 正在调用 DeepSeek API ({DEEPSEEK_MODEL})...")

    # 构建用户消息
    user_content = "请对以下书籍进行分类和打标签：\n\n"
    for i, (book_id, title, author, description) in enumerate(books_batch, 1):
        desc_truncated = (description[:800] + "...") if len(description) > 800 else description
        user_content += f"### 第{i}本\n"
        user_content += f"- 书名：{title}\n"
        user_content += f"- 作者：{author or '未知'}\n"
        user_content += f"- 简介：{desc_truncated}\n\n"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(DEEPSEEK_API_URL, data=data, headers=headers, method="POST")

    for attempt in range(MAX_RETRIES):
        try:
            t0 = time.time()
            if attempt > 0:
                print(f"  🔄 重试第 {attempt+1} 次...")
            with urllib.request.urlopen(req, timeout=180) as resp:
                elapsed = time.time() - t0
                print(f"  ⏱️  API 响应耗时 {elapsed:.1f}s")
                body = json.loads(resp.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                # 尝试解析 JSON
                parsed = json.loads(content)
                # 可能返回的是 {"books": [...]} 或直接 [...]
                if isinstance(parsed, dict):
                    if "books" in parsed:
                        return parsed["books"]
                    # 尝试找到第一个列表值
                    for v in parsed.values():
                        if isinstance(v, list):
                            return v
                    return [parsed]
                return parsed
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            print(f"  ⚠️ HTTP {e.code} 错误 (尝试 {attempt+1}/{MAX_RETRIES}): {error_body[:200]}")
            if e.code == 429:
                wait = (attempt + 1) * 5
                print(f"  ⏳ 限流，等待 {wait} 秒...")
                time.sleep(wait)
            elif e.code >= 500:
                time.sleep((attempt + 1) * 3)
            else:
                raise
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠️ 解析响应失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ 请求异常 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep((attempt + 1) * 2)

    return None


# ============================================================
# 主流程
# ============================================================

def classify_batch(conn, api_key, books_batch, batch_num, system_prompt):
    """处理一批书籍的分类"""
    titles = [b[1] for b in books_batch]
    print(f"\n📦 批次 {batch_num}：{', '.join(titles)}")

    results = call_deepseek(api_key, books_batch, system_prompt)
    if not results:
        print(f"  ❌ 此批次 API 调用失败，跳过")
        return 0

    # 将结果按标题匹配到 book_id
    title_to_id = {b[1]: b[0] for b in books_batch}
    saved_count = 0

    for result in results:
        result_title = result.get("title", "")
        # 尝试精确匹配
        book_id = title_to_id.get(result_title)
        # 如果没匹配到，尝试模糊匹配
        if book_id is None:
            for title, bid in title_to_id.items():
                if result_title in title or title in result_title:
                    book_id = bid
                    break

        if book_id is None:
            print(f"  ⚠️ 无法匹配书名：{result_title}")
            continue

        try:
            save_classification(conn, book_id, result, DEEPSEEK_MODEL)
            cat = result.get("category", "?")
            cat_name = result.get("category_name", "")
            conf = result.get("confidence", "?")
            print(f"  ✅ [{cat} {cat_name}] {result_title} (confidence: {conf})")
            saved_count += 1
        except Exception as e:
            print(f"  ❌ 保存失败 [{result_title}]: {e}")

    conn.commit()
    return saved_count


def main():
    parser = argparse.ArgumentParser(description="使用 DeepSeek 对书籍进行自动分类")
    parser.add_argument("--category", type=str, required=True,
                        help="必填: 分类的名称（例如：'哲学', '心理学'），对应的提示词文件将在 prompts/ 目录下查找")
    parser.add_argument("--pilot", type=int, default=None,
                        help="试跑模式：仅处理 N 本书（如 --pilot 30）")
    parser.add_argument("--all", action="store_true",
                        help="全量模式：处理所有未分类的书")
    parser.add_argument("--db", default=DB_PATH,
                        help="数据库路径")
    parser.add_argument("--api-key", default=None,
                        help="DeepSeek API Key（也可通过 DEEPSEEK_API_KEY 环境变量设置）")
    parser.add_argument("--init-only", action="store_true",
                        help="仅初始化数据库表，不执行分类")
    parser.add_argument("--stats", action="store_true",
                        help="查看当前分类统计")
    parser.add_argument("--reset", action="store_true",
                        help="清空所有分类数据（重新开始）")
    args = parser.parse_args()

    # 数据库连接
    if not os.path.exists(args.db):
        print(f"❌ 数据库文件不存在: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")

    # 重置
    if args.reset:
        confirm = input("⚠️  确定要清空所有分类数据吗？(yes/no): ")
        if confirm.lower() == "yes":
            conn.executescript("""
                DROP TABLE IF EXISTS book_tags;
                DROP TABLE IF EXISTS book_classifications;
            """)
            print("🗑️  分类数据已清空")
            init_db(conn)
        conn.close()
        return

    # 初始化表
    init_db(conn)

    if args.init_only:
        conn.close()
        return

    # 统计
    if args.stats:
        show_stats(conn)
        conn.close()
        return

    # 获取 API Key
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 请设置 DeepSeek API Key:")
        print("   方式1: export DEEPSEEK_API_KEY='your-key'")
        print("   方式2: --api-key your-key")
        sys.exit(1)

    # 确定处理数量
    if args.pilot:
        limit = args.pilot
        print(f"🧪 试跑模式：处理 {limit} 本书")
    elif args.all:
        limit = None
        print("🚀 全量模式：处理所有未分类的书")
    else:
        print("请指定模式: --pilot N 或 --all")
        sys.exit(1)

    print(f"📖 使用分类配置: {args.category} (prompts/{args.category}.md)")
    system_prompt = get_system_prompt(args.category)

    # 获取待分类书籍
    books = get_unclassified_books(conn, args.category, limit)
    if not books:
        print("✨ 没有需要分类的书籍")
        conn.close()
        return

    total = len(books)
    print(f"📚 共 {total} 本书待分类")

    # 分批处理
    total_saved = 0
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = books[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        saved = classify_batch(conn, api_key, batch, batch_num, system_prompt)
        total_saved += saved

        # 进度
        progress = min((i + BATCH_SIZE), total) / total * 100
        print(f"  📊 进度: {progress:.0f}% ({total_saved}/{total})")

        # 延迟（最后一批不等）
        if i + BATCH_SIZE < total:
            time.sleep(REQUEST_DELAY)

    print(f"\n{'='*50}")
    print(f"✅ 分类完成！成功处理 {total_saved}/{total} 本书")
    show_stats(conn)
    conn.close()


def show_stats(conn):
    """显示分类统计信息"""
    cursor = conn.cursor()

    # 总体统计
    cursor.execute("SELECT COUNT(*) FROM books WHERE detail_scraped = 1")
    total_books = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM book_classifications")
    classified = cursor.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"📊 分类统计")
    print(f"{'='*50}")
    print(f"总书籍数: {total_books}")
    print(f"已分类数: {classified}")
    print(f"未分类数: {total_books - classified}")
    print(f"覆盖率:   {classified/total_books*100:.1f}%" if total_books > 0 else "")

    # 各分类分布
    cursor.execute("""
        SELECT category_code, category_name, COUNT(*) as cnt
        FROM book_classifications
        GROUP BY category_code
        ORDER BY cnt DESC
    """)
    rows = cursor.fetchall()
    if rows:
        print(f"\n📂 分类分布:")
        for code, name, cnt in rows:
            bar = "█" * (cnt // 5) if cnt >= 5 else "▎"
            print(f"  {code:6s} {name or '':20s} {cnt:4d} {bar}")

    # confidence 分布
    cursor.execute("""
        SELECT confidence, COUNT(*) FROM book_classifications GROUP BY confidence
    """)
    conf_rows = cursor.fetchall()
    if conf_rows:
        print(f"\n🎯 置信度分布:")
        for conf, cnt in conf_rows:
            print(f"  {conf or 'unknown':10s} {cnt}")

    # 最常见标签
    cursor.execute("""
        SELECT dimension, tag_value, COUNT(*) as cnt
        FROM book_tags
        GROUP BY dimension, tag_value
        ORDER BY dimension, cnt DESC
    """)
    tag_rows = cursor.fetchall()
    if tag_rows:
        print(f"\n🏷️  热门标签 (Top 5 per dimension):")
        current_dim = None
        dim_count = 0
        for dim, val, cnt in tag_rows:
            if dim != current_dim:
                current_dim = dim
                dim_count = 0
                print(f"  [{dim}]")
            if dim_count < 5:
                print(f"    {val}: {cnt}")
                dim_count += 1


if __name__ == "__main__":
    main()

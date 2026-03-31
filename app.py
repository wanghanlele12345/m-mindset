from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import json
import re
import urllib.parse
import unicodedata

app = FastAPI()

# 强制使用绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "books.db")
COVERS_DIR = os.path.join(BASE_DIR, "data", "covers")

print(f"\n🚀 --- SERVER STARTUP DEBUG ---")
print(f"BASE_DIR: {BASE_DIR}")
print(f"DB_PATH: {DB_PATH} (Exists: {os.path.exists(DB_PATH)})")
print(f"COVERS_DIR: {COVERS_DIR} (Exists: {os.path.exists(COVERS_DIR)})")
if os.path.exists(COVERS_DIR):
    print(f"FILES IN COVERS: {len(os.listdir(COVERS_DIR))}")
print(f"--------------------------------\n")

CATEGORY_MAP = {
    "1.1": "哲学工具书", "1.2": "哲学导论与普及", "1.3": "哲学方法论", "1.4": "哲学思想史与哲学家传记",
    "2.1": "古代与中世纪哲学", "2.2": "近代哲学 16-19世纪", "2.3": "现代与当代西方哲学",
    "3.1": "中国古代哲学", "3.2": "中国近现代哲学", "3.3": "其他东方哲学",
    "4.1": "核心形而上学/本体论", "4.2": "心灵哲学",
    "5.1": "认识论/知识论", "5.2": "科学哲学",
    "6.1": "逻辑学", "6.2": "语言哲学",
    "7.1": "规范伦理学", "7.2": "元伦理学", "7.3": "应用伦理学",
    "8.1": "政治哲学", "8.2": "社会哲学", "8.3": "法哲学",
    "9.1": "美学理论", "9.2": "各类艺术与文学哲学",
    "10.1": "宗教哲学", "10.2": "历史哲学", "10.3": "教育哲学", "10.4": "技术与媒介哲学", "10.5": "哲学人类学与文化哲学", "10.6": "哲学与心理学"
}

def get_db_conn(mode="ro"):
    abs_db_path = DB_PATH
    if not os.path.exists(abs_db_path):
        os.makedirs(os.path.dirname(abs_db_path), exist_ok=True)
        conn = sqlite3.connect(abs_db_path)
        conn.close()
    
    db_uri = f"file:{abs_db_path}?mode={mode}"
    conn = sqlite3.connect(db_uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/debug")
async def debug_info():
    import os
    info = {
        "BASE_DIR": BASE_DIR,
        "DB_PATH": DB_PATH,
        "DB_EXISTS": os.path.exists(DB_PATH),
        "DB_SIZE_MB": os.path.getsize(DB_PATH) / (1024 * 1024) if os.path.exists(DB_PATH) else 0,
        "CWD": os.getcwd(),
        "FILES_IN_BASE": os.listdir(BASE_DIR) if os.path.exists(BASE_DIR) else [],
        "FILES_IN_DATA": os.listdir(os.path.join(BASE_DIR, "data")) if os.path.exists(os.path.join(BASE_DIR, "data")) else []
    }
    return info

@app.get("/api/books")
async def get_books(root_category: str = ""):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        
        where_clause = ""
        params = []
        if root_category:
            where_clause = "WHERE b.root_category = ?"
            params.append(root_category)
        
        query = f"""
            SELECT 
                b.id, b.title, b.author, b.publisher, b.pub_date, b.price, b.rating, 
                b.rating_count, b.url, b.subtitle, b.cover_screenshot, b.detail_scraped,
                b.description, b.created_at, b.translator, b.pages, b.catalog, b.excerpt,
                bc.category_code, bc.category_name, bc.confidence, b.cover_remote_url
            FROM books b
            LEFT JOIN book_classifications bc ON b.id = bc.book_id
            {where_clause}
            ORDER BY b.rating DESC NULLS LAST
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        tag_query = f"""
            SELECT t.book_id, t.dimension, t.tag_value 
            FROM book_tags t
            JOIN books b ON t.book_id = b.id
            {where_clause}
            ORDER BY t.book_id
        """
        cursor.execute(tag_query, params)
        tags_by_book = {}
        for tag_row in cursor.fetchall():
            bid = tag_row['book_id']
            if bid not in tags_by_book:
                tags_by_book[bid] = {}
            dim = tag_row['dimension']
            if dim not in tags_by_book[bid]:
                tags_by_book[bid][dim] = []
            tags_by_book[bid][dim].append(tag_row['tag_value'])
        
        books = []
        for row in rows:
            book = dict(row)
            book['tags'] = tags_by_book.get(book['id'], {})
            books.append(book)
        
        conn.close()
        return {"data": books}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/categories")
async def get_categories(root_category: str = ""):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        
        where_clause = ""
        params = []
        if root_category:
            where_clause = "WHERE b.root_category = ?"
            params.append(root_category)
            
        cursor.execute(f"""
            SELECT bc.category_code, bc.category_name, COUNT(*) as count
            FROM book_classifications bc
            JOIN books b ON bc.book_id = b.id
            {where_clause}
            GROUP BY bc.category_code
            ORDER BY bc.category_code
        """, params)
        categories = [dict(row) for row in cursor.fetchall()]

        cursor.execute(f"""
            SELECT t.dimension, t.tag_value, COUNT(*) as count
            FROM book_tags t
            JOIN books b ON t.book_id = b.id
            {where_clause}
            GROUP BY t.dimension, t.tag_value
            ORDER BY t.dimension, count DESC
        """, params)
        tag_rows = cursor.fetchall()
        tag_dims = {}
        for row in tag_rows:
            dim = row['dimension']
            if dim not in tag_dims:
                tag_dims[dim] = []
            tag_dims[dim].append({'value': row['tag_value'], 'count': row['count']})

        conn.close()
        return {'categories': categories, 'tag_dimensions': tag_dims}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/other_books")
async def get_other_books(root_category: str = ""):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        
        where_clause = ""
        params = []
        if root_category:
            where_clause = " AND b.root_category = ?"
            params.append(root_category)
        
        query = f"""
            SELECT 
                b.id, b.title, b.author, b.cover_screenshot, b.rating,
                bc.is_philosophy, bc.belongs_to_category, bc.suggested_category, bc.reason, b.cover_remote_url
            FROM books b
            JOIN book_classifications bc ON b.id = bc.book_id
            WHERE (bc.category_code = '其他' OR bc.category_code = '其他分类' OR bc.category_code = 'Other')
            {where_clause}
            ORDER BY b.rating DESC NULLS LAST
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        books = []
        for row in rows:
            book = dict(row)
            s_cat = book.get('suggested_category') or ''
            match = re.search(r'^(\d+\.\d+)', s_cat.strip())
            if match:
                code = match.group(1)
                name = CATEGORY_MAP.get(code, '')
                if name and name not in s_cat:
                    book['suggested_category'] = f"{code} {name}"
            books.append(book)
        
        conn.close()
        return {'data': books}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/covers/{filename:path}")
async def get_cover(filename: str):
    # 彻底的解码
    decoded_filename = urllib.parse.unquote(urllib.parse.unquote(filename))
    decoded_filename = unicodedata.normalize('NFC', decoded_filename)
    
    # 1. 绝对精确匹配
    direct_path = os.path.join(COVERS_DIR, decoded_filename)
    if os.path.exists(direct_path) and os.path.isfile(direct_path):
        return FileResponse(direct_path, media_type="image/png")
    
    # 2. 忽略大小写和标点的极致模糊匹配
    try:
        files = os.listdir(COVERS_DIR)
        def normalize_text(t):
            t = unicodedata.normalize('NFC', t)
            return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', t.lower())

        target_core = normalize_text(os.path.splitext(decoded_filename)[0])
        
        for f in files:
            f_nfc = unicodedata.normalize('NFC', f)
            # A. 包含匹配
            if decoded_filename in f_nfc or f_nfc in decoded_filename:
                return FileResponse(os.path.join(COVERS_DIR, f), media_type="image/png")
            
            # B. 核心文本匹配
            if target_core and normalize_text(os.path.splitext(f_nfc)[0]) == target_core:
                return FileResponse(os.path.join(COVERS_DIR, f), media_type="image/png")
    except:
        pass

    raise HTTPException(status_code=404, detail=f"Cover not found: {decoded_filename}")

@app.get("/")
async def read_index():
    index_path = os.path.join(BASE_DIR, "static", "index.html")
    if os.path.exists(index_path): return FileResponse(index_path)
    return HTMLResponse("<h1>Static files missing</h1>")

@app.get("/other")
@app.get("/others")
async def read_other():
    other_path = os.path.join(BASE_DIR, "static", "other.html")
    if os.path.exists(other_path): return FileResponse(other_path)
    return HTMLResponse("<h1>Static files missing</h1>")

@app.post("/api/accept_suggestion")
async def accept_suggestion(payload: dict = Body(...)):
    try:
        book_id = payload.get('book_id')
        suggested_category = payload.get('suggested_category')
        conn = get_db_conn(mode="rw")
        cursor = conn.cursor()
        match = re.search(r'^(\d+\.\d+)', suggested_category.strip())
        cat_code = match.group(1) if match else suggested_category
        cursor.execute("UPDATE book_classifications SET category_code = ?, suggested_category = NULL WHERE book_id = ?", (cat_code, book_id))
        conn.commit()
        conn.close()
        return {'success': True}
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/open_weread")
async def open_weread():
    return JSONResponse({'error': 'Automation restricted to local scripts.'}, status_code=400)

if os.path.exists(os.path.join(BASE_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

if __name__ == "__main__":
    import uvicorn
    print("🌟 Starting server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)

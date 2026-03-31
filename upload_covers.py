import sqlite3
import os
import requests
import base64
import time
import concurrent.futures

# 配置
API_KEY = "b68204b64ed8c70d589e83fcb100974d"
DB_PATH = "data/books.db"
COVERS_DIR = "data/covers"

def upload_image(image_path):
    """上传单张图片到 ImgBB"""
    try:
        with open(image_path, "rb") as file:
            url = "https://api.imgbb.com/1/upload"
            payload = {
                "key": API_KEY,
                "image": base64.b64encode(file.read()),
            }
            res = requests.post(url, payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                return data['data']['url']
            else:
                print(f"Error uploading {image_path}: {res.text}")
                return None
    except Exception as e:
        print(f"Exception for {image_path}: {e}")
        return None

def process_book(book_id, cover_path):
    """处理单本书的上传与更新"""
    # 修正路径：如果数据库存的是相对路径，确保它在本地能找到
    full_path = cover_path
    if not os.path.isabs(full_path):
        full_path = os.path.join(os.getcwd(), cover_path)
    
    if not os.path.exists(full_path):
        # 尝试去掉前缀
        if cover_path.startswith("data/covers/"):
            full_path = os.path.join(os.getcwd(), cover_path)
        else:
            print(f"File not found: {full_path}")
            return None

    remote_url = upload_image(full_path)
    if remote_url:
        return (remote_url, book_id)
    return None

def main():
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 找出所有有本地封面但没有远程 URL 的书籍
    cursor.execute("SELECT id, cover_screenshot FROM books WHERE cover_screenshot IS NOT NULL AND (cover_remote_url IS NULL OR cover_remote_url = '')")
    rows = cursor.fetchall()
    
    total = len(rows)
    print(f"🚀 Found {total} covers to upload...")

    if total == 0:
        print("No covers need uploading!")
        return

    # 使用线程池并发上传 (5 个并发)
    batch_size = 50
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for i in range(0, total, batch_size):
            batch = rows[i:i+batch_size]
            futures = {executor.submit(process_book, row['id'], row['cover_screenshot']): row['id'] for row in batch}
            
            updates = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    updates.append(result)
            
            # 批量更新数据库
            if updates:
                cursor.executemany("UPDATE books SET cover_remote_url = ? WHERE id = ?", updates)
                conn.commit()
                print(f"✅ Progress: {min(i + batch_size, total)}/{total} uploaded.")

    conn.close()
    print("🎉 All done!")

if __name__ == "__main__":
    main()

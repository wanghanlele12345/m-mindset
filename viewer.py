import http.server
import socketserver
import json
import sqlite3
import urllib.parse
import os
import argparse
import re
import sys

DB_PATH = "output/books.db"

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

class BookVisualizerHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        unquoted_path = urllib.parse.unquote(parsed_path.path)
        
        if parsed_path.path == '/api/books':
            self.handle_api_books()
        elif parsed_path.path == '/api/categories':
            self.handle_api_categories()
        elif parsed_path.path == '/api/other_books':
            self.handle_api_other_books()
        elif parsed_path.path.startswith('/covers/'):
            # 提供封面图片文件
            filename = urllib.parse.unquote(os.path.basename(parsed_path.path))
            cover_path = os.path.join('output', 'covers', filename)
            if os.path.exists(cover_path):
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open(cover_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, 'Cover not found')
        elif parsed_path.path == '/':
            self.path = '/static/index.html'
            return super().do_GET()
        elif unquoted_path.endswith('/others'):
            self.path = '/static/other.html'
            return super().do_GET()
        elif parsed_path.path == '/other':
            self.path = '/static/other.html'
            return super().do_GET()
        else:
            return super().do_GET()

    def _open_db(self):
        abs_db_path = os.path.abspath(DB_PATH)
        db_uri = f"file:{abs_db_path}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _open_db_rw(self):
        abs_db_path = os.path.abspath(DB_PATH)
        db_uri = f"file:{abs_db_path}?mode=rw"
        conn = sqlite3.connect(db_uri, uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def handle_api_books(self):
        try:
            conn = self._open_db()
            cursor = conn.cursor()
            
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            root_category = query_params.get('root_category', [''])[0]

            where_clause = ""
            params = []
            if root_category:
                where_clause = "WHERE b.root_category = ?"
                params.append(root_category)
            
            # Books with classification data (LEFT JOIN so unclassified books still appear)
            query = f"""
                SELECT 
                    b.id, b.title, b.author, b.publisher, b.pub_date, b.price, b.rating, 
                    b.rating_count, b.url, b.subtitle, b.cover_screenshot, b.detail_scraped,
                    b.description, b.created_at, b.translator, b.pages, b.catalog, b.excerpt,
                    bc.category_code, bc.category_name, bc.confidence
                FROM books b
                LEFT JOIN book_classifications bc ON b.id = bc.book_id
                {where_clause}
                ORDER BY b.rating DESC NULLS LAST
            """
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Get all tags indexed by book_id
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
            
            self._send_json({'data': books})
            conn.close()
            
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def handle_api_categories(self):
        """Return distinct categories with book counts for the filter sidebar."""
        try:
            conn = self._open_db()
            cursor = conn.cursor()
            
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            root_category = query_params.get('root_category', [''])[0]

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

            # Also return tag dimensions and their values with counts
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

            self._send_json({'categories': categories, 'tag_dimensions': tag_dims})
            conn.close()
            
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def handle_api_other_books(self):
        """Fetch all books classified as '其他' with their reasons."""
        try:
            conn = self._open_db()
            cursor = conn.cursor()
            
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            root_category = query_params.get('root_category', [''])[0]

            where_clause = ""
            params = []
            if root_category:
                where_clause = " AND b.root_category = ?"
                params.append(root_category)
            
            # Fetch all '其他' books and their philosophical checking fields
            query = f"""
                SELECT 
                    b.id, b.title, b.author, b.cover_screenshot, b.rating,
                    bc.is_philosophy, bc.belongs_to_category, bc.suggested_category, bc.reason
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
            
            self._send_json({'data': books})
            conn.close()
            
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/api/accept_suggestion':
            self.handle_api_accept_suggestion()
        elif parsed_path.path == '/api/reclassify':
            self.handle_api_reclassify()
        elif parsed_path.path == '/api/delete_book':
            self.handle_api_delete_book()
        elif parsed_path.path == '/api/open_weread':
            self.handle_api_open_weread()
        else:
            self.send_error(404, 'Not Found')

    def handle_api_accept_suggestion(self):
        """Update a book's classification to its suggested category."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            book_id = data.get('book_id')
            suggested_category = data.get('suggested_category')
            
            if not book_id or not suggested_category:
                self._send_json({'error': 'Missing book_id or suggested_category'}, status=400)
                return

            conn = self._open_db_rw()
            cursor = conn.cursor()
            
            # Step 1: Look up or parse the category name if possible (optional, but good for completeness)
            match = re.search(r'^(\d+\.\d+)(?:\s+(.*))?$', suggested_category.strip())
            if match:
                cat_code = match.group(1)
                new_cat_name = match.group(2) or ""
            else:
                cat_code = suggested_category
                new_cat_name = ""

            if not new_cat_name:
                # Find the category name corresponding to the suggested code from the db if it exists
                cursor.execute("SELECT category_name FROM book_classifications WHERE category_code = ? LIMIT 1", (cat_code,))
                row = cursor.fetchone()
                new_cat_name = row['category_name'] if row else ""

            # Step 2: Update the classification
            cursor.execute("""
                UPDATE book_classifications 
                SET category_code = ?, 
                    category_name = ?,
                    suggested_category = NULL,
                    is_philosophy = NULL,
                    reason = NULL,
                    confidence = 'medium'
                WHERE book_id = ?
            """, (cat_code, new_cat_name, book_id))
            
            if cursor.rowcount == 0:
                self._send_json({'error': 'Book classification not found'}, status=404)
            else:
                conn.commit()
                self._send_json({'success': True, 'message': 'Book reclassified successfully'})
                
            conn.close()
            
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON data'}, status=400)
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def handle_api_reclassify(self):
        """Clear a book's classification to send it back to the unclassified pool."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            book_id = data.get('book_id')
            
            if not book_id:
                self._send_json({'error': 'Missing book_id'}, status=400)
                return

            conn = self._open_db_rw()
            cursor = conn.cursor()
            
            # Step 1: Delete tags
            cursor.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
            
            # Step 2: Delete classification
            cursor.execute("DELETE FROM book_classifications WHERE book_id = ?", (book_id,))
            
            if cursor.rowcount == 0:
                # If nothing was deleted from book_classifications, it might not have existed, but that's fine.
                # However, since they clicked from the UI, it should exist.
                self._send_json({'error': 'Book classification not found'}, status=404)
            else:
                conn.commit()
                self._send_json({'success': True, 'message': 'Book sent to unclassified pool successfully'})
                
            conn.close()
            
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON data'}, status=400)
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def handle_api_delete_book(self):
        """Delete a book and all its associated data permanently from the database."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            book_id = data.get('book_id')
            
            if not book_id:
                self._send_json({'error': 'Missing book_id'}, status=400)
                return

            conn = self._open_db_rw()
            cursor = conn.cursor()
            
            # Step 1: Delete tags
            cursor.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
            
            # Step 2: Delete classification
            cursor.execute("DELETE FROM book_classifications WHERE book_id = ?", (book_id,))
            
            # Step 3: Delete from main books table
            cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
            
            if cursor.rowcount == 0:
                self._send_json({'error': 'Book not found'}, status=404)
            else:
                conn.commit()
                self._send_json({'success': True, 'message': 'Book completely deleted from database'})
                
            conn.close()
            
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON data'}, status=400)
        except sqlite3.Error as e:
            self._send_json({'error': str(e)}, status=500)

    def handle_api_open_weread(self):
        """Invoke the local automation script to open the book in WeRead via uiautomator2."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            title = data.get('title')
            author = data.get('author', '')
            
            if not title:
                self._send_json({'error': 'Missing book title'}, status=400)
                return

            import subprocess
            
            # The script should be in the same directory as viewer.py or accessible
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'weread_open_book_api.py')
            
            # Use the local virtual environment Python
            python_exec = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'bin', 'python')
            
            args = [python_exec, script_path, title]
            if author:
                args.extend(["--author", author])
                
            print(f"Executing: {' '.join(args)}")
            
            # Run the automation script synchronously
            # Depending on how long it takes, we might want to return immediately and run async,
            # but returning success after it completes provides better UI feedback.
            # Timeout set to 40 seconds because UI testing can be slow.
            result = subprocess.run(args, capture_output=True, text=True, timeout=40)
            
            if result.returncode == 0 and 'SUCCESS' in result.stdout:
                self._send_json({'success': True, 'message': 'Successfully opened reading view.'})
            else:
                self._send_json({'error': f"Failed to automate WeRead. Logs: {result.stdout} {result.stderr}"}, status=500)
                
        except subprocess.TimeoutExpired:
            self._send_json({'error': 'Automation script timed out.'}, status=504)
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON data'}, status=400)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web Visualizer for Douban Books Database")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--db", type=str, default="output/books.db", help="Path to the SQLite database")
    args = parser.parse_args()

    DB_PATH = args.db
    
    if not os.path.exists(DB_PATH):
        print(f"Warning: Database file not found at {DB_PATH}. The visualizer might show an error.")

    # Create static directory if it doesn't exist to prevent 404s
    os.makedirs("static", exist_ok=True)

    Handler = BookVisualizerHandler
    
    # allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", args.port), Handler) as httpd:
        print(f"🌟 Starting Visualizer Server at http://localhost:{args.port}")
        print(f"📊 Using database at: {DB_PATH}")
        print(f"Type Ctrl+C to stop the server.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

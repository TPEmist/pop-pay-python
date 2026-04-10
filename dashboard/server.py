import http.server
import sqlite3
import json
import os
import sys
import webbrowser
import argparse
from datetime import date
from urllib.parse import urlparse, parse_qs

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".config", "pop-pay", "pop_state.db")
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

class DashboardRequestHandler(http.server.BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == "/api/budget/today":
            self.get_budget_today()
        elif path == "/api/seals":
            query = parse_qs(parsed_path.query)
            status_filter = query.get("status", [None])[0]
            self.get_seals(status_filter)
        elif path.startswith("/api/"):
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())
        else:
            self.serve_static(path)

    def do_PUT(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path.startswith("/api/settings/"):
            key = path.split("/")[-1]
            self.put_setting(key)
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        
        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        
        # Security: prevent directory traversal
        if not os.path.commonpath([STATIC_DIR, os.path.abspath(file_path)]) == STATIC_DIR:
            self._set_headers(403, "text/plain")
            self.wfile.write(b"Forbidden")
            return

        if os.path.exists(file_path) and os.path.isfile(file_path):
            content_type = "text/html"
            if file_path.endswith(".js"):
                content_type = "application/javascript"
            elif file_path.endswith(".css"):
                content_type = "text/css"
            elif file_path.endswith(".png"):
                content_type = "image/png"
            
            self._set_headers(200, content_type)
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"Not Found")

    def get_db_connection(self):
        return sqlite3.connect(self.server.db_path)

    def get_budget_today(self):
        today = date.today().isoformat()
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Get spent
        cursor.execute("SELECT spent_amount FROM daily_budget WHERE date = ?", (today,))
        row = cursor.fetchone()
        spent = row[0] if row else 0.0
        
        # Get max budget from settings
        cursor.execute("SELECT value FROM dashboard_settings WHERE key = 'max_daily_budget'")
        row = cursor.fetchone()
        max_budget = float(row[0]) if row else 500.0
        
        conn.close()
        
        data = {
            "spent": spent,
            "max": max_budget,
            "remaining": max_budget - spent
        }
        self._set_headers()
        self.wfile.write(json.dumps(data).encode())

    def get_seals(self, status_filter=None):
        conn = self.get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if status_filter:
            cursor.execute(
                "SELECT seal_id, amount, vendor, status, masked_card, timestamp FROM issued_seals WHERE LOWER(status) = LOWER(?) ORDER BY timestamp DESC",
                (status_filter,)
            )
        else:
            cursor.execute(
                "SELECT seal_id, amount, vendor, status, masked_card, timestamp FROM issued_seals ORDER BY timestamp DESC"
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        seals = [dict(row) for row in rows]

        # Decrypt masked_card for display
        import hashlib, hmac, socket, base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            enc_key = hmac.new(b"pop-pay-state-salt", socket.gethostname().encode(), hashlib.sha256).digest()
            for seal in seals:
                mc = seal.get("masked_card")
                if mc:
                    try:
                        data = base64.b64decode(mc)
                        if len(data) >= 28:
                            nonce, tag, ct = data[:12], data[12:28], data[28:]
                            aesgcm = AESGCM(enc_key)
                            seal["masked_card"] = aesgcm.decrypt(nonce, tag + ct, None).decode("utf-8")
                    except Exception:
                        pass  # Already plaintext or corrupt
        except Exception:
            pass  # cryptography not installed — show raw

        self._set_headers()
        self.wfile.write(json.dumps(seals).encode())

    def put_setting(self, key):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            value = str(data.get("value"))
        except (json.JSONDecodeError, KeyError):
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON or missing value"}).encode())
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO dashboard_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value)
        )
        conn.commit()
        conn.close()
        
        self._set_headers()
        self.wfile.write(json.dumps({"key": key, "value": value}).encode())

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_budget (
            date TEXT PRIMARY KEY,
            spent_amount FLOAT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issued_seals (
            seal_id TEXT PRIMARY KEY,
            amount FLOAT,
            vendor TEXT,
            status TEXT,
            masked_card TEXT,
            expiration_date TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

class PopDashboardServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, db_path):
        super().__init__(server_address, RequestHandlerClass)
        self.db_path = db_path

def create_server(port=3210, db_path=DEFAULT_DB_PATH):
    init_db(db_path)
    server = PopDashboardServer(("127.0.0.1", port), DashboardRequestHandler, db_path)
    return server

def main():
    parser = argparse.ArgumentParser(description="Pop-Pay Dashboard Server")
    parser.add_argument("--port", type=int, default=3210, help="Port to run the server on (default: 3210)")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    
    args, _ = parser.parse_known_args()
    
    server = create_server(args.port, args.db)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Starting dashboard server at {url}")
    print(f"Using database: {args.db}")
    
    if not args.no_open:
        webbrowser.open(url)
        
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()
        sys.exit(0)

if __name__ == "__main__":
    main()

import sqlite3
import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from config import Config

logger = logging.getLogger(__name__)

class DatabaseManager:
    _lock = threading.Lock()
    
    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_db()
        
    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS windows (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        market TEXT,
                        opened_at DATETIME,
                        threshold_price DECIMAL,
                        binance_open_price DECIMAL,
                        mint_amount_ngn INTEGER,
                        pairs_minted INTEGER,
                        up_sells_filled INTEGER DEFAULT 0,
                        down_sells_filled INTEGER DEFAULT 0,
                        avg_up_fill_price DECIMAL DEFAULT 0,
                        avg_down_fill_price DECIMAL DEFAULT 0,
                        pairs_burned INTEGER DEFAULT 0,
                        burn_recovered_ngn INTEGER DEFAULT 0,
                        singles_resolved_up INTEGER DEFAULT 0,
                        singles_resolved_down INTEGER DEFAULT 0,
                        resolution TEXT,
                        sell_revenue_ngn INTEGER DEFAULT 0,
                        win_payout_ngn INTEGER DEFAULT 0,
                        net_pnl_ngn INTEGER DEFAULT 0,
                        kill_switch_fired BOOLEAN DEFAULT 0,
                        kill_switch_reason TEXT,
                        postonly_rejections INTEGER DEFAULT 0,
                        reprice_count INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        window_id INTEGER,
                        filled_at DATETIME,
                        side TEXT,
                        shares INTEGER,
                        price_ngn DECIMAL,
                        elapsed_seconds INTEGER,
                        order_id TEXT,
                        FOREIGN KEY(window_id) REFERENCES windows(id)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS balance_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at DATETIME,
                        wallet_balance_ngn INTEGER,
                        open_orders_count INTEGER,
                        daily_pnl_ngn INTEGER
                    )
                """)
                conn.commit()

    def insert_window(self, data: Dict[str, Any]) -> int:
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                columns = ', '.join(data.keys())
                placeholders = ', '.join(['?'] * len(data))
                sql = f"INSERT INTO windows ({columns}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid

    def update_window(self, window_id: int, updates: Dict[str, Any]):
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                sql = f"UPDATE windows SET {set_clause} WHERE id = ?"
                values = tuple(updates.values()) + (window_id,)
                cursor.execute(sql, values)
                conn.commit()

    def insert_fill(self, fill_data: Dict[str, Any]):
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                columns = ', '.join(fill_data.keys())
                placeholders = ', '.join(['?'] * len(fill_data))
                sql = f"INSERT INTO fills ({columns}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(fill_data.values()))
                conn.commit()

    def insert_snapshot(self, snapshot_data: Dict[str, Any]):
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                columns = ', '.join(snapshot_data.keys())
                placeholders = ', '.join(['?'] * len(snapshot_data))
                sql = f"INSERT INTO balance_snapshots ({columns}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(snapshot_data.values()))
                conn.commit()

    def get_daily_pnl(self) -> int:
        today_iso = datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                # Sum the net_pnl_ngn for all windows opened today (UTC)
                cursor.execute("SELECT SUM(net_pnl_ngn) FROM windows WHERE opened_at LIKE ?", (f"{today_iso}%",))
                row = cursor.fetchone()
                return int(row[0] or 0)

    def print_daily_report(self):
        today_iso = datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, market, net_pnl_ngn, kill_switch_fired FROM windows WHERE opened_at LIKE ?", (f"{today_iso}%",))
                rows = cursor.fetchall()
                print("========================================")
                print(f"Daily Report for {today_iso}")
                if not rows:
                    print("No windows recorded today.")
                else:
                    net = 0
                    for r in rows:
                        print(f"Window {r[0]} ({r[1]}): P&L = ₦{r[2]} | Kill-Switch: {'Yes' if r[3] else 'No'}")
                        net += r[2]
                    print("----------------------------------------")
                    print(f"Total Daily P&L: ₦{net}")
                print("========================================")

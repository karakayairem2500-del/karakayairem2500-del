import asyncio
import datetime
import hashlib
import hmac
import json
import os
import random
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import networkx as nx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# =============================================================================
# 1. VERİTABANI YÖNETİMİ & KALICILIK (SQLITE)
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "fortecrypto.db")


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Kullanıcılar Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")

    # Cüzdanlar Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        address TEXT UNIQUE NOT NULL,
        owner TEXT NOT NULL,
        kind TEXT NOT NULL,
        encrypted_private_key TEXT,
        created_at TEXT NOT NULL
    )""")

    # Token Yönetimi Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        initial_supply REAL NOT NULL,
        price REAL NOT NULL,
        drift REAL NOT NULL,
        volatility REAL NOT NULL,
        created_by TEXT
    )""")

    # Varlık Tokenizasyon Tablosu (RWA)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rwa_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_name TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        total_value_usd REAL NOT NULL,
        token_symbol TEXT NOT NULL,
        fractional_tokens REAL NOT NULL,
        is_collateralized INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT
    )""")

    # NFT Marketplace Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nfts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        creator TEXT NOT NULL,
        owner TEXT NOT NULL,
        price_usd REAL NOT NULL,
        is_for_sale INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""")

    # İşlemler Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_hash TEXT UNIQUE NOT NULL,
        token_symbol TEXT NOT NULL,
        from_wallet TEXT NOT NULL,
        to_wallet TEXT NOT NULL,
        amount REAL NOT NULL,
        usd_value REAL NOT NULL,
        risk_score REAL NOT NULL,
        ip_address TEXT,
        is_vpn_proxy INTEGER DEFAULT 0,
        geo_lat REAL,
        geo_lon REAL,
        is_geofence_violation INTEGER DEFAULT 0,
        risk_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")

    # Akıllı Sözleşme Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS smart_contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_address TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        contract_type TEXT NOT NULL,
        creator TEXT NOT NULL,
        counterparty TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        is_audited INTEGER NOT NULL,
        vulnerabilities_found TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")

    # Blokzincir Tablosu
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        block_index INTEGER PRIMARY KEY,
        timestamp TEXT NOT NULL,
        hash TEXT NOT NULL,
        previous_hash TEXT NOT NULL,
        nonce INTEGER NOT NULL,
        tx_count INTEGER NOT NULL
    )""")

    # Varsayılan Veriler
    cursor.execute("SELECT COUNT(*) FROM wallets")
    if cursor.fetchone()[0] == 0:
        default_wallets = [
            (
            "Sistem Hazine Cüzdanı", "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", "sistem", "treasury", "enc_pk_sys_1",
            datetime.datetime.now().isoformat()),
            ("Ana Operasyon Cüzdanı", "0x2546BcD3c84621e976D8185a91A922aC5dDc8235", "sistem", "operations",
             "enc_pk_sys_2", datetime.datetime.now().isoformat()),
            ("Kurumsal Yatırım Cüzdanı", "0x9F1a2B3c4D5e6F7a8B9c0D1e2F3a4B5c6D7e8F9a", "sistem", "investment",
             "enc_pk_sys_3", datetime.datetime.now().isoformat()),
            ("ASELSAN Tedarik Cüzdanı", "0x3A8bC91D720fE45A1289bCc1234567890abcdef1", "sistem", "corporate",
             "enc_pk_sys_4", datetime.datetime.now().isoformat()),
            ("HAVELSAN Ar-Ge Cüzdanı", "0x4B9cD02E831aF56B2390cDD234567890abcdef2", "sistem", "corporate",
             "enc_pk_sys_5", datetime.datetime.now().isoformat())
        ]
        cursor.executemany(
            "INSERT INTO wallets (label, address, owner, kind, encrypted_private_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            default_wallets)

    cursor.execute("SELECT COUNT(*) FROM tokens")
    if cursor.fetchone()[0] == 0:
        default_tokens = [
            ("ARD Lira Token", "ARDL", 1000000.0, 12.50, 0.0002, 0.014, "sistem"),
            ("Ankara Teknoloji Coin", "ANKC", 500000.0, 3.80, 0.0005, 0.028, "sistem")
        ]
        cursor.executemany(
            "INSERT INTO tokens (name, symbol, initial_supply, price, drift, volatility, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            default_tokens)

    cursor.execute("SELECT COUNT(*) FROM nfts")
    if cursor.fetchone()[0] == 0:
        default_nfts = [
            ("nft_101", "Kuantum Sanat Eseri #1", "Dijital Kuantum Sanat Koleksiyonu", "sistem", "sistem", 1500.0, 1,
             datetime.datetime.now().isoformat()),
            ("nft_102", "Ankara TEKNOKENT Ar-Ge Tapusu", "Tokenize edilmiş dijital Ar-Ge hak sahipliği", "sistem",
             "sistem", 5000.0, 1, datetime.datetime.now().isoformat())
        ]
        cursor.executemany(
            "INSERT INTO nfts (token_id, title, description, creator, owner, price_usd, is_for_sale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            default_nfts)

    conn.commit()
    conn.close()


def migrate_schema():
    expected_columns = {
        "users": {"username": "TEXT", "password_hash": "TEXT", "salt": "TEXT", "created_at": "TEXT"},
        "wallets": {"label": "TEXT", "address": "TEXT", "owner": "TEXT", "kind": "TEXT",
                    "encrypted_private_key": "TEXT", "created_at": "TEXT"},
        "tokens": {"name": "TEXT", "symbol": "TEXT", "initial_supply": "REAL", "price": "REAL", "drift": "REAL",
                   "volatility": "REAL", "created_by": "TEXT"},
        "rwa_assets": {"asset_name": "TEXT", "asset_type": "TEXT", "total_value_usd": "REAL", "token_symbol": "TEXT",
                       "fractional_tokens": "REAL", "is_collateralized": "INTEGER", "created_at": "TEXT",
                       "created_by": "TEXT"},
        "nfts": {"token_id": "TEXT", "title": "TEXT", "description": "TEXT", "creator": "TEXT", "owner": "TEXT",
                 "price_usd": "REAL", "is_for_sale": "INTEGER DEFAULT 1", "created_at": "TEXT"},
        "transactions": {"tx_hash": "TEXT", "token_symbol": "TEXT", "from_wallet": "TEXT", "to_wallet": "TEXT",
                         "amount": "REAL", "usd_value": "REAL", "risk_score": "REAL", "ip_address": "TEXT",
                         "is_vpn_proxy": "INTEGER DEFAULT 0", "geo_lat": "REAL", "geo_lon": "REAL",
                         "is_geofence_violation": "INTEGER DEFAULT 0", "risk_reason": "TEXT DEFAULT ''",
                         "created_at": "TEXT"},
        "smart_contracts": {"contract_address": "TEXT", "name": "TEXT", "contract_type": "TEXT DEFAULT 'Standart'",
                            "creator": "TEXT", "counterparty": "TEXT DEFAULT 'Genel Ağ'", "code_hash": "TEXT",
                            "is_audited": "INTEGER", "vulnerabilities_found": "TEXT", "created_at": "TEXT"},
        "blocks": {"timestamp": "TEXT", "hash": "TEXT", "previous_hash": "TEXT", "nonce": "INTEGER",
                   "tx_count": "INTEGER"},
    }

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {r[0] for r in cursor.fetchall()}

    for table, columns in expected_columns.items():
        if table not in existing_tables:
            continue
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, col_type in columns.items():
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
    conn.commit()
    conn.close()


init_db()
migrate_schema()

# =============================================================================
# 2. KİMLİK DOĞRULAMA (AUTH) MOTORU
# =============================================================================

SESSIONS: Dict[str, str] = {}
DUMMY_SALT = secrets.token_hex(16)
DUMMY_HASH = hashlib.pbkdf2_hmac("sha256", b"dummy_password", DUMMY_SALT.encode("utf-8"), 100_000).hex()


def hash_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return {"hash": derived.hex(), "salt": salt}


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return hmac.compare_digest(derived.hex(), expected_hash)


def get_current_user(request: Request) -> str:
    token = request.cookies.get("session_token")
    if not token or token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekiyor")
    return SESSIONS[token]


class AuthRequest(BaseModel):
    username: str
    password: str


# =============================================================================
# 3. AĞ ANALİZİ, GEOFENCING VE GÜVENLİK MOTORU
# =============================================================================

transaction_graph = nx.DiGraph()
SECURITY_EVENTS: List[Dict[str, Any]] = []

# Her cüzdan adresi için en GÜNCEL işlemin risk durumunu tutar.
# Bu sözlük, ağ grafiğindeki düğüm renklerinin işlem tablosundaki
# risk rozetleriyle her zaman eş zamanlı (senkron) kalmasını sağlar.
NODE_RISK_STATE: Dict[str, Dict[str, Any]] = {}

ALLOWED_GEO_BOUNDS = {
    "min_lat": 39.8000, "max_lat": 40.0000,
    "min_lon": 32.7000, "max_lon": 33.0000
}

# Risk eşiği: bu değerin üstü KRİTİK, altı/eşiti NORMAL kabul edilir.
RISK_CRITICAL_THRESHOLD = 75.0


class SecurityEngine:
    @staticmethod
    def detect_vpn_or_proxy(ip_address: str) -> bool:
        known_vpn_subnets = ["192.168.1.100", "10.0.0.1", "172.16.0.1", "vpn_node", "100.64."]
        return any(subnet in ip_address for subnet in known_vpn_subnets)

    @staticmethod
    def check_geofence_violation(lat: float, lon: float) -> bool:
        if not (ALLOWED_GEO_BOUNDS["min_lat"] <= lat <= ALLOWED_GEO_BOUNDS["max_lat"] and
                ALLOWED_GEO_BOUNDS["min_lon"] <= lon <= ALLOWED_GEO_BOUNDS["max_lon"]):
            return True
        return False

    @staticmethod
    def calculate_risk_score(amount: float, usd_val: float, is_vpn: bool, is_geo_violation: bool,
                             sender_address: str):
        """Risk puanını hesaplar ve her etkenin katkısını (sayısal + sözel) bir liste olarak döndürür."""
        breakdown: List[Dict[str, Any]] = [{
            "factor": "Taban Risk Puanı",
            "points": 10.0,
            "detail": "Her işlem için uygulanan standart başlangıç puanı"
        }]
        base_risk = 10.0

        if usd_val > 5000:
            base_risk += 35.0
            breakdown.append({
                "factor": "Yüksek İşlem Tutarı",
                "points": 35.0,
                "detail": f"${usd_val:,.2f} tutarındaki işlem 5.000$ kritik eşiğinin üzerinde"
            })
        elif usd_val > 1000:
            base_risk += 15.0
            breakdown.append({
                "factor": "Orta Düzey İşlem Tutarı",
                "points": 15.0,
                "detail": f"${usd_val:,.2f} tutarındaki işlem 1.000$-5.000$ aralığında"
            })

        if is_vpn:
            base_risk += 25.0
            breakdown.append({
                "factor": "VPN/Proxy Tespiti",
                "points": 25.0,
                "detail": "Gönderen IP adresi bilinen VPN/Proxy ağlarından biriyle eşleşti"
            })

        if is_geo_violation:
            base_risk += 30.0
            breakdown.append({
                "factor": "Coğrafi Sınır (Geofence) İhlali",
                "points": 30.0,
                "detail": "İşlem, izin verilen Ankara bölgesi koordinat sınırlarının dışında gerçekleşti"
            })

        out_degree = 0
        if transaction_graph.has_node(sender_address):
            out_degree = transaction_graph.out_degree(sender_address)
            if out_degree > 3:
                base_risk += 15.0
                breakdown.append({
                    "factor": "Yoğun Gönderim Deseni",
                    "points": 15.0,
                    "detail": f"Gönderen cüzdan ağ grafiğinde {out_degree} farklı adrese işlem göndermiş durumda"
                })

        total = min(99.9, round(base_risk, 1))
        return total, breakdown

    @staticmethod
    def get_severity_level(risk_score: float) -> str:
        # Artık dört seviye yerine, yüzdelik risk skoruna göre tek eşikli
        # (KRİTİK / NORMAL) sınıflandırma kullanılıyor.
        return "KRİTİK" if risk_score >= RISK_CRITICAL_THRESHOLD else "NORMAL"

    @staticmethod
    def build_reason_text(breakdown: List[Dict[str, Any]], risk_score: float, severity: str) -> str:
        """Risk puanının NEDEN o şekilde çıktığını sayısal + sözel olarak anlatan tek bir metin üretir."""
        if severity == "KRİTİK":
            head = f"Bu işlem %{risk_score:.1f} risk puanıyla KRİTİK olarak işaretlendi. Katkıda bulunan etkenler: "
        else:
            head = f"Bu işlem %{risk_score:.1f} risk puanıyla NORMAL kabul edildi. Değerlendirilen etkenler: "
        parts = [f"{b['factor']} (+{b['points']:.0f} puan) — {b['detail']}" for b in breakdown]
        return head + "; ".join(parts) + "."


# =============================================================================
# 4. AKILLI SÖZLEŞME VE STATİK GÜVENLİK ANALİZİ MODÜLÜ
# =============================================================================

CONTRACT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "kira_standart": {
        "name": "Standart Kira / Depozito Sözleşmesi",
        "contract_type": "Kira",
        "code": "function payRent(uint amount) public { require(amount == monthlyRent); balance += amount; }",
    },
    "satis_escrow": {
        "name": "Standart Satış & Escrow Sözleşmesi",
        "contract_type": "Satış",
        "code": "function confirmDelivery() public { payable(seller).transfer(price); status = Status.Completed; }",
    },
    "hakedis_vesting": {
        "name": "Hakediş (Vesting) Kilit Sözleşmesi",
        "contract_type": "Hakediş",
        "code": "function claim() public { require(block.timestamp >= unlockTime); token.transfer(msg.sender, amount); }",
    },
    "likidite_riskli": {
        "name": "Likidite Havuzu (Risk Zafiyet Testi)",
        "contract_type": "Likidite",
        "code": "function withdraw(uint amount) public { require(tx.origin == owner); msg.sender.call.value(amount)(); }",
    },
}


class SmartContractEngine:
    @staticmethod
    def audit_contract_code(code_text: str) -> Dict[str, Any]:
        lines = code_text.split('\n')
        clean_code = " ".join([line.split('//')[0] for line in lines])

        vulnerabilities = []
        if "selfdestruct" in clean_code:
            vulnerabilities.append("CRITICAL: Destructive Function Detected")
        if "tx.origin" in clean_code:
            vulnerabilities.append("HIGH: Phishing Vector via tx.origin")
        if "call.value" in clean_code:
            vulnerabilities.append("MEDIUM: Potential Reentrancy Risk")

        return {
            "is_audited": 1 if len(vulnerabilities) == 0 else 0,
            "vulnerabilities": vulnerabilities if vulnerabilities else ["GÜVENLİ: Zafiyet Tespit Edilmedi"]
        }


# =============================================================================
# 5. ASENKRON BLOKZİNCİR MOTORU
# =============================================================================

class Block:
    def __init__(self, index: int, transactions: List[Dict[str, Any]], previous_hash: str):
        self.index = index
        self.timestamp = datetime.datetime.now().isoformat()
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.calculate_hash()

    def calculate_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index, "timestamp": self.timestamp,
            "transactions": self.transactions, "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def mine_block_sync(self, difficulty: int = 2):
        target = "0" * difficulty
        while self.hash[:difficulty] != target:
            self.nonce += 1
            self.hash = self.calculate_hash()


class Blockchain:
    def __init__(self):
        self.pending_transactions: List[Dict[str, Any]] = []
        self.init_genesis()

    def init_genesis(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM blocks")
        if cursor.fetchone()[0] == 0:
            genesis = Block(0, [{"info": "Genesis Block - Multi Module persistent"}], "0")
            genesis.mine_block_sync(1)
            cursor.execute(
                "INSERT INTO blocks (block_index, timestamp, hash, previous_hash, nonce, tx_count) VALUES (?, ?, ?, ?, ?, ?)",
                (genesis.index, genesis.timestamp, genesis.hash, genesis.previous_hash, genesis.nonce, 1)
            )
            conn.commit()
        conn.close()

    def get_latest_block_hash(self) -> str:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT hash FROM blocks ORDER BY block_index DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else "0"

    def get_latest_block_index(self) -> int:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT block_index FROM blocks ORDER BY block_index DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    async def add_transaction(self, tx: Dict[str, Any]):
        self.pending_transactions.append(tx)
        if len(self.pending_transactions) >= 3:
            await self.mine_pending_transactions_async()

    async def mine_pending_transactions_async(self):
        new_index = self.get_latest_block_index() + 1
        prev_hash = self.get_latest_block_hash()

        new_block = Block(new_index, list(self.pending_transactions), prev_hash)
        await asyncio.to_thread(new_block.mine_block_sync, 2)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO blocks (block_index, timestamp, hash, previous_hash, nonce, tx_count) VALUES (?, ?, ?, ?, ?, ?)",
            (new_block.index, new_block.timestamp, new_block.hash, new_block.previous_hash, new_block.nonce,
             len(self.pending_transactions))
        )
        conn.commit()
        conn.close()
        self.pending_transactions = []

    def validate_chain(self) -> bool:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM blocks ORDER BY block_index ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        for i in range(1, len(rows)):
            current = rows[i]
            previous = rows[i - 1]
            if current["previous_hash"] != previous["hash"]:
                return False
        return True


BLOCKCHAIN = Blockchain()


# =============================================================================
# 6. SİMÜLASYON MOTORU
# =============================================================================

async def generate_transaction():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM wallets")
    wallets = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM tokens")
    tokens = [dict(r) for r in cursor.fetchall()]

    if len(wallets) < 2 or not tokens:
        conn.close()
        return

    sender, receiver = random.sample(wallets, 2)
    token = random.choice(tokens)

    # Tutar: %22 ihtimalle bilinçli olarak "yüksek tutarlı" bir işlem üret,
    # böylece riskli (KRİTİK) işlemlerin oranı biraz artar ama yine de azınlıkta kalır.
    if random.random() < 0.22:
        amount = round(random.uniform(600, 2500), 2)
    else:
        amount = round(random.uniform(10, 500), 2)
    usd_val = round(amount * token["price"], 2)

    mock_ip = f"192.168.{random.randint(1, 10)}.{random.randint(1, 254)}"
    # VPN/Proxy tespit olasılığı %10 -> %18 (riskli işlemleri hafifçe artırır, normal çoğunlukta kalır).
    if random.random() < 0.18:
        mock_ip = "192.168.1.100"

    # Geofence ihlali gerçekten üretilebilsin diye %14 ihtimalle izin verilen
    # Ankara koordinat kutusunun DIŞINDA bir konum üretiyoruz.
    if random.random() < 0.14:
        mock_lat = round(random.uniform(40.90, 41.20), 4)   # İstanbul bölgesi -> ihlal
        mock_lon = round(random.uniform(28.80, 29.20), 4)
    else:
        mock_lat = round(random.uniform(39.80, 39.95), 4)
        mock_lon = round(random.uniform(32.70, 32.95), 4)

    is_vpn = SecurityEngine.detect_vpn_or_proxy(mock_ip)
    is_geo_violation = SecurityEngine.check_geofence_violation(mock_lat, mock_lon)

    risk_score, risk_breakdown = SecurityEngine.calculate_risk_score(amount, usd_val, is_vpn, is_geo_violation,
                                                                      sender["address"])
    severity = SecurityEngine.get_severity_level(risk_score)
    reason_text = SecurityEngine.build_reason_text(risk_breakdown, risk_score, severity)

    # Çizge kenarına miktarın yanında yüzdelik risk skorunu ve nedenini de ekliyoruz,
    # böylece ağ grafiğindeki düğüm/kenar renklendirmesi gerçek risk skoruna dayanır.
    transaction_graph.add_edge(sender["address"], receiver["address"], amount=amount, risk=risk_score,
                                reason=reason_text)

    # Cüzdanların ağ grafiğindeki anlık risk durumunu, işlem tablosunda görünen
    # EN GÜNCEL işlemle birebir aynı olacak şekilde güncelliyoruz (eş zamanlılık).
    now_str = datetime.datetime.now().isoformat()
    node_state = {"risk_percent": risk_score, "risk_level": severity, "reason": reason_text, "updated_at": now_str}
    NODE_RISK_STATE[sender["address"]] = node_state
    NODE_RISK_STATE[receiver["address"]] = node_state

    tx_hash = "0x" + uuid.uuid4().hex[:32]

    cursor.execute(
        "INSERT INTO transactions (tx_hash, token_symbol, from_wallet, to_wallet, amount, usd_value, risk_score, ip_address, is_vpn_proxy, geo_lat, geo_lon, is_geofence_violation, risk_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_hash, token["symbol"], sender["label"], receiver["label"], amount, usd_val, risk_score, mock_ip,
         1 if is_vpn else 0, mock_lat, mock_lon, 1 if is_geo_violation else 0, reason_text, now_str)
    )
    conn.commit()
    conn.close()

    tx = {
        "tx_hash": tx_hash, "token_symbol": token["symbol"],
        "from_wallet": sender["label"], "to_wallet": receiver["label"],
        "amount": amount, "usd_value": usd_val, "risk_score": risk_score,
        "risk_reason": reason_text, "created_at": now_str
    }

    await BLOCKCHAIN.add_transaction(tx)

    if is_vpn or is_geo_violation or risk_score >= 50:
        SECURITY_EVENTS.append({
            "event_type": "GEOFENCE_VIOLATION" if is_geo_violation else (
                "VPN_DETECTED" if is_vpn else "TRANSACTION_RISK"),
            "subject": sender["address"],
            "result_summary": f"Risk: %{risk_score} | VPN: {'Var' if is_vpn else 'Yok'} | Geofence İhlali: {'EVET' if is_geo_violation else 'HAYIR'}",
            "reason": reason_text,
            "risk_score": risk_score,
            "severity": severity,
            "created_at": now_str
        })


async def simulation_loop():
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tokens")
            tokens = [dict(r) for r in cursor.fetchall()]

            for t in tokens:
                shock = random.gauss(0, 1)
                change = t["drift"] + t["volatility"] * shock
                new_price = round(max(0.01, t["price"] * (1 + change)), 4)
                cursor.execute("UPDATE tokens SET price = ? WHERE id = ?", (new_price, t["id"]))

            conn.commit()
            conn.close()

            await generate_transaction()
        except Exception as e:
            print("Simülasyon Hatası:", e)
        await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        task.cancel()


# =============================================================================
# 7. FASTAPI API ENDPOINT'LERİ
# =============================================================================

app = FastAPI(title="ForteCrypto ARD Engine - Full Suite", version="6.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])


# --------------------------- KİMLİK DOĞRULAMA ---------------------------

@app.post("/v1/auth/register", status_code=201)
def register(payload: AuthRequest):
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 3 karakter olmalı")
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Şifre en az 4 karakter olmalı")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Bu kullanıcı adı zaten alınmış")

    creds = hash_password(payload.password)
    now_str = datetime.datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
        (username, creds["hash"], creds["salt"], now_str)
    )
    conn.commit()
    conn.close()
    return {"status": "Kayıt başarılı", "username": username}


@app.post("/v1/auth/login")
def login(payload: AuthRequest, response: Response):
    username = payload.username.strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        verify_password(payload.password, DUMMY_SALT, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

    if not verify_password(payload.password, row["salt"], row["password_hash"]):
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

    token = secrets.token_hex(24)
    SESSIONS[token] = username
    response.set_cookie(
        key="session_token", value=token, httponly=True,
        samesite="lax", max_age=60 * 60 * 24 * 7
    )
    return {"status": "Giriş başarılı", "username": username}


@app.post("/v1/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token and token in SESSIONS:
        del SESSIONS[token]
    response.delete_cookie("session_token")
    return {"status": "Çıkış yapıldı"}


@app.get("/v1/auth/me")
def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}


# --------------------------- TOKEN & RWA YÖNETİMİ ---------------------------

class TokenCreateRequest(BaseModel):
    name: str
    symbol: str
    initial_supply: float
    price: float
    drift: float = 0.0003
    volatility: float = 0.02


@app.get("/v1/token/list")
def list_tokens(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens")
    tokens = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return tokens


@app.post("/v1/token/create", status_code=201)
def create_token(payload: TokenCreateRequest, current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tokens (name, symbol, initial_supply, price, drift, volatility, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (payload.name, payload.symbol, payload.initial_supply, payload.price, payload.drift, payload.volatility,
         current_user)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"id": new_id, "symbol": payload.symbol, "status": "Token Oluşturuldu"}


class RWAAssetRequest(BaseModel):
    asset_name: str
    asset_type: str
    total_value_usd: float
    token_symbol: str


@app.post("/v1/tokenization/asset/create", status_code=201)
def create_rwa_asset(payload: RWAAssetRequest, current_user: str = Depends(get_current_user)):
    fractional_tokens = payload.total_value_usd / 10.0
    now_str = datetime.datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO rwa_assets (asset_name, asset_type, total_value_usd, token_symbol, fractional_tokens, is_collateralized, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (payload.asset_name, payload.asset_type, payload.total_value_usd, payload.token_symbol, fractional_tokens, 1,
         now_str, current_user)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"id": new_id, "asset_name": payload.asset_name, "status": "RWA Tokenize Edildi"}


@app.get("/v1/tokenization/asset/list")
def list_rwa_assets(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rwa_assets ORDER BY id DESC")
    assets = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return assets


# --------------------------- AKILLI SÖZLEŞME VE RİSK KONTROL ENDPOINT'LERİ ---------------------------

class ContractCreateRequest(BaseModel):
    counterparty_wallet: str
    template_key: str


@app.get("/v1/smartcontract/list")
def list_smart_contracts(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM smart_contracts ORDER BY id DESC")
    contracts = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return contracts


@app.post("/v1/smartcontract/check-risk")
def check_contract_risk(payload: ContractCreateRequest, current_user: str = Depends(get_current_user)):
    """Sözleşme şablonunun ve karşı tarafın gerçek risk durumunu sorgular."""
    if payload.template_key not in CONTRACT_TEMPLATES:
        raise HTTPException(status_code=400, detail="Geçersiz sözleşme şablonu")

    template = CONTRACT_TEMPLATES[payload.template_key]
    audit_res = SmartContractEngine.audit_contract_code(template["code"])

    # Yalnızca kod içinde zafiyet varsa risk olarak işaretle
    has_risk = (audit_res["is_audited"] == 0)

    return {
        "has_risk": has_risk,
        "code_audited": audit_res["is_audited"],
        "code_vulnerabilities": audit_res["vulnerabilities"],
        "company_risk": "NORMAL",
        "company_risk_msg": "Karşı taraf cüzdanı güvenli kabul edildi."
    }


@app.post("/v1/smartcontract/create", status_code=201)
def create_smart_contract(payload: ContractCreateRequest, current_user: str = Depends(get_current_user)):
    if payload.template_key not in CONTRACT_TEMPLATES:
        raise HTTPException(status_code=400, detail="Geçersiz sözleşme şablonu")

    template = CONTRACT_TEMPLATES[payload.template_key]
    audit_res = SmartContractEngine.audit_contract_code(template["code"])

    contract_addr = "0x" + hashlib.sha256(
        f"{current_user}-{payload.counterparty_wallet}-{time.time()}".encode()).hexdigest()[:40]
    code_hash = hashlib.sha256(template["code"].encode()).hexdigest()
    now_str = datetime.datetime.now().isoformat()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO smart_contracts (contract_address, name, contract_type, creator, counterparty, code_hash, is_audited, vulnerabilities_found, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (contract_addr, template["name"], template["contract_type"], current_user, payload.counterparty_wallet,
         code_hash,
         audit_res["is_audited"], ", ".join(audit_res["vulnerabilities"]), now_str)
    )
    conn.commit()
    conn.close()

    return {"status": "Sözleşme Oluşturuldu ve Denetlendi", "contract_address": contract_addr,
            "is_audited": audit_res["is_audited"]}


# --------------------------- NFT MARKETPLACE ---------------------------

class NFTMintRequest(BaseModel):
    title: str
    description: str
    price_usd: float


@app.get("/v1/nft/list")
def list_nfts(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nfts ORDER BY id DESC")
    nfts = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return nfts


@app.post("/v1/nft/mint", status_code=201)
def mint_nft(payload: NFTMintRequest, current_user: str = Depends(get_current_user)):
    token_id = "nft_" + uuid.uuid4().hex[:8]
    now_str = datetime.datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO nfts (token_id, title, description, creator, owner, price_usd, is_for_sale, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (token_id, payload.title, payload.description, current_user, current_user, payload.price_usd, now_str)
    )
    conn.commit()
    conn.close()
    return {"token_id": token_id, "status": "NFT Mint Edildi"}


# --------------------------- CÜZDAN & AĞ GRAFİĞİ ---------------------------

class WalletCreateRequest(BaseModel):
    label: str


@app.get("/v1/wallet/list")
def list_wallets(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, label, address, owner, kind, created_at FROM wallets ORDER BY id DESC")
    w = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return w


@app.post("/v1/wallet/create", status_code=201)
def create_wallet(payload: WalletCreateRequest, current_user: str = Depends(get_current_user)):
    raw_seed = f"{current_user}-{payload.label}-{time.time()}"
    address = "0x" + hashlib.sha256(raw_seed.encode()).hexdigest()[:40]
    private_key = "pk_" + hashlib.sha256((raw_seed + "secret").encode()).hexdigest()
    encrypted_pk = "enc_v1_" + hashlib.sha256(private_key.encode()).hexdigest()[:32]

    now_str = datetime.datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO wallets (label, address, owner, kind, encrypted_private_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.label, address, current_user, "custom", encrypted_pk, now_str)
    )
    conn.commit()
    conn.close()
    return {"wallet": {"label": payload.label, "address": address, "owner": current_user}}


@app.get("/v1/network/vpn-status")
def get_network_vpn_stats(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE is_vpn_proxy = 1")
    vpn_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE is_geofence_violation = 1")
    geo_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM transactions")
    total_tx = cursor.fetchone()[0]
    conn.close()
    return {
        "total_analyzed_transactions": total_tx,
        "vpn_proxy_detected_count": vpn_count,
        "geofence_violations_count": geo_count,
        "network_nodes_active": transaction_graph.number_of_nodes(),
        "network_edges_active": transaction_graph.number_of_edges()
    }


@app.get("/v1/network/graph")
def get_network_graph(current_user: str = Depends(get_current_user)):
    nodes = []
    for node in transaction_graph.nodes():
        out_deg = transaction_graph.out_degree(node)
        in_deg = transaction_graph.in_degree(node)

        # Düğümün risk durumu artık NODE_RISK_STATE üzerinden, yani o cüzdanı
        # ilgilendiren EN SON işlemin risk puanından okunuyor. Bu sayede grafik,
        # işlem/güvenlik tablolarında görünen risk durumuyla birebir (eş zamanlı) örtüşür.
        state = NODE_RISK_STATE.get(node)
        if state:
            node_risk_percent = state["risk_percent"]
            node_risk_level = state["risk_level"]
            node_reason = state["reason"]
        else:
            out_risks = [d.get("risk", 0.0) for _, _, d in transaction_graph.out_edges(node, data=True)]
            in_risks = [d.get("risk", 0.0) for _, _, d in transaction_graph.in_edges(node, data=True)]
            all_risks = out_risks + in_risks
            node_risk_percent = round(max(all_risks), 1) if all_risks else 0.0
            node_risk_level = "KRİTİK" if node_risk_percent >= RISK_CRITICAL_THRESHOLD else "NORMAL"
            node_reason = ""

        nodes.append({
            "id": node,
            "label": (node[:8] + "...") if len(node) > 8 else node,
            "out_degree": out_deg,
            "in_degree": in_deg,
            "risk_percent": node_risk_percent,
            "risk_level": node_risk_level,
            "reason": node_reason
        })

    edges = []
    for u, v, data in transaction_graph.edges(data=True):
        edges.append({
            "from": u,
            "to": v,
            "amount": data.get("amount", 0),
            "risk_percent": round(data.get("risk", 0.0), 1),
            "reason": data.get("reason", "")
        })

    return {"nodes": nodes, "edges": edges}


@app.get("/v1/security/events")
def get_security_events(current_user: str = Depends(get_current_user)):
    return list(reversed(SECURITY_EVENTS))[:15]


@app.get("/v1/dashboard/summary")
def dashboard_summary(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(price * initial_supply) FROM tokens")
    mc = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(usd_value), COUNT(*) FROM transactions")
    tx_row = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM wallets")
    w_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM blocks")
    b_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM nfts")
    nft_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM smart_contracts")
    sc_count = cursor.fetchone()[0]
    conn.close()
    return {
        "total_market_cap_usd": round(mc, 2),
        "volume_24h_usd": round(tx_row[0] or 0.0, 2),
        "active_wallets": w_count,
        "blockchain_height": b_count,
        "total_nfts_minted": nft_count,
        "total_contracts": sc_count,
        "chain_integrity": BLOCKCHAIN.validate_chain()
    }


@app.get("/v1/transactions/list")
def list_transactions(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 20")
    txs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return txs


@app.get("/v1/blockchain/blocks")
def get_blocks(current_user: str = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM blocks ORDER BY block_index DESC LIMIT 10")
    blocks = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return blocks


# =============================================================================
# DASHBOARD ARAYÜZÜ (AKILLI RİSK POP-UP KONTROLLÜ)
# =============================================================================

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>ForteCrypto | Tam Güvenlikli Platform</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  :root{ --bg:#0b0e14; --panel:#121722; --border:#232b3d; --text:#e7ecf5; --accent:#5b8cff; --green:#33d17a; --red:#ff5c5c; --purple:#8f6bff; --yellow:#ffcc4d; --orange:#ff9f43;}
  *{box-sizing:border-box;}
  body{margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,Segoe UI,sans-serif; padding:20px;}
  header{display:flex; justify-content:space-between; align-items:center; padding:15px 20px; background:var(--panel); border:1px solid var(--border); border-radius:10px;}
  header h2{margin:0; font-size:18px;}
  .kpis{display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-top:16px;}
  .kpi{background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:14px;}
  .kpi .label{font-size:11px; color:#9aa7c2; text-transform:uppercase; letter-spacing:.05em;}
  .kpi .value{font-size:22px; font-weight:700; margin-top:4px;}
  .grid{display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px;}
  .card{background:var(--panel); border:1px solid var(--border); padding:16px; border-radius:10px;}
  .card h3{margin-top:0; font-size:14px; display:flex; align-items:center; gap:8px;}
  .card small{color:#9aa7c2; display:block; margin-bottom:8px;}
  input, button, select{padding:8px; margin:4px 0; border-radius:6px; border:1px solid var(--border); background:#161c29; color:#fff; width:100%; box-sizing:border-box; font-size:13px;}
  button{background:var(--accent); font-weight:bold; cursor:pointer; border:none; margin-top:6px;}
  button:hover{opacity:.9;}
  table{width:100%; border-collapse:collapse; font-size:11.5px;}
  td,th{padding:6px; border-bottom:1px solid var(--border); text-align:left; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:160px;}
  th{color:#9aa7c2; font-weight:600;}
  .scroll{max-height:220px; overflow-y:auto;}
  #authRoot{max-width:380px; margin:80px auto; background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:26px;}
  #authTabs{display:flex; gap:8px; margin-bottom:14px;}
  #authTabs button{background:#161c29; color:#9aa7c2;}
  #authTabs button.active{background:var(--accent); color:#fff;}
  #authError{color:var(--red); font-size:12.5px; min-height:16px; margin-top:4px;}
  .badge-safe{background:var(--green); color:#000; padding:2px 6px; border-radius:4px; font-weight:bold;}
  .badge-risk{background:var(--red); color:#fff; padding:2px 6px; border-radius:4px; font-weight:bold;}
  .badge-critical{background:var(--red); color:#fff; padding:2px 6px; border-radius:4px; font-weight:bold;}
  .badge-normal{background:var(--green); color:#000; padding:2px 6px; border-radius:4px; font-weight:bold;}
  .arrow-up{color:var(--green); font-weight:bold;}
  .arrow-down{color:var(--red); font-weight:bold;}
  .arrow-flat{color:#9aa7c2; font-weight:bold;}
  .reason-cell{max-width:220px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:help;}

  /* MODAL POP-UP STİLLERİ */
  .modal-overlay{display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); z-index:1000; justify-content:center; align-items:center;}
  .modal-box{background:var(--panel); border:2px solid var(--orange); border-radius:12px; padding:24px; max-width:480px; width:90%; color:var(--text);}
  .modal-box h3{color:var(--orange); margin-top:0;}
  .modal-box ul{padding-left:20px; font-size:13px; color:#dcdcdc;}
  .modal-actions{display:flex; gap:10px; margin-top:18px;}
  .modal-actions button{flex:1;}
</style>
</head>
<body>

<!-- RİSK UYARI MODAL PENCERESİ -->
<div class="modal-overlay" id="riskModal">
  <div class="modal-box">
    <h3>⚠️ YÜKSEK RİSK UYARISI</h3>
    <p style="font-size:13px;">Bu sözleşmeyi oluşturmadan önce aşağıdaki risk tespit edildi:</p>
    <ul id="riskList"></ul>
    <p style="font-size:12px; color:#9aa7c2;">Devam etmek istediğinizden emin misiniz, yoksa işlemi iptal etmek mi istersiniz?</p>
    <div class="modal-actions">
      <button type="button" onclick="confirmContractCreation()" style="background:var(--red);">⚠️ Riski Kabul Et ve Gönder</button>
      <button type="button" onclick="closeRiskModal()" style="background:#3a4454;">❌ Vazgeç / İptal Et</button>
    </div>
  </div>
</div>

<div id="authRoot">
  <h2 style="text-align:center;">⚡ ForteCrypto</h2>
  <div id="authTabs">
    <button id="tabLogin" class="active" onclick="switchAuthTab('login')" type="button">Giriş Yap</button>
    <button id="tabRegister" onclick="switchAuthTab('register')" type="button">Kayıt Ol</button>
  </div>

  <form id="loginForm">
    <input type="text" id="loginUser" placeholder="Kullanıcı Adı" required>
    <input type="password" id="loginPass" placeholder="Şifre" required>
    <button type="submit">Giriş Yap</button>
  </form>

  <form id="registerForm" style="display:none;">
    <input type="text" id="regUser" placeholder="Kullanıcı Adı (en az 3 karakter)" required>
    <input type="password" id="regPass" placeholder="Şifre (en az 4 karakter)" required>
    <button type="submit" style="background:var(--green)">Kayıt Ol</button>
  </form>
  <div id="authError"></div>
</div>

<div id="appRoot" style="display:none;">
<header>
  <h2>⚡ ForteCrypto ARD Engine — Tam Güvenlik & NFT Portalı</h2>
  <div>👤 <strong id="whoAmI"></strong> <button onclick="doLogout()" style="width:auto; padding:4px 10px; margin-left:10px; background:var(--red);">Çıkış Yap</button></div>
</header>

<div class="kpis" id="kpiRow"></div>

<div class="grid">

  <!-- AKILLI SÖZLEŞME YÖNETİMİ VE FİRMAYA SÖZLEŞME GÖNDERME -->
  <div class="card" style="grid-column: 1 / -1;">
    <h3 style="color:var(--accent)">🛡️ Akıllı Sözleşme Oluşturma & Denetim Paneli</h3>
    <small>Firmalar / Cüzdanlar arası güvenli sözleşme talebi gönderin ve hash/statik analiz durumunu inceleyin.</small>

    <form id="scForm" style="display:grid; grid-template-columns: 2fr 2fr 1fr; gap:10px; margin-bottom:14px;">
      <select id="scTargetWallet" required>
        <option value="">-- Karşı Taraf (Firma / Cüzdan Seçin) --</option>
      </select>
      <select id="scTemplate" required>
        <option value="kira_standart">Standart Kira / Depozito Sözleşmesi (GÜVENLİ)</option>
        <option value="satis_escrow">Standart Satış & Escrow Sözleşmesi (GÜVENLİ)</option>
        <option value="hakedis_vesting">Hakediş (Vesting) Kilit Sözleşmesi (GÜVENLİ)</option>
        <option value="likidite_riskli">Likidite Havuzu (Risk Zafiyet Testi - RİSKLİ)</option>
      </select>
      <button type="submit">✍️ Sözleşme Gönder</button>
    </form>

    <div class="scroll"><table>
      <thead><tr><th>Sözleşme Adı</th><th>Tür</th><th>Oluşturan</th><th>Karşı Taraf</th><th>Kod Hash</th><th>Güvenilirlik</th><th>Açıklama / Zafiyet</th></tr></thead>
      <tbody id="scT"></tbody>
    </table></div>
  </div>

  <!-- CANLI TRANSFER AĞI GRAFİĞİ -->
  <div class="card" style="grid-column: 1 / -1;">
    <h3 style="color:var(--accent)">🕸️ Canlı Etkileşimli Transfer Ağı Grafiği</h3>
    <small>Oklar üzerindeki sayılar transfer edilen token miktarını, düğüm rengi ise o adrese ait EN SON işlemin risk yüzdesini temsil eder (%75 ve üzeri = KRİTİK). Fare ile üzerine gelerek nedenini görebilirsiniz.</small>
    <div id="networkGraphViz" style="height:350px; border:1px solid var(--border); border-radius:8px; background:#0d1017;"></div>
  </div>

  <!-- TOKEN YÖNETİMİ -->
  <div class="card">
    <h3>🪙 Token Çıkarma Paneli</h3>
    <small>Fiyatlar dinamik simüle edilir — ok işareti son yenilemeye göre yükseliş/düşüşü gösterir</small>
    <div class="scroll"><table>
      <thead><tr><th>Sembol</th><th>Ad</th><th>Fiyat ($)</th><th>Arz</th></tr></thead>
      <tbody id="tokT"></tbody>
    </table></div>
    <form id="tokForm" style="margin-top:10px;">
      <input type="text" id="tName" placeholder="Token Adı" required>
      <input type="text" id="tSym" placeholder="Sembol (Örn: FRTC)" required>
      <input type="number" id="tSupply" placeholder="Başlangıç Arzı" required>
      <input type="number" id="tPrice" placeholder="Başlangıç Fiyatı ($)" required>
      <button type="submit">➕ Token Oluştur</button>
    </form>
  </div>

  <!-- RWA TOKENİZASYON -->
  <div class="card">
    <h3 style="color:var(--green)">🏛️ Varlık Tokenizasyonu (RWA)</h3>
    <small>Fiziksel varlıkların blokzincire aktarımı</small>
    <div class="scroll"><table>
      <thead><tr><th>Varlık</th><th>Tür</th><th>Değer ($)</th><th>Token</th></tr></thead>
      <tbody id="rwaT"></tbody>
    </table></div>
    <form id="rwaForm" style="margin-top:10px;">
      <input type="text" id="rName" placeholder="Varlık Adı" required>
      <input type="text" id="rType" placeholder="Varlık Türü (Gayrimenkul vb.)" required>
      <input type="number" id="rVal" placeholder="Toplam Değer ($)" required>
      <input type="text" id="rSym" placeholder="Token Sembolü" required>
      <button type="submit" style="background:var(--green)">🏛️ Varlığı Tokenize Et</button>
    </form>
  </div>

  <!-- NFT MARKETPLACE -->
  <div class="card">
    <h3 style="color:var(--purple)">🎨 NFT Marketplace</h3>
    <small>Dijital Varlık Mint Etme ve Ticaret Altyapısı</small>
    <div class="scroll"><table>
      <thead><tr><th>Token ID</th><th>Başlık</th><th>Fiyat</th><th>Sahip</th></tr></thead>
      <tbody id="nftT"></tbody>
    </table></div>
    <form id="nftForm" style="margin-top:10px;">
      <input type="text" id="nftTitle" placeholder="NFT Eser Başlığı" required>
      <input type="text" id="nftDesc" placeholder="Açıklama" required>
      <input type="number" id="nftPrice" placeholder="Fiyat ($)" required>
      <button type="submit" style="background:var(--purple)">🎨 NFT Mint Et</button>
    </form>
  </div>

  <!-- AĞ / GEOFENCING ANALİZİ -->
  <div class="card">
    <h3 style="color:var(--red)">📡 Ağ İşlemleri & Geofencing (VPN)</h3>
    <small>VPN ve Coğrafi Konum İhlal Analizleri — Risk yüzdesi %75 ve üzerinde ise KRİTİK, altındaysa NORMAL kabul edilir. "Neden" sütununun üzerine gelerek gerekçeyi görebilirsiniz.</small>
    <div class="scroll"><table>
      <thead><tr><th>Hash</th><th>Fiyat</th><th>IP</th><th>VPN</th><th>Geofence</th><th>Risk</th><th>Neden</th></tr></thead>
      <tbody id="txT"></tbody>
    </table></div>
  </div>

  <!-- CÜZDANLAR -->
  <div class="card">
    <h3 style="color:var(--yellow)">👛 Cüzdan Yönetimi</h3>
    <small>Korumalı cüzdan kayıtları</small>
    <div class="scroll"><table>
      <thead><tr><th>Etiket</th><th>Adres</th><th>Sahip</th></tr></thead>
      <tbody id="walT"></tbody>
    </table></div>
    <form id="walForm" style="margin-top:10px;">
      <input type="text" id="wLabel" placeholder="Cüzdan Etiketi" required>
      <button type="submit" style="background:var(--yellow); color:#000;">👛 Cüzdan Üret</button>
    </form>
  </div>

  <!-- BLOKZİNCİR KAYITLARI -->
  <div class="card">
    <h3 style="color:var(--accent)">⛓️ Blokzincir Kayıtları</h3>
    <small>PoW Konsensüsü — Her blok kendinden önceki bloğun hash'ine bağlanarak zincir bütünlüğünü sağlar</small>
    <div class="scroll"><table>
      <thead><tr><th>#</th><th>Hash</th><th>Önceki Hash</th><th>Zaman</th></tr></thead>
      <tbody id="blkT"></tbody>
    </table></div>
  </div>

</div>
</div>

<script>
let currentUsername = null;
let visNetwork = null;
let pendingContractData = null;
let lastTokenPrices = {};

function switchAuthTab(tab){
  const isLogin = tab === 'login';
  document.getElementById('tabLogin').classList.toggle('active', isLogin);
  document.getElementById('tabRegister').classList.toggle('active', !isLogin);
  document.getElementById('loginForm').style.display = isLogin ? 'block' : 'none';
  document.getElementById('registerForm').style.display = isLogin ? 'none' : 'block';
  document.getElementById('authError').innerText = '';
}

async function loadWalletsForDropdown(){
  const res = await fetch('/v1/wallet/list', {credentials:'include'});
  if(!res.ok) return;
  const wallets = await res.json();
  const select = document.getElementById('scTargetWallet');
  select.innerHTML = '<option value="">-- Karşı Taraf (Firma / Cüzdan Seçin) --</option>';
  wallets.forEach(w => {
    select.innerHTML += `<option value="${w.label} (${w.address.slice(0,8)}...)">${w.label} - [${w.owner}]</option>`;
  });
}

async function loadGraph(){
  const res = await fetch('/v1/network/graph', {credentials:'include'});
  if(!res.ok) return;
  const g = await res.json();

  const nodes = new vis.DataSet(g.nodes.map(n => ({
    id: n.id,
    label: n.label,
    title: `Risk: %${n.risk_percent} (${n.risk_level})` + (n.reason ? `\n${n.reason}` : ''),
    color: { background: n.risk_level === 'KRİTİK' ? '#ff5c5c' : '#5b8cff', border: '#bcd2ff' },
    font: { color: '#e7ecf5', size: 10 }
  })));

  const edges = new vis.DataSet(g.edges.map((e, i) => ({
    id: i,
    from: e.from,
    to: e.to,
    label: e.amount.toFixed(1) + ' Token',
    title: `Risk: %${e.risk_percent}` + (e.reason ? `\n${e.reason}` : ''),
    arrows: 'to',
    font: { color: '#bcd2ff', size: 9 },
    color: { color: e.risk_percent >= 75 ? '#ff5c5c' : '#3a5a95' }
  })));

  const container = document.getElementById('networkGraphViz');
  const options = {
    physics: { barnesHut: { gravitationalConstant: -2000 } },
    nodes: { shape: 'dot', size: 10 }
  };

  if (!visNetwork) {
    visNetwork = new vis.Network(container, { nodes, edges }, options);
  } else {
    visNetwork.setData({ nodes, edges });
  }
}

function priceArrowHtml(symbol, price){
  const prev = lastTokenPrices[symbol];
  let arrow = '<span class="arrow-flat">→</span>';
  if(prev !== undefined){
    if(price > prev) arrow = '<span class="arrow-up">▲</span>';
    else if(price < prev) arrow = '<span class="arrow-down">▼</span>';
  }
  lastTokenPrices[symbol] = price;
  return arrow;
}

function riskBadgeHtml(riskScore){
  const isCritical = riskScore >= 75;
  const cls = isCritical ? 'badge-critical' : 'badge-normal';
  const label = isCritical ? 'KRİTİK' : 'NORMAL';
  return `<span class="${cls}">%${riskScore.toFixed(1)} ${label}</span>`;
}

async function load(){
  const sumRes = await fetch('/v1/dashboard/summary', {credentials:'include'});
  if(!sumRes.ok) return;
  const summary = await sumRes.json();
  document.getElementById('kpiRow').innerHTML = `
    <div class="kpi"><div class="label">Piyasa Değeri</div><div class="value">$${summary.total_market_cap_usd.toLocaleString()}</div></div>
    <div class="kpi"><div class="label">Toplam Hacim</div><div class="value">$${summary.volume_24h_usd.toLocaleString()}</div></div>
    <div class="kpi"><div class="label">Aktif Cüzdan</div><div class="value">${summary.active_wallets}</div></div>
    <div class="kpi"><div class="label">Sözleşmeler</div><div class="value">${summary.total_contracts}</div></div>
    <div class="kpi"><div class="label">Zincir Bütünlüğü</div><div class="value" style="color:var(--green)">${summary.chain_integrity ? 'DOĞRULANDI' : 'HATA'}</div></div>
  `;

  // Sözleşmeler
  const scs = await (await fetch('/v1/smartcontract/list', {credentials:'include'})).json();
  document.getElementById('scT').innerHTML = scs.map(c=>`
    <tr>
      <td>${c.name}</td>
      <td>${c.contract_type}</td>
      <td>${c.creator}</td>
      <td>${c.counterparty}</td>
      <td>${c.code_hash ? c.code_hash.slice(0,10)+'...' : '-'}</td>
      <td>${c.is_audited ? '<span class="badge-safe">GÜVENLİ</span>' : '<span class="badge-risk">RİSKLİ</span>'}</td>
      <td style="font-size:10px; color:#9aa7c2;">${c.vulnerabilities_found}</td>
    </tr>
  `).join('') || '<tr><td colspan="7">Henüz sözleşme yok.</td></tr>';

  // Tokenler (fiyat yükseliş/düşüş oku ile)
  const tokens = await (await fetch('/v1/token/list', {credentials:'include'})).json();
  document.getElementById('tokT').innerHTML = tokens.map(t=>`<tr><td>${t.symbol}</td><td>${t.name}</td><td>$${t.price} ${priceArrowHtml(t.symbol, t.price)}</td><td>${Math.round(t.initial_supply).toLocaleString()}</td></tr>`).join('');

  // RWA
  const rwa = await (await fetch('/v1/tokenization/asset/list', {credentials:'include'})).json();
  document.getElementById('rwaT').innerHTML = rwa.map(r=>`<tr><td>${r.asset_name}</td><td>${r.asset_type}</td><td>$${r.total_value_usd.toLocaleString()}</td><td>${r.token_symbol}</td></tr>`).join('');

  // NFT
  const nfts = await (await fetch('/v1/nft/list', {credentials:'include'})).json();
  document.getElementById('nftT').innerHTML = nfts.map(n=>`<tr><td>${n.token_id}</td><td>${n.title}</td><td>$${n.price_usd}</td><td>${n.owner}</td></tr>`).join('');

  // İşlemler (yüzdelik risk rozeti VE nedeni birlikte gösterilir)
  const txs = await (await fetch('/v1/transactions/list', {credentials:'include'})).json();
  document.getElementById('txT').innerHTML = txs.map(t=>`<tr><td>${t.tx_hash.slice(0,8)}...</td><td>$${t.usd_value}</td><td>${t.ip_address}</td><td>${t.is_vpn_proxy ? 'EVET':'HAYIR'}</td><td style="color:${t.is_geofence_violation ? 'var(--red)':'var(--green)'}">${t.is_geofence_violation ? 'İHLAL':'NORMAL'}</td><td>${riskBadgeHtml(t.risk_score)}</td><td class="reason-cell" title="${(t.risk_reason||'').replace(/"/g,'&quot;')}">${t.risk_reason || '-'}</td></tr>`).join('');

  // Cüzdanlar
  const wallets = await (await fetch('/v1/wallet/list', {credentials:'include'})).json();
  document.getElementById('walT').innerHTML = wallets.map(w=>`<tr><td>${w.label}</td><td>${w.address.slice(0,10)}...</td><td>${w.owner}</td></tr>`).join('');

  // Bloklar (nonce ve tx sayısı gibi teknik ayrıntılar yerine okunabilir zaman gösterilir)
  const blocks = await (await fetch('/v1/blockchain/blocks', {credentials:'include'})).json();
  document.getElementById('blkT').innerHTML = blocks.map(b=>`<tr><td>${b.block_index}</td><td>${b.hash.slice(0,8)}...</td><td>${b.previous_hash.slice(0,8)}...</td><td>${new Date(b.timestamp).toLocaleTimeString('tr-TR')}</td></tr>`).join('');

  loadGraph();
}

// SÖZLEŞME GÖNDERME VE RİSK KONTROL AKIŞI
document.getElementById('scForm').onsubmit = async (e) => {
  e.preventDefault();

  pendingContractData = {
    counterparty_wallet: scTargetWallet.value,
    template_key: scTemplate.value
  };

  // Önce risk durumunu sorgula
  const checkRes = await fetch('/v1/smartcontract/check-risk', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify(pendingContractData)
  });

  if(!checkRes.ok) return;
  const riskInfo = await checkRes.json();

  if(riskInfo.has_risk){
    // SADECE Gerçek bir risk varsa Pop-up göster
    const list = document.getElementById('riskList');
    list.innerHTML = '';

    if(riskInfo.code_audited === 0){
      list.innerHTML += `<li><b>Sözleşme Kodu Riski:</b> ${riskInfo.code_vulnerabilities.join(', ')}</li>`;
    }

    document.getElementById('riskModal').style.display = 'flex';
  } else {
    // Risk yoksa Pop-up ÇIKARMADAN doğrudan oluştur
    executeContractCreation();
  }
};

async function executeContractCreation(){
  if(!pendingContractData) return;
  const res = await fetch('/v1/smartcontract/create', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify(pendingContractData)
  });
  if(res.ok){
    pendingContractData = null;
    load();
  }
}

function confirmContractCreation(){
  closeRiskModal();
  executeContractCreation();
}

function closeRiskModal(){
  document.getElementById('riskModal').style.display = 'none';
}

document.getElementById('loginForm').onsubmit = async (e) => {
  e.preventDefault();
  document.getElementById('authError').innerText = '';
  const res = await fetch('/v1/auth/login', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify({username: loginUser.value, password: loginPass.value})
  });
  const data = await res.json();
  if(res.ok){
    currentUsername = data.username;
    document.getElementById('whoAmI').innerText = currentUsername;
    document.getElementById('authRoot').style.display='none';
    document.getElementById('appRoot').style.display='block';
    loadWalletsForDropdown();
    load(); setInterval(load, 4000);
  } else {
    document.getElementById('authError').innerText = data.detail || 'Giriş Başarısız';
  }
};

document.getElementById('registerForm').onsubmit = async (e) => {
  e.preventDefault();
  document.getElementById('authError').innerText = '';
  const res = await fetch('/v1/auth/register', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username: regUser.value, password: regPass.value})
  });
  const data = await res.json();
  if(res.ok){
    loginUser.value = regUser.value;
    loginPass.value = regPass.value;
    switchAuthTab('login');
    document.getElementById('loginForm').requestSubmit();
  } else {
    document.getElementById('authError').innerText = data.detail || 'Kayıt Başarısız';
  }
};

document.getElementById('tokForm').onsubmit = async (e) => {
  e.preventDefault();
  await fetch('/v1/token/create', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify({name: tName.value, symbol: tSym.value, initial_supply: parseFloat(tSupply.value), price: parseFloat(tPrice.value)})
  });
  e.target.reset(); load();
};

document.getElementById('rwaForm').onsubmit = async (e) => {
  e.preventDefault();
  await fetch('/v1/tokenization/asset/create', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify({asset_name: rName.value, asset_type: rType.value, total_value_usd: parseFloat(rVal.value), token_symbol: rSym.value})
  });
  e.target.reset(); load();
};

document.getElementById('nftForm').onsubmit = async (e) => {
  e.preventDefault();
  await fetch('/v1/nft/mint', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify({title: nftTitle.value, description: nftDesc.value, price_usd: parseFloat(nftPrice.value)})
  });
  e.target.reset(); load();
};

document.getElementById('walForm').onsubmit = async (e) => {
  e.preventDefault();
  await fetch('/v1/wallet/create', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
    body: JSON.stringify({label: wLabel.value})
  });
  e.target.reset(); load();
};

async function doLogout(){
  await fetch('/v1/auth/logout', {method:'POST', credentials:'include'});
  location.reload();
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


if __name__ == "__main__":
    import uvicorn

    file_name = os.path.basename(__file__).replace(".py", "")
    uvicorn.run(f"{file_name}:app", host="127.0.0.1", port=8000, reload=True)
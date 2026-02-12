import os
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def send_telegram(text):
    token = os.environ["TG_BOT_TOKEN"]
    chat_id = os.environ["TG_CHAT_ID"]
url = f"https://api.telegram.org/bot{token}/sendMessage"
r = requests.post(
    url,
    json={"chat_id": chat_id, "text": text},
    timeout=30
)
r.raise_for_status()


r.raise_for_status()


REVERT_API = "https://api.revert.finance"

def fetch_positions(safe: str) -> dict:
    url = f"{REVERT_API}/v1/positions/uniswapv3/account/{safe}"
    params = {"active": "true", "with-v4": "true"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_xp_operations(safe: str) -> list:
    url = f"{REVERT_API}/v1/xp-operations/{safe}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()
def _as_list(value):
    """xp-operations/positionsの返り値を 'list' に正規化する"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # よくある形: {"data":[...]} or {"positions":[...]}
        for k in ("data", "positions", "items", "result", "operations", "xp_operations", "xpOperations", "logs"):
            v = value.get(k)
            if isinstance(v, list):
                return v
    return []


def calc_fee_usd_24h_from_xp_ops(xp_ops_list, now_dt):
    """
    xp-operations から直近24hの確定手数料(USD相当)を合計する。
    DevToolsのスクショにある 'points' をUSD相当として扱う（推測）。
    """
    since = now_dt - timedelta(hours=24)
    total = 0.0
    count = 0

    for op in xp_ops_list:
        if not isinstance(op, dict):
            continue

        # timestamp: 秒（スクショで 1770641xxx の形）
        ts = op.get("timestamp")
        if ts is None:
            continue

        try:
            ts_dt = datetime.fromtimestamp(int(ts), JST)
        except Exception:
            continue

        if ts_dt < since or ts_dt > now_dt:
            continue

        # 収益っぽい操作だけ拾う（まずは広めに）
        op_type = str(op.get("op_type", "")).lower()
        if not any(key in op_type for key in ("fee", "collect", "compound")):
            continue

        # points をUSD相当で加算（pointsが無い場合はスキップ）
        try:
            points = float(op.get("points", 0))
        except Exception:
            points = 0.0

        if points == 0:
            continue

        total += points
        count += 1

    return total, count


def main():
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    safe = os.environ.get("SAFE_ADDRESS", "SAFE_NOT_SET")
    if safe == "SAFE_NOT_SET":
        send_telegram("SAFE\nSAFE_NOT_SET\n\nSAFE_ADDRESS をRenderのEnvironment Variablesに入れてね")
        return
    positions = fetch_positions(safe)
    xp_ops = fetch_xp_operations(safe)
    # ✅ Step B: 2本取得できたか確認（まずは件数だけ）
    pos_list = positions if isinstance(positions, list) else positions.get("positions", positions.get("data", []))
    xp_list = _as_list(xp_ops)
    pos_count = len(pos_list) if isinstance(pos_list, list) else 0
    xp_count = len(xp_list)
    fee_24h, fee_count = calc_fee_usd_24h_from_xp_ops(xp_list, datetime.now(JST))
    
    send_telegram(
        "CBC Liquidity Mining – Debug\n"
        f"{now}\n"
        "━━━━━━━━━━━━━━\n"
        f"SAFE\n{safe}\n\n"
        "Step B) Fetch OK\n"
        f"positions: {pos_count}\n"
        f"xp-operations: {xp_count}\n"
        f"24h fee (points): {fee_24h}\n"
        f"24h fee count: {fee_count}\n"
    )




    message = (
        "CBC Liquidity Mining – Daily\n"
        f"{now}\n"
        "━━━━━━━━━━━━━━\n\n"
        "SAFE\n"
        f"{safe}\n\n"
        "Render接続テスト成功 🎉\n"
    )

    send_telegram(message)

if __name__ == "__main__":
    main()

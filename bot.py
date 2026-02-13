import os
import requests
import json


def send_telegram(text):
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")

    if not token or not chat_id:
        print("Telegram ENV missing", flush=True)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": chat_id, "text": text},
        timeout=30
    )
    print("Telegram status:", r.status_code, flush=True)
    r.raise_for_status()








from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))





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


def calc_fee_usd_daily_from_xp_ops(xp_ops_list, now_dt):

    end_dt = now_dt.replace(hour=9, minute=0, second=0, microsecond=0)

    if now_dt < end_dt:
        end_dt = end_dt - timedelta(days=1)

    start_dt = end_dt - timedelta(days=1)

    total = 0.0
    count = 0

    for op in xp_ops_list:
        if not isinstance(op, dict):
            continue

        ts = op.get("timestamp")
        if ts is None:
            continue

        try:
            ts_dt = datetime.fromtimestamp(int(ts), JST)
        except:
            continue

        if ts_dt < start_dt or ts_dt >= end_dt:
            continue

        op_type = str(op.get("op_type", "")).lower()
        if not any(k in op_type for k in ("fee", "collect", "compound")):
            continue

        try:
            points = float(op.get("points", 0) or 0)
        except:
            points = 0.0

        if points == 0:
            continue

        total += points
        count += 1

    return total, count, start_dt, end_dt


def main():
    print("=== BOT START (PRINT) ===", flush=True)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    safe = os.environ.get("SAFE_ADDRESS", "SAFE_NOT_SET")

    if safe == "SAFE_NOT_SET":
        send_telegram("SAFE\nSAFE_NOT_SET\n\nSAFE_ADDRESS をRenderのEnvironment Variablesに入れてね")
        return

    positions = fetch_positions(safe)
    xp_ops = fetch_xp_operations(safe)


    pos_list = positions if isinstance(positions, list) else positions.get("positions", positions.get("data", []))
    xp_list = _as_list(xp_ops)
    
    


    pos_count = len(pos_list) if isinstance(pos_list, list) else 0
    xp_count = len(xp_list)
    fee_usd, fee_count, start_dt, end_dt = calc_fee_usd_daily_from_xp_ops(
    xp_list,
    datetime.now(JST)
)



    report = (
    "CBC Liquidity Mining – Daily\n"
    f"Period End: {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
    "────────────────────\n"
    f"SAFE\n{safe}\n\n"
    f"■ 24h確定手数料 ${fee_usd:.2f}\n"
    f"■ Transactions {fee_count}\n"
    f"■ Period {start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
)






if __name__ == "__main__":
        main()

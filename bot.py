import os
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def send_telegram(text):
    token = os.environ["TG_BOT_TOKEN"]
    chat_id = os.environ["TG_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
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
    pos_count = len(pos_list) if isinstance(pos_list, list) else 0
    xp_count = len(xp_ops) if isinstance(xp_ops, list) else 0

    send_telegram(
        "CBC Liquidity Mining – Debug\n"
        f"{now}\n"
        "━━━━━━━━━━━━━━\n"
        f"SAFE\n{safe}\n\n"
        "Step B) Fetch OK\n"
        f"positions: {pos_count}\n"
        f"xp-operations: {xp_count}\n"
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

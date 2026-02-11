import os
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def send_telegram(text):
    token = os.environ["TG_BOT_TOKEN"]
    chat_id = os.environ["TG_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def main():
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    safe = os.environ.get("SAFE_ADDRESS", "SAFE_NOT_SET")

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

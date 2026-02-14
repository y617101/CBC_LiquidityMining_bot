import os
import requests
import json

from datetime import datetime, timedelta, timezone
from decimal import Decimal


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

def fetch_positions(safe: str, active: bool = True):
    url = f"{REVERT_API}/v1/positions/uniswapv3/account/{safe}"
    params = {"active": "true" if active else "false", "with-v4": "true"}
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
    n_all = 0
    n_dict = 0
    n_ts = 0
    n_in_window = 0
    n_type = 0
    n_usd = 0

    end_dt = now_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_dt < end_dt:
        end_dt = end_dt - timedelta(days=1)
    start_dt = end_dt - timedelta(days=1)

    total = 0.0
    count = 0

    for op in xp_ops_list:  # ← ここは「4スペース」インデントで必ず関数内
        print("DBG OP:", op, flush=True)
        n_all += 1
        if isinstance(op, dict):
            n_dict += 1

        if not isinstance(op, dict):
            continue

        ts = op.get("timestamp")
        if ts is not None:
            n_ts += 1
        if ts is None:
            continue

        try:
            ts_i = int(ts)

            # ミリ秒なら秒に直す
            if ts_i > 10_000_000_000:
                ts_i = ts_i // 1000

            ts_dt = datetime.fromtimestamp(ts_i, JST)

        except:
            continue

        print("DBG ts_dt:", ts_dt, flush=True)
        print("DBG window:", start_dt, end_dt, flush=True)

        if ts_dt < start_dt or ts_dt >= end_dt:
            continue

        op_type = str(op.get("op_type", "")).lower()
        n_type += 1
        if not any(k in op_type for k in ("fee", "collect", "compound")):
            pass

        n_in_window += 1

        usd = None

        # まずは points をUSD候補として拾う（原因特定用）
        if "points" in op:
            try:
                usd = float(op.get("points"))
            except:
                usd = None

        # points で取れなかった時だけ、既存のUSDキー探索へ
        if usd is None:
            for key in [
                "usdAmount", "amountUsd", "amountUSD",
                "valueUsd", "valueUSD",
                "feeUsd", "feeUSD",
                "collectedFeesUsd", "collectedFeesUSD"
            ]:
                if key in op:
                    try:
                        usd = float(op.get(key))
                    except:
                        usd = None
                    break

        # ネスト探索（dict/listのどこかに "usd" を含むキーがあれば拾う）
        if usd is None:
            def walk(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, str) and "usd" in k.lower():
                            try:
                                return float(v)
                            except:
                                pass
                        r = walk(v)
                        if r is not None:
                            return r
                elif isinstance(obj, list):
                    for item in obj:
                        r = walk(item)
                        if r is not None:
                            return r
                return None

        if usd is None:
            usd = walk(op)

        if usd is None:
            continue

        n_usd += 1
        total += usd
        count += 1



    print("DBG n_all/n_dict/n_ts/n_in_window/n_type/n_usd:",
        n_all, n_dict, n_ts, n_in_window, n_type, n_usd, flush=True)
    
    return total, count, start_dt, end_dt
    
def calc_uncollected_usd_from_positions(pos_list):
    total = 0.0

    for pos in pos_list:
        try:
            v = pos.get("fees_value")  # ✅ これが未回収USD（ログで確認できた）
            if v is None:
                continue
            total += float(v)
        except:
            continue

    return total



def main():
    print("=== BOT START (PRINT) ===", flush=True)

    safe = os.environ.get("SAFE_ADDRESS", "SAFE_NOT_SET")
    if safe == "SAFE_NOT_SET":
        send_telegram("SAFE\nSAFE_NOT_SET\n\nSAFE_ADDRESS をRenderのEnvironment Variablesに入れてね")
        return

    positions_open = fetch_positions(safe, active=True)
    positions_exited = fetch_positions(safe, active=False)
    xp_ops = fetch_xp_operations(safe)

    pos_list_open = positions_open if isinstance(positions_open, list) else positions_open.get("positions", positions_open.get("data", []))
    pos_list_exited = positions_exited if isinstance(positions_exited, list) else positions_exited.get("positions", positions_exited.get("data", []))

    # pos_list_all を作る（open + exited）
    pos_list_all = []
    if isinstance(pos_list_open, list):
        pos_list_all += pos_list_open
  

    types = set()
    for p in pos_list_all:
        for cf in (p.get("cash_flows") or []):
            t = cf.get("type")
            if t:
                types.add(t)
    print("DBG cash_flow types:", sorted(types), flush=True)


    if isinstance(pos_list_open, list):
        pos_list_all += pos_list_open
    if isinstance(pos_list_exited, list):
        pos_list_all += pos_list_exited

    # --- TEMP DEBUG (cash_flows shape) ---
    try:
        if isinstance(pos_list_all, list) and len(pos_list_all) > 0:
            cf = pos_list_all[0].get("cash_flows")
            print("DBG cash_flows type:", type(cf), flush=True)
            if isinstance(cf, list) and len(cf) > 0:
                print("DBG cash_flow keys:", list(cf[0].keys()), flush=True)
                print("DBG cash_flow sample:", str(cf[0])[:1200], flush=True)
    except Exception as e:
        print("DBG cash_flows error:", e, flush=True)

    uncollected_usd = calc_uncollected_usd_from_positions(pos_list_open)
    xp_list = _as_list(xp_ops)

    pos_open_count = len(pos_list_open) if isinstance(pos_list_open, list) else 0
    pos_exited_count = len(pos_list_exited) if isinstance(pos_list_exited, list) else 0
    pos_all_count = len(pos_list_all)
    xp_count = len(xp_list)

    print("pos_open:", pos_open_count, "pos_exited:", pos_exited_count, "pos_all:", pos_all_count, "xp:", xp_count, flush=True)

    fee_usd, fee_count, start_dt, end_dt = calc_fee_usd_daily_from_xp_ops(
        xp_list,
        datetime.now(JST)
    )

    report = (
        "CBC Liquidity Mining — Daily\n"
        f"Period End: {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
        "────────────────\n"
        f"SAFE\n{safe}\n\n"
        f"・24h確定手数料 ${fee_usd:.2f}\n"
        f"・未回収手数料 ${uncollected_usd:.2f}\n"
        f"・Transactions {fee_count}\n"
        f"・Period {start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
    )

    send_telegram(report)


if __name__ == "__main__":
    main()

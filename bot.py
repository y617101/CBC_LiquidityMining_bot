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


def to_f(x, default=None):
    try:
        return float(x)
    except:
        return default

def fmt_money(x):
    return "N/A" if x is None else f"${x:,.2f}"

def fmt_pct(x):
    return "N/A" if x is None else f"{x:.2f}%"

def get_symbol(tok):
    # token0/token1 が dict の想定（なければ fallback）
    if isinstance(tok, dict):
        return tok.get("symbol") or tok.get("ticker") or tok.get("name") or "TOKEN"
    return "TOKEN"

def calc_net_usd(pos):
    """
    Net（借入差引後・positions API対応版）
    Net = pooled assets USD - repay_usd

    pooled assets USD = current_amount0 * pool_price + current_amount1
    repay_usd は amount_to_repay が無いので cash_flows から推定
    """

    price = to_f(pos.get("pool_price"))
    a0 = to_f(pos.get("current_amount0"))
    a1 = to_f(pos.get("current_amount1"))

    if price is None or a0 is None or a1 is None:
        return None

    pooled_usd = a0 * price + a1

    repay_usd = to_f(pos.get("amount_to_repay"))
    if repay_usd is None:
        repay_usd = extract_repay_usd_from_cash_flows(pos)

    return pooled_usd - repay_usd


def calc_fee_apr_a(fee_24h_usd, net_usd):
    if fee_24h_usd is None or net_usd is None or net_usd <= 0:
        return None
    return (fee_24h_usd / net_usd) * 365 * 100
def extract_repay_usd_from_cash_flows(pos):
    """
    positions API に amount_to_repay が無い場合の代替:
    cash_flows の type == 'lendor-borrow' から USD を拾う（最新を優先）
    """
    cfs = pos.get("cash_flows") or []
    best_ts = None
    best_val = None

    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        if cf.get("type") != "lendor-borrow":
            continue

        v = to_f(cf.get("amount_usd"))
        ts = cf.get("timestamp")

        if v is None:
            continue

        # timestamp が取れるなら最新を採用
        try:
            ts_i = int(ts) if ts is not None else None
        except:
            ts_i = None

        if ts_i is None:
            best_val = v
            continue

        if best_ts is None or ts_i > best_ts:
            best_ts = ts_i
            best_val = v

    # 借入系は符号がマイナスのことがあるので絶対値で扱う
    return abs(best_val) if best_val is not None else 0.0
def _lower(s):
    return str(s or "").strip().lower()

def _to_ts_sec(ts):
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:  # ms -> sec
            ts_i //= 1000
        return ts_i
    except:
        return None

def calc_fee_usd_24h_from_cash_flows(pos_list_all, now_dt):
    """
    Fees Collected（確定手数料）を positions[*].cash_flows から拾って 24h窓で合計
    返り値:
      total_fee_usd, total_count, fee_by_nft(dict), count_by_nft(dict), start_dt, end_dt
    """
    end_dt = now_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_dt < end_dt:
        end_dt -= timedelta(days=1)
    start_dt = end_dt - timedelta(days=1)

    total = 0.0
    total_count = 0
    fee_by_nft = {}
    count_by_nft = {}

    for pos in (pos_list_all or []):
        if not isinstance(pos, dict):
            continue

        nft_id = str(pos.get("nft_id", "UNKNOWN"))
        cfs = pos.get("cash_flows") or []

        if not isinstance(cfs, list):
            continue

        for cf in cfs:
            if not isinstance(cf, dict):
                continue

            t = _lower(cf.get("type"))

            # 確定手数料は claimed-fees のみ
            if t != "claimed-fees":
                continue

            # --- DBG: claimed-fees を1回だけ出す ---

            ts = _to_ts_sec(cf.get("timestamp"))
            if ts is None:
                continue
                
                ts_dt = datetime.fromtimestamp(ts, JST)
                if ts_dt < start_dt or ts_dt >= end_dt:
                    continue
                    

        amt_usd = to_f(cf.get("amount_usd"))

        if amt_usd is None:
            prices = cf.get("prices") or {}
            p0 = to_f((prices.get("token0") or {}).get("usd"))
            p1 = to_f((prices.get("token1") or {}).get("usd"))
        
            q0 = to_f(cf.get("claimed_token0")) or to_f(cf.get("fees0")) or to_f(cf.get("amount0")) or 0.0
            q1 = to_f(cf.get("claimed_token1")) or to_f(cf.get("fees1")) or to_f(cf.get("amount1")) or 0.0
        
            usd0 = abs(q0) * p0 if p0 is not None else 0.0
            usd1 = abs(q1) * p1 if p1 is not None else 0.0
            amt_usd = usd0 + usd1
        
        # ここで1回だけ弾く（重複いらない）
        if amt_usd is None or amt_usd <= 0:
            continue



            # Fees Collected は基本プラス想定。念のため0以下は無視（不要なら外してOK）
            if amt_usd <= 0:
                continue

            total += float(amt_usd)
            total_count += 1

            fee_by_nft[nft_id] = fee_by_nft.get(nft_id, 0.0) + float(amt_usd)
            count_by_nft[nft_id] = count_by_nft.get(nft_id, 0) + 1

    return total, total_count, fee_by_nft, count_by_nft, start_dt, end_dt

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

    uncollected_usd = calc_uncollected_usd_from_positions(pos_list_open)
    xp_list = _as_list(xp_ops)

    pos_open_count = len(pos_list_open) if isinstance(pos_list_open, list) else 0
    pos_exited_count = len(pos_list_exited) if isinstance(pos_list_exited, list) else 0
    xp_count = len(xp_list)

    print("pos_open:", pos_open_count, "pos_exited:", pos_exited_count, "xp:", xp_count, flush=True)


    # --- 24h fee (cash_flowsベース) ---
    pos_list_all = []
    if isinstance(pos_list_open, list):
        pos_list_all += pos_list_open
    if isinstance(pos_list_exited, list):
        pos_list_all += pos_list_exited

    test_now = datetime.now(JST)
    fee_usd, fee_count, fee_by_nft, count_by_nft, start_dt, end_dt = calc_fee_usd_24h_from_cash_flows(pos_list_all, test_now)



    # --- NFT blocks (active only) ---
    nft_lines = []
    net_total = 0.0
    uncollected_total = 0.0

    for pos in (pos_list_open if isinstance(pos_list_open, list) else []):
        nft_id = str(pos.get("nft_id", "UNKNOWN"))
        # --- DEBUG: pos keys を1回だけ出す ---
        if not os.environ.get("DBG_POS_KEYS_PRINTED"):
            print("DBG pos keys:", list(pos.keys()), flush=True)
            print("DBG pos sample:", str(pos)[:1200], flush=True)
            os.environ["DBG_POS_KEYS_PRINTED"] = "1"
# --- /DEBUG ---

        in_range = pos.get("in_range")
        status = "ACTIVE"
        if in_range is False:
            status = "OUT OF RANGE"

        # Net (USD)
        net = calc_net_usd(pos)
        if net is not None:
            net_total += net

        repay_dbg = to_f(pos.get("amount_to_repay"))
        if repay_dbg is None:
            repay_dbg = extract_repay_usd_from_cash_flows(pos)


        # Uncollected (USD)
        fees_value = to_f(pos.get("fees_value"), 0.0)
        uncollected_total += fees_value

        # Uncollected (token amounts)
        u0 = pos.get("uncollected_fees0")
        u1 = pos.get("uncollected_fees1")
        sym0 = get_symbol(pos.get("token0"))
        sym1 = get_symbol(pos.get("token1"))

        # Fee APR（A方式）: 現時点はNFT別に確定手数料を安全に紐づけできない可能性があるため N/A
        fee_apr = None

        nft_lines.append(
            f"\nNFT {nft_id}\n"
            f"Status: {status}\n"
            f"Net: {fmt_money(net)}\n"
            f"Repay(est): {fmt_money(repay_dbg)}\n"
            f"Uncollected: {fees_value:.2f} USD\n"
            f"Uncollected Fees: {to_f(u0, 0.0):.8f} {sym0} / {to_f(u1, 0.0):.6f} {sym1}\n"
            f"Fee APR: {fmt_pct(fee_apr)}\n"
        )

    report = (
        "CBC Liquidity Mining — Daily\n"
        f"Period End: {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
        "────────────────\n"
        f"SAFE\n{safe}\n\n"
        f"・24h確定手数料 {fmt_money(fee_usd)}\n"
        f"・Net合算 {fmt_money(net_total)}\n"
        f"・未回収手数料 {fmt_money(uncollected_total)}\n"
        f"・Transactions {fee_count}\n"
        f"・Period {start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
        + "".join(nft_lines)
    )

    send_telegram(report)


if __name__ == "__main__":
    main()

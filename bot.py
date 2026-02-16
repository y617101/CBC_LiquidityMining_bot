import os
import requests

# ================================
# Token Symbol Map (Base)
# ================================
ADDRESS_SYMBOL_MAP = {
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",

}


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
    Net = underlying_value - debt(推定)
    """
    pooled_usd = to_f(pos.get("underlying_value"))
    if pooled_usd is None:
        return None

    debt_usd = extract_repay_usd_from_cash_flows(pos)
    if debt_usd is None:
        debt_usd = 0.0

    net = pooled_usd - debt_usd

    if not os.environ.get("DBG_NET_FINAL"):
        os.environ["DBG_NET_FINAL"] = "1"

    return net






def calc_fee_apr_a(fee_24h_usd, net_usd):
    if fee_24h_usd is None or net_usd is None or net_usd <= 0:
        return None
    return (fee_24h_usd / net_usd) * 365 * 100

def extract_repay_usd_from_cash_flows(pos):
    cfs = pos.get("cash_flows") or []
    if not isinstance(cfs, list):
        return 0.0

    # 1) total_debt を最優先（最新timestampのもの）
    latest = None
    latest_ts = -1
    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        t = _lower(cf.get("type"))
        if t not in ("lendor-borrow", "lendor-repay"):
            continue
        td = to_f(cf.get("total_debt"))
        ts = to_f(cf.get("timestamp")) or 0
        if td is not None and ts >= latest_ts:
            latest_ts = ts
            latest = td

    if latest is not None:
        return max(float(latest), 0.0)

    # 2) total_debt が無い場合のみ、borrows - repays をUSDで集計（USDフィールド優先）
    borrow_usd = 0.0
    repay_usd = 0.0

    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        t = _lower(cf.get("type"))
        if t not in ("lendor-borrow", "lendor-repay"):
            continue

        v = to_f(cf.get("amount_usd"))
        if v is None: v = to_f(cf.get("usd"))
        if v is None: v = to_f(cf.get("value_usd"))
        if v is None: v = to_f(cf.get("valueUsd"))
        if v is None: v = to_f(cf.get("amountUsd"))

        if v is None:
            continue  # ← ここで “amount×price” に落ちない（壊れやすいので）

        v = abs(float(v))
        if t == "lendor-borrow":
            borrow_usd += v
        else:
            repay_usd += v

    debt = borrow_usd - repay_usd
    return debt if debt > 0 else 0.0







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
    end_dt = now_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_dt < end_dt:
        end_dt -= timedelta(days=1)
    start_dt = end_dt - timedelta(days=1)

    total = 0.0
    total_count = 0
    fee_by_nft = {}
    count_by_nft = {}

    # DBG: 24h窓で拾えたtypeを確認する
    dbg_types = set()

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
            if t:
                dbg_types.add(t)

            # ✅ いまはまず「確定手数料type候補」を見つけたいので、
            #    ここは一旦ゆるくして、fee/collect/claim を含むものだけ拾ってDBGする
            if not any(k in t for k in ("fee", "collect", "claim")):
                continue

            ts = _to_ts_sec(cf.get("timestamp"))
            if ts is None:
                continue

            ts_dt = datetime.fromtimestamp(ts, JST)
            if ts_dt < start_dt or ts_dt >= end_dt:
                continue

            # まずUSD直があれば優先
            amt_usd = to_f(cf.get("amount_usd"))

            # 無ければ prices + amount0/1系で推定
            if amt_usd is None:
                prices = cf.get("prices") or {}
                p0 = to_f((prices.get("token0") or {}).get("usd")) or 0.0
                p1 = to_f((prices.get("token1") or {}).get("usd")) or 0.0

                q0 = to_f(cf.get("collected_fees_token0")) or to_f(cf.get("claimed_token0")) or to_f(cf.get("fees0")) or to_f(cf.get("amount0")) or 0.0
                q1 = to_f(cf.get("collected_fees_token1")) or to_f(cf.get("claimed_token1")) or to_f(cf.get("fees1")) or to_f(cf.get("amount1")) or 0.0

                amt_usd = abs(q0) * p0 + abs(q1) * p1

            # ガード
            try:
                amt_usd = float(amt_usd)
            except Exception:
                continue
            if not (amt_usd > 0):
                continue

            total += amt_usd
            total_count += 1
            fee_by_nft[nft_id] = fee_by_nft.get(nft_id, 0.0) + amt_usd
            count_by_nft[nft_id] = count_by_nft.get(nft_id, 0) + 1


    return total, total_count, fee_by_nft, count_by_nft, start_dt, end_dt

def resolve_symbol(pos, which):
    # which: "token0" or "token1"
    v = pos.get(which)

    # 1) まず pos[token0/token1] が dict の場合
    if isinstance(v, dict):
        s = v.get("symbol") or v.get("ticker") or v.get("name")
        if s:
            return s
        addr = v.get("address") or v.get("token_address") or v.get("tokenAddress")
        if addr:
            return ADDRESS_SYMBOL_MAP.get(str(addr).strip().lower(), "TOKEN")

    # 2) pos[token0/token1] が address文字列の場合
    if isinstance(v, str):
        m = ADDRESS_SYMBOL_MAP.get(v.strip().lower())
        if m:
            return m

    # 3) fallback: pos["tokens"] から拾う（list想定）
    toks = pos.get("tokens")
    if isinstance(toks, list) and len(toks) >= 2:
        idx = 0 if which == "token0" else 1
        t = toks[idx]
        if isinstance(t, dict):
            s = t.get("symbol") or t.get("ticker") or t.get("name")
            if s:
                return s
            addr = t.get("address") or t.get("token_address") or t.get("tokenAddress")
            if addr:
                m = ADDRESS_SYMBOL_MAP.get(str(addr).strip().lower())
                if m:
                    return m

    return "TOKEN"


def main():

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


        in_range = pos.get("in_range")
        status = "ACTIVE"
        if in_range is False:
            status = "OUT OF RANGE"

        # Net (USD)
        net = calc_net_usd(pos)
        if not os.environ.get("DBG_NET_ONCE"):
            os.environ["DBG_NET_ONCE"] = "1"

        if net is not None:
            net_total += float(net)

        
        # Fee APR（A方式）
        fee_usd_nft = fee_by_nft.get(str(nft_id), 0.0)
        fee_apr = calc_fee_apr_a(fee_usd_nft, net)
        
        fee_apr_ui = to_f(
            ((pos.get("performance") or {}).get("hodl") or {}).get("fee_apr")
        )




        # Uncollected (USD)
        fees_value = to_f(pos.get("fees_value"), 0.0)
        uncollected_total += fees_value

        # Uncollected (token amounts)
        u0 = pos.get("uncollected_fees0")
        u1 = pos.get("uncollected_fees1")
        
        sym0 = resolve_symbol(pos, "token0")
        sym1 = resolve_symbol(pos, "token1")

        
        # ここに入れる（sym0/sym1 の直前）



        # Fee APR（A方式）: 現時点はNFT別に確定手数料を安全に紐づけできない可能性があるため N/A

        fee_apr_ui = to_f(
            ((pos.get("performance") or {}).get("hodl") or {}).get("fee_apr")
        )

        nft_lines.append(
            f"\nNFT {nft_id}\n"
            f"Status: {status}\n"
            f"Net: {fmt_money(net)}\n"
            f"Uncollected: {fees_value:.2f} USD\n"
            f"Uncollected Fees:\n"
            f"{to_f(u0, 0.0):.8f} {sym0}\n"
            f"{to_f(u1, 0.0):.6f} {sym1}\n"
            f"Fee APR: {fmt_pct(fee_apr_ui)}\n"
        )


    safe_fee_apr = calc_fee_apr_a(fee_usd, net_total)
   

    report = (
        "CBC Liquidity Mining — Daily\n"
        f"Period End: {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
        "────────────────\n"
        f"SAFE\n{safe}\n\n"
        f"・24h確定手数料 {fmt_money(fee_usd)}\n"
        f"・Fee APR(SAFE) {fmt_pct(safe_fee_apr)}\n"
        f"・Net合算 {fmt_money(net_total)}\n"
        f"・未回収手数料 {fmt_money(uncollected_total)}\n"
        f"・Transactions {fee_count}\n"
        f"・Period {start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')} JST\n"
        + "".join(nft_lines)
    )

    send_telegram(report)


if __name__ == "__main__":
    main()

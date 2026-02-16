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
    Net = underlying_value - debt
    REVERTの underlying_value を基準にする（最も正確）
    """

    pooled_usd = to_f(pos.get("underlying_value"))
    if pooled_usd is None:
        return None

    repay_usd = extract_repay_usd_from_cash_flows(pos)
    if repay_usd is None:
        repay_usd = 0.0

    net = pooled_usd - repay_usd

    if not os.environ.get("DBG_NET_FINAL"):
        print("DBG NET pooled:", pooled_usd,
              "debt:", repay_usd,
              "net:", net,
              flush=True)
        os.environ["DBG_NET_FINAL"] = "1"

    return net





def calc_fee_apr_a(fee_24h_usd, net_usd):
    if fee_24h_usd is None or net_usd is None or net_usd <= 0:
        return None
    return (fee_24h_usd / net_usd) * 365 * 100

def extract_repay_usd_from_cash_flows(pos):
    """
    借入残高（USD）を cash_flows から推定する
    優先：total_debt（あればそれが残高）
    予備：sum(lendor-borrow) - sum(lendor-repay)（USD換算できる場合）
    """
    cfs = pos.get("cash_flows") or []
    if not isinstance(cfs, list):
        return 0.0

    # --- ① total_debt を最優先で拾う（最も確実） ---
    best_ts = None
    best_debt = None
    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        t = _lower(cf.get("type"))
        if t not in ("lendor-borrow", "lendor-repay"):
            continue

        d = to_f(cf.get("total_debt"))
        if d is None:
            continue

        ts = cf.get("timestamp") or cf.get("ts")
        ts = _to_ts_sec(ts)  # あなたの既存ヘルパーがある前提
        if ts is None:
            ts = 0

        if best_ts is None or ts >= best_ts:
            best_ts = ts
            best_debt = abs(float(d))

    if best_debt is not None:
        return best_debt

    # --- ② 予備：借入−返済（USD換算できる時だけ） ---
    # token0/token1 アドレスを pos から取る（ログ上、文字列で入ってる）
    t0 = _lower(pos.get("token0"))
    t1 = _lower(pos.get("token1"))

    borrow_usd = 0.0
    repay_usd = 0.0

    for cf in cfs:
        if not isinstance(cf, dict):
            continue

        t = _lower(cf.get("type"))
        if t not in ("lendor-borrow", "lendor-repay"):
            continue

        amt = to_f(cf.get("amount"))
        if amt is None:
            continue
        amt = float(amt)

        token = cf.get("token") or {}
        addr = _lower((token.get("address") if isinstance(token, dict) else None))
        prices = cf.get("prices") or {}

        price_usd = None
        if addr and t0 and addr == t0:
            price_usd = to_f(((prices.get("token0") or {}) if isinstance(prices, dict) else {}).get("usd"))
        elif addr and t1 and addr == t1:
            price_usd = to_f(((prices.get("token1") or {}) if isinstance(prices, dict) else {}).get("usd"))

        # price_usd が取れないなら諦めてスキップ（total_debt優先のため）
        if price_usd is None:
            continue

        v = abs(amt * float(price_usd))

        if t == "lendor-borrow":
            borrow_usd += v
        elif t == "lendor-repay":
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

    print("DBG all cash_flow types (seen):", sorted(dbg_types), flush=True)
    print("DBG fee-like count(24h):", total_count, flush=True)

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
    print("=== BOT START (PRINT) ===", flush=True)

    safe = os.environ.get("SAFE_ADDRESS", "SAFE_NOT_SET")
    if safe == "SAFE_NOT_SET":
        send_telegram("SAFE\nSAFE_NOT_SET\n\nSAFE_ADDRESS をRenderのEnvironment Variablesに入れてね")
        return

    positions_open = fetch_positions(safe, active=True)
    positions_exited = fetch_positions(safe, active=False)
    xp_ops = fetch_xp_operations(safe)

    # --- DBG: xp-operationsの中身を1件だけ見る ---
    try:
        xp_list = _as_list(xp_ops)
        print("DBG xp_list len:", len(xp_list), flush=True)
        if xp_list:
            print("DBG xp sample keys:", list(xp_list[0].keys()), flush=True)
            print("DBG xp sample:", str(xp_list[0])[:1500], flush=True)
    except Exception as e:
        print("DBG xp parse error:", e, flush=True)


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
    print("DBG fee_by_nft keys:", list(fee_by_nft.keys()), flush=True)



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
        if not os.environ.get("DBG_NET_ONCE"):
            print("DBG pooled_usd/repay_usd test pos keys:", list(pos.keys()), flush=True)
            os.environ["DBG_NET_ONCE"] = "1"

        if net is not None:
            net_total += net
        
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
        if not os.environ.get("DBG_TOKEN_SHAPE_PRINTED"):
            print("DBG token0 raw:", pos.get("token0"), flush=True)
            print("DBG token1 raw:", pos.get("token1"), flush=True)
            print("DBG tokens raw:", pos.get("tokens"), flush=True)
            os.environ["DBG_TOKEN_SHAPE_PRINTED"] = "1"



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
    print("DBG SAFE APR:", fee_usd, net_total, safe_fee_apr, flush=True)

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

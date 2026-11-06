"""台股抄底指數（Python 版，對應 xq/bottom_index.xs）

資料來源：證交所（大盤 OHLC、成交金額、漲跌家數、融資融券、三大法人）
          期交所（選擇權 P/C 未平倉比、台指期近月收盤、外資台指期未平倉）
歷史資料存在 data/history.csv，每次只補缺的交易日。
分數 >= THRESHOLD 時推播 Telegram（--force 一律推播，供測試）。
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ---------------- 參數（對應 XQ input） ----------------
LENGTH = int(os.getenv("LENGTH", "60"))          # 百分位回看天數
THRESHOLD = float(os.getenv("THRESHOLD", "70"))  # 推播門檻
BACKFILL_MONTHS = int(os.getenv("BACKFILL_MONTHS", "7"))

# (啟用, 權重)；融資維持率無公開免費資料，預設停用
SIGNALS = {
    "VolLow":    ("量縮至低檔",         1, 10),
    "Shadow":    ("長下影放量",         1, 10),
    "VolStruct": ("跌量縮漲量增",       1, 10),
    "Div":       ("價RSI底背離",        1, 15),
    "LimitDn":   ("跌停家數高峰回落",   1, 10),
    "AdvRatio":  ("上漲家數比改善",     1, 10),
    "Margin":    ("融資餘額洗出",       1, 10),
    "Maint":     ("融資維持率落底回升", 0, 10),
    "SSRatio":   ("券資比偏高",         1, 8),
    "Foreign":   ("外資賣超收斂",       1, 12),
    "Local":     ("投信自營回補",       1, 8),
    "PCR":       ("選擇權P/C未平倉比",  1, 10),
    "Basis":     ("期現基差轉正",       1, 8),
    "FutF":      ("外資期貨空單收斂",   1, 10),
}

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.csv")
UA = {"User-Agent": "Mozilla/5.0 (bottom-index bot)"}
TW = timezone(timedelta(hours=8))


# ---------------- 工具 ----------------
def http(url, data=None, tries=3):
    body = urllib.parse.urlencode(data).encode() if data else None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            return urllib.request.urlopen(req, timeout=40).read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))


def twse(path, **params):
    params["response"] = "json"
    raw = http(f"https://www.twse.com.tw/rwd/zh/{path}?" + urllib.parse.urlencode(params))
    time.sleep(1.2)  # 證交所限流
    return json.loads(raw)


def num(s):
    s = str(s).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def roc(s):
    y, m, d = s.split("/")
    return date(int(y) + 1911, int(m), int(d))


def months_back(n):
    today = datetime.now(TW).date()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def month_end(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return min(nxt - timedelta(days=1), datetime.now(TW).date())


# ---------------- 證交所 ----------------
def fetch_month_index(m):
    """大盤 OHLC + 成交金額（月資料）。"""
    ds = m.strftime("%Y%m%d")
    o = twse("TAIEX/MI_5MINS_HIST", date=ds)
    v = twse("afterTrading/FMTQIK", date=ds)
    rows = {}
    for r in o.get("data", []) or []:
        rows[roc(r[0])] = dict(open=num(r[1]), high=num(r[2]), low=num(r[3]), close=num(r[4]))
    for r in v.get("data", []) or []:
        d = roc(r[0])
        if d in rows:
            rows[d]["volume"] = num(r[2]) / 1e8  # 成交金額（億元）
    return rows


def parse_count(s):
    m = re.match(r"([\d,]+)\(([\d,]+)\)", str(s))
    return (num(m.group(1)), num(m.group(2))) if m else (np.nan, np.nan)


def fetch_day(d):
    ds = d.strftime("%Y%m%d")
    out = {}
    mi = twse("afterTrading/MI_INDEX", date=ds, type="MS")
    for t in mi.get("tables", []) or []:
        if t.get("title") == "漲跌證券數合計":
            for r in t["data"]:
                if r[0].startswith("上漲"):
                    out["adv"], _ = parse_count(r[2])
                elif r[0].startswith("下跌"):
                    out["dec"], out["limit_dn"] = parse_count(r[2])
    mg = twse("marginTrading/MI_MARGN", date=ds, selectType="MS")
    if mg.get("stat") == "OK" and mg.get("tables"):
        data = mg["tables"][0]["data"]
        out["margin"] = num(data[0][5])       # 融資餘額（張）
        out["short"] = num(data[1][5])        # 融券餘額（張）
    bf = twse("fund/BFI82U", type="day", dayDate=ds)
    if bf.get("stat") == "OK":
        rows = {r[0]: num(r[3]) / 1e8 for r in bf["data"]}  # 億元
        out["foreign"] = rows.get("外資及陸資(不含外資自營商)", np.nan)
        out["trust"] = rows.get("投信", np.nan)
        out["dealer"] = rows.get("自營商(自行買賣)", 0) + rows.get("自營商(避險)", 0)
    return out


# ---------------- 期交所 ----------------
def taifex_csv(path, data):
    raw = http(f"https://www.taifex.com.tw/cht/3/{path}", data)
    time.sleep(1)
    txt = raw.decode("big5", errors="ignore")
    if txt.lstrip().startswith("<"):
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(txt), index_col=False)


def fetch_taifex(start, end):
    """回傳 {date: dict(pcr, fut_close, fut_net)}，按月分段查詢。"""
    out = {}
    m = date(start.year, start.month, 1)
    while m <= end:
        s, e = max(m, start), min(month_end(m), end)
        q = dict(queryStartDate=s.strftime("%Y/%m/%d"), queryEndDate=e.strftime("%Y/%m/%d"))
        # 外資台指期未平倉淨口數
        try:
            df = taifex_csv("futContractsDateDown", {**q, "commodityId": "TXF"})
            if not df.empty:
                df = df[df["身份別"].astype(str).str.contains("外資")]
                for _, r in df.iterrows():
                    d = datetime.strptime(str(r["日期"]), "%Y/%m/%d").date()
                    out.setdefault(d, {})["fut_net"] = num(r["多空未平倉口數淨額"])
        except Exception as ex:  # noqa: BLE001
            print("futContracts fail", ex, file=sys.stderr)
        # 台指期近月（一般盤）收盤
        try:
            df = taifex_csv("futDataDown", {**q, "down_type": "1", "commodity_id": "TX"})
            if not df.empty:
                df.columns = [c.strip() for c in df.columns]
                df["到期月份(週別)"] = df["到期月份(週別)"].astype(str).str.strip()
                df = df[(df["交易時段"].astype(str).str.strip() == "一般")
                        & df["到期月份(週別)"].str.fullmatch(r"\d{6}")]
                for dstr, g in df.groupby("交易日期"):
                    g = g.sort_values("到期月份(週別)")
                    d = datetime.strptime(str(dstr).strip(), "%Y/%m/%d").date()
                    out.setdefault(d, {})["fut_close"] = num(g.iloc[0]["收盤價"])
        except Exception as ex:  # noqa: BLE001
            print("futData fail", ex, file=sys.stderr)
        # 選擇權 P/C 未平倉量比率
        try:
            html = http("https://www.taifex.com.tw/cht/3/pcRatio?" + urllib.parse.urlencode(q)).decode("utf-8", "ignore")
            time.sleep(1)
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
                cells = [re.sub(r"<[^>]+>|\s", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                if len(cells) >= 7 and re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", cells[0]):
                    d = datetime.strptime(cells[0], "%Y/%m/%d").date()
                    out.setdefault(d, {})["pcr"] = num(cells[6])
        except Exception as ex:  # noqa: BLE001
            print("pcRatio fail", ex, file=sys.stderr)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


# ---------------- 更新歷史 ----------------
def update_history():
    hist = pd.read_csv(HIST, parse_dates=["date"]) if os.path.exists(HIST) else pd.DataFrame()
    have = set(hist["date"].dt.date) if not hist.empty else set()
    months = months_back(BACKFILL_MONTHS if not have else 2)
    idx = {}
    for m in months:
        idx.update(fetch_month_index(m))
    new_days = sorted(d for d in idx if d not in have)
    if not new_days:
        return hist
    print(f"補 {len(new_days)} 個交易日：{new_days[0]} ~ {new_days[-1]}")
    tx = fetch_taifex(new_days[0], new_days[-1])
    rows = []
    for d in new_days:
        r = {"date": pd.Timestamp(d), **idx[d]}
        try:
            r.update(fetch_day(d))
        except Exception as ex:  # noqa: BLE001
            print(f"{d} 證交所資料失敗：{ex}", file=sys.stderr)
        r.update(tx.get(d, {}))
        rows.append(r)
    hist = pd.concat([hist, pd.DataFrame(rows)], ignore_index=True)
    hist = hist.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    hist.to_csv(HIST, index=False, float_format="%.4f")
    return hist


# ---------------- 指數計算（逐項對應 XQ） ----------------
def rsi_wilder(close, n=14):
    diff = close.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def pct_rank(s, lb, invert=False):
    hi, lo = s.rolling(lb, min_periods=lb).max(), s.rolling(lb, min_periods=lb).min()
    rng = hi - lo
    p = ((s - lo) / rng * 100).where(rng != 0, 50)
    p = p.where(s.notna(), 50)  # 抓不到資料以 50 中性計
    return 100 - p if invert else p


def average_if(cond, vals, n):
    v = vals.where(cond)
    return v.rolling(n, min_periods=1).mean()


def compute(h):
    h = h.copy()
    lb = max(LENGTH, 20)
    c, o, hi, lo, v = h["close"], h["open"], h["high"], h["low"], h["volume"]
    s = pd.DataFrame(index=h.index)

    s["VolLow"] = pct_rank(v, lb, invert=True)

    rng_bar = hi - lo
    low_shadow = ((np.minimum(o, c) - lo) / rng_bar).where(rng_bar > 0, 0)
    s["Shadow"] = np.where((low_shadow >= 0.5) & (v > v.rolling(20).mean() * 1.5) & (c >= o), 100, 0)

    up_v = average_if(c > c.shift(), v, 10)
    dn_v = average_if(c < c.shift(), v, 10)
    vol_ratio = (up_v / dn_v).where(dn_v > 0, 1).fillna(1)
    s["VolStruct"] = pct_rank(vol_ratio, lb)

    rsi = rsi_wilder(c, 14)
    price_low = lo <= lo.rolling(20).min()
    rsi_not_low = rsi > rsi.rolling(20).min() * 1.02
    s["Div"] = np.where(price_low & rsi_not_low, 100, 0)

    ld = h["limit_dn"]
    p = pct_rank(ld, lb)
    peak = (ld.rolling(5).max() >= ld.rolling(lb).max() * 0.7) & (ld < ld.shift())
    s["LimitDn"] = np.where(peak, np.maximum(p, 70), p * 0.5)

    adv_r = (h["adv"] / (h["adv"] + h["dec"]) * 100).fillna(50)
    a = pct_rank(adv_r, lb)
    s["AdvRatio"] = np.where(adv_r > adv_r.shift(), np.minimum(a + 10, 100), a)

    s["Margin"] = pct_rank(h["margin"], lb, invert=True)
    s["Maint"] = 50.0  # 無公開資料
    s["SSRatio"] = pct_rank(h["short"] / h["margin"] * 100, lb)
    s["Foreign"] = pct_rank(h["foreign"].rolling(5).sum(), lb)
    s["Local"] = pct_rank((h["trust"] + h["dealer"]).rolling(5).sum(), lb)
    s["PCR"] = pct_rank(h["pcr"], lb)

    basis = h["fut_close"] - c
    b = pct_rank(basis, lb)
    s["Basis"] = np.where((basis > 0) & (basis.shift() <= 0), np.minimum(b + 20, 100), b)
    s["FutF"] = pct_rank(h["fut_net"], lb)

    w_sum = sum(w for _, en, w in SIGNALS.values() if en)
    total = sum(s[k] * w for k, (_, en, w) in SIGNALS.items() if en) / w_sum
    s["total"] = total
    s["date"] = h["date"]
    return s


# ---------------- Telegram ----------------
def send(text):
    if not TOKEN or not CHAT_ID:
        print(text)
        return
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=json.dumps({"chat_id": CHAT_ID, "text": text[:4000]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def report(s, h):
    last, prev = s.iloc[-1], s.iloc[-2]
    hl = h.iloc[-1]
    streak = 0
    for t in reversed(s["total"].tolist()):
        if t >= THRESHOLD:
            streak += 1
        else:
            break
    head = "🟢 台股抄底指數達標" if last["total"] >= THRESHOLD else "ℹ️ 台股抄底指數"
    lines = [
        f"{head} {last['date']:%Y-%m-%d}",
        f"分數 {last['total']:.1f}（門檻 {THRESHOLD:.0f}，前一日 {prev['total']:.1f}）",
    ]
    if streak:
        lines.append(f"連續 {streak} 天達標")
    lines.append(f"加權指數 {hl['close']:,.2f}，成交 {hl['volume']:,.0f} 億")
    lines.append("")
    top = sorted(((k, last[k]) for k, (_, en, _) in SIGNALS.items() if en), key=lambda x: -x[1])
    for k, v in top:
        lines.append(f"{SIGNALS[k][0]}：{v:.0f}")
    lines.append("\n僅供研究參考，非投資建議。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="不論分數一律推播")
    args = ap.parse_args()

    h = update_history()
    if len(h) < LENGTH + 5:
        print(f"歷史資料只有 {len(h)} 天，不足 {LENGTH + 5} 天")
        return
    s = compute(h)
    msg = report(s, h)
    print(msg)
    today = datetime.now(TW).date()
    is_today = s.iloc[-1]["date"].date() == today
    if args.force or (is_today and s.iloc[-1]["total"] >= THRESHOLD):
        send(msg)
    s.to_csv(os.path.join(os.path.dirname(HIST), "scores.csv"), index=False, float_format="%.1f")


if __name__ == "__main__":
    main()

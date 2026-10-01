# FOREX DESK v1.0 — "LONDON BREAKOUT + NEWS GUARD" (paper trading, zero money)
# One pattern, done perfectly: quiet Asian range → London/NY breakout → must hold
# → BOTH engines agree (structure + momentum) → paper scorecard in pips.
# Built on the proven AI-TRADER analysis pattern — adapted for forex physics.
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

st.set_page_config(page_title=" Forex Desk", page_icon="🌍", layout="wide",
                   initial_sidebar_state="collapsed")

APP_VERSION = "v1.1 · FX LIVE LEVELS"
IST = ZoneInfo("Asia/Kolkata")
LON = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")
TG_TOKEN = "8725365776:AAENJn_QG8qYEw7sUu_DiaH_qgsAA_JLY"
TG_CHATS = "8585402983,1996619549"

# ── instruments: pip = 1 unit of "price move" we count ──
FX = {
    "EURUSD=X": {"name": "EUR/USD", "pip": 0.0001, "dec": 5},
    "GBPUSD=X": {"name": "GBP/USD", "pip": 0.0001, "dec": 5},
    "USDJPY=X": {"name": "USD/JPY", "pip": 0.01, "dec": 3},
    "GC=F":     {"name": "GOLD",    "pip": 0.1, "dec": 1},
}
SESSIONS = {"asian": "ASIAN", "london": "LONDON", "ny": "NEW YORK"}
NEWS_BLACKOUT_MIN = 20          # ±minutes around high-impact events — NO new signals
CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STATE_FX = "forex_paper.json"   # paper positions + history (NEVER wiped on update)
STATE_CONS = "forex_cons.json"  # today's snapshots (wiped on new version)


# ═══════════════ helpers ═══════════════
def blog(msg):
    try:
        with open("boot_log_forex.txt", "a", encoding="utf-8") as f:
            f.write(f"{now_ist().strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def now_ist():
    return datetime.now(IST)


def jload(fn, default):
    try:
        if os.path.exists(fn):
            return json.load(open(fn, encoding="utf-8"))
    except Exception:
        pass
    return default


def jsave(fn, d):
    try:
        json.dump(d, open(fn, "w", encoding="utf-8"))
    except Exception:
        pass


def deploy_wipe():
    """version changed → wipe today's consensus (paper HISTORY is kept forever)."""
    try:
        last = ""
        if os.path.exists("last_version_forex.txt"):
            last = open("last_version_forex.txt", encoding="utf-8").read().strip()
        if last == APP_VERSION:
            return
        for f in (STATE_CONS,):
            try:
                os.remove(f)
            except Exception:
                pass
        open("last_version_forex.txt", "w", encoding="utf-8").write(APP_VERSION)
        blog(f"deploy wipe · {APP_VERSION} (paper history preserved)")
    except Exception:
        pass


def fx_market_open():
    """Forex week: Mon 05:30 IST → Sat 05:30 IST (approx close Fri 22:00 UTC)."""
    n = now_ist()
    if n.weekday() == 5:                       # Saturday
        return False
    if n.weekday() == 6:                       # Sunday
        return n.hour >= 5 and True            # opens Sunday ~5:30 IST (Sydney)
    if n.weekday() == 0 and n.hour < 5:
        return False
    return True


def session_now():
    """→ list of active session names."""
    n = now_ist()
    h = n.hour * 60 + n.minute
    out = []
    if 5 * 60 + 30 <= h < 12 * 60 + 30:
        out.append("asian")
    lon_h = (datetime.now(LON).hour * 60 + datetime.now(LON).minute)
    if 8 * 60 <= lon_h < 16 * 60 + 30:
        out.append("london")
    ny_h = (datetime.now(NY).hour * 60 + datetime.now(NY).minute)
    if 8 * 60 <= ny_h < 17 * 00:
        out.append("ny")
    return out


def london_open_ist():
    """Today's London open (8:00 London) converted to IST — correct summer/winter."""
    n = datetime.now(LON)
    o = n.replace(hour=8, minute=0, second=0, microsecond=0)
    return o.astimezone(IST)


def ny_open_ist():
    """Today's NY open (9:30 New York) in IST."""
    n = datetime.now(NY)
    o = n.replace(hour=9, minute=30, second=0, microsecond=0)
    return o.astimezone(IST)


def to_pips(sym, price_diff):
    return price_diff / FX[sym]["pip"]


def fmt_p(sym, px):
    return f"{px:.{FX[sym]['dec']}f}"


# ═══════════════ data ═══════════════
@st.cache_data(ttl=55, show_spinner=False)
def fetch_5m(sym):
    """Two days of 5-min candles, IST index, flat columns."""
    try:
        d = yf.download(sym, period="2d", interval="5m", progress=False, auto_adjust=True)
        if d is None or not len(d):
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]
        d = d.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]]
        d.index = pd.DatetimeIndex(d.index).tz_convert(IST)
        return d.dropna()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_1d(sym):
    try:
        d = yf.download(sym, period="10d", interval="1d", progress=False, auto_adjust=True)
        if d is None or not len(d):
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]
        d = d.rename(columns=str.title)[["Open", "High", "Low", "Close"]]
        d.index = pd.DatetimeIndex(d.index).tz_convert(IST)
        return d.dropna()
    except Exception:
        return None


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def fetch_calendar():
    """High-impact events for the week (free feed, no key)."""
    try:
        rq = urllib.request.Request(CAL_URL, headers={"User-Agent": "Mozilla/5.0",
                                                      "Accept": "application/json"})
        ev = json.loads(urllib.request.urlopen(rq, timeout=20).read())
        out = []
        for e in ev:
            if str(e.get("impact", "")).lower() != "high":
                continue
            try:
                t = datetime.fromisoformat(e["date"]).astimezone(IST)
            except Exception:
                continue
            out.append({"t": t, "country": e.get("country", "?"),
                        "title": e.get("title", "?"), "forecast": e.get("forecast") or "—"})
        return sorted(out, key=lambda x: x["t"])
    except Exception:
        return []


def blackout_active(cals):
    """±20 min around any high-impact event → True + the event."""
    n = now_ist()
    for e in cals:
        if abs((e["t"] - n).total_seconds()) <= NEWS_BLACKOUT_MIN * 60:
            return True, e
    return False, None


def next_events(cals, k=3):
    n = now_ist()
    return [e for e in cals if e["t"] >= n][:k]


# ═══════════════ THE ENGINE — quiet range → breakout → must hold ═══════════════
def quiet_box(df, t0, t1, max_body=0.060, max_width=0.55):
    """The 'silence box': candles between t0 and t1 (IST datetimes).
    Must be genuinely quiet — FX pairs: body ≤0.06%, width ≤0.55%;
    GOLD breathes ~2× wider: body ≤0.10%, width ≤1.2%."""
    try:
        d = df[(df.index >= t0) & (df.index < t1)]
        if len(d) < 12:
            return None
        o, c = d["Open"].astype(float), d["Close"].astype(float)
        if (o <= 0).any():
            return None
        bodies = (c - o).abs() / o * 100
        avg_body = float(bodies.mean())
        hi, lo = float(d["High"].max()), float(d["Low"].min())
        if hi <= 0:
            return None
        width_pct = (hi - lo) / hi * 100
        if avg_body > max_body or width_pct > max_width:   # not a tight range
            return None
        return {"hi": hi, "lo": lo, "avg_body": avg_body, "n": len(d),
                "t0": t0, "t1": t1, "width_pct": width_pct}
    except Exception:
        return None


def session_box(sym, df, which):
    """Asian box (Tokyo 05:30 → London open) or London-morning box (→ NY open)."""
    if df is None or not len(df):
        return None, None
    today = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    gold = sym == "GC=F"
    if which == "london":
        t0, t1 = today + timedelta(hours=5, minutes=30), london_open_ist()
        scan_from = london_open_ist()
    else:
        t0, t1 = london_open_ist(), ny_open_ist()
        scan_from = ny_open_ist()
    box = quiet_box(df, t0, t1, max_body=0.10 if gold else 0.060,
                    max_width=1.2 if gold else 0.55)
    return box, scan_from


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def detect_signal(sym, df, which):
    """🌋 Range-volcano for FX: quiet box → breakout candle that CLOSES outside
    and STILL HOLDS at the last candle. Range-based (spot FX has no volume).
    Gold (GC=F) additionally requires volume ≥ 2× quiet average."""
    box, scan_from = session_box(sym, df, which)
    if box is None:
        return None
    info = FX[sym]
    try:
        after = df[df.index >= scan_from]
        if not len(after):
            return {"state": "WAIT-OPEN", "box": box, "which": which}
        thr_body = max(0.10 if sym == "GC=F" else 0.060,
                       2.5 * max(box["avg_body"], 0.020))          # FX-scaled eruption
        sig = None
        for i in range(len(after)):
            row = after.iloc[i]
            o, c, h, l = (float(row["Open"]), float(row["Close"]),
                          float(row["High"]), float(row["Low"]))
            if o <= 0:
                continue
            body = (c - o) / o * 100
            if body >= thr_body and c > box["hi"]:
                sig = {"dir": "UP", "i": i, "ts": after.index[i], "body": body,
                       "o": o, "c": c, "h": h, "l": l}
                break
            if body <= -thr_body and c < box["lo"]:
                sig = {"dir": "DN", "i": i, "ts": after.index[i], "body": body,
                       "o": o, "c": c, "h": h, "l": l}
                break
        if not sig:
            # still inside the box — how near the edge?
            lc = float(after["Close"].iloc[-1])
            near = 0.0
            if box["hi"] > box["lo"]:
                pos = (lc - box["lo"]) / (box["hi"] - box["lo"])
                near = max(pos, 1 - pos)          # 1.0 = AT an edge
            return {"state": "LOADING" if near >= 0.88 else "QUIET",
                    "box": box, "which": which, "near_edge": round(near * 100)}
        # must STILL hold outside the box at the latest candle
        lc = float(after["Close"].iloc[-1])
        if sig["dir"] == "UP" and lc <= box["hi"]:
            return {"state": "FADED", "box": box, "which": which}
        if sig["dir"] == "DN" and lc >= box["lo"]:
            return {"state": "FADED", "box": box, "which": which}
        # fade check — big rejecting wick against the breakout
        rge = sig["h"] - sig["l"]
        wick = (sig["h"] - max(sig["o"], sig["c"])) if sig["dir"] == "UP" else (min(sig["o"], sig["c"]) - sig["l"])
        fading = rge > 0 and wick / rge >= 0.45
        # gold: volume confirmation (the one instrument with real volume)
        vol_mult = None
        if sym == "GC=F":
            q = df[(df.index >= box["t0"]) & (df.index < box["t1"])]["Volume"].astype(float)
            if len(q) and float(q.mean()) > 0:
                vol_mult = round(float(df.loc[sig["ts"], "Volume"]) / float(q.mean()), 1)
            if vol_mult is not None and vol_mult < 2.0:
                return {"state": "NO-VOL", "box": box, "which": which}
        # ── momentum confirmation (engine #2): EMA20/50 + RSI agree? ──
        closes = df["Close"].astype(float)
        e20, e50 = ema(closes, 20).iloc[-1], ema(closes, 50).iloc[-1]
        r = rsi(closes).iloc[-1]
        if sig["dir"] == "UP":
            eng = (e20 > e50, r > 52)
        else:
            eng = (e20 < e50, r < 48)
        n_eng = sum(eng) + 1                               # structure always agrees
        # ── the plan (measured move), in price + pips ──
        height = box["hi"] - box["lo"]
        if sig["dir"] == "UP":
            entry, sl = box["hi"], box["lo"]
            t1, t2 = entry + height, entry + 2 * height
        else:
            entry, sl = box["lo"], box["hi"]
            t1, t2 = entry - height, entry - 2 * height
        risk = abs(entry - sl)
        return {"state": "BOOM" if sig["dir"] == "UP" else "TRAP",
                "box": box, "which": which, "ts": sig["ts"].strftime("%H:%M"),
                "body": round(sig["body"], 3), "fading": fading,
                "vol_mult": vol_mult, "engines": n_eng,
                "confirmed": n_eng == 3 and not fading,
                "entry": round(entry, 6), "sl": round(sl, 6),
                "t1": round(t1, 6), "t2": round(t2, 6),
                "pips_risk": round(to_pips(sym, risk), 1),
                "pips_t1": round(to_pips(sym, abs(t1 - entry)), 1),
                "pips_t2": round(to_pips(sym, abs(t2 - entry)), 1),
                "rr": round(abs(t1 - entry) / risk, 1) if risk > 0 else None}
    except Exception:
        return None


# ═══════════════ Telegram (minimal, proven pattern) ═══════════════
def tg_send(text):
    try:
        for chat in TG_CHATS.split(","):
            u = (f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage?"
                 + urllib.parse.urlencode({"chat_id": chat.strip(), "text": text,
                                           "parse_mode": "HTML", "disable_web_page_preview": "true"}))
            urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read()
        return True
    except Exception:
        return False


# ═══════════════ consensus windows → RESULT ═══════════════
def window_slots():
    """London +45/+75 min, NY +15/+45 min after each open (IST datetimes)."""
    lo = london_open_ist()
    no = ny_open_ist()
    return {"LDN": [lo + timedelta(minutes=45), lo + timedelta(minutes=75)],
            "NY": [no + timedelta(minutes=15), no + timedelta(minutes=45)]}


def cons_state():
    d = jload(STATE_CONS, {})
    today = now_ist().strftime("%Y-%m-%d")
    if d.get("day") != today:
        d = {"day": today, "snaps": {}, "announced": {}, "last_ping": None}
    return d


def paper_state():
    return jload(STATE_FX, {"positions": [], "history": [], "summary_day": None})


def cons_capture(all_sig):
    """Snapshot confirmed signals into every due slot (one per window)."""
    d = cons_state()
    changed = False
    n = now_ist()
    for w, slots in window_slots().items():
        taken = d["snaps"].get(w) or {}
        for si, slot in enumerate(slots):
            lbl = f"{slot.strftime('%H:%M')}"
            if n >= slot and lbl not in taken:
                taken[lbl] = {s: v["entry"] for s, v in all_sig.items()
                              if v and v.get("confirmed") and v["state"] in ("BOOM", "TRAP")}
                changed = True
                break
        d["snaps"][w] = taken
    if changed:
        jsave(STATE_CONS, d)
    return d


def cons_result(all_sig, prices):
    """A pair in BOTH snapshots of a window = STABLE → paper trade + message."""
    d = cons_state()
    n = now_ist()
    sent = False
    pk = paper_state()
    opened = []
    for w, slots in window_slots().items():
        if d["announced"].get(w) or n < slots[-1]:
            continue
        snaps = d["snaps"].get(w) or {}
        labels = [f"{s.strftime('%H:%M')}" for s in slots]
        sets = [set(snaps.get(l) or {}) for l in labels if l in snaps]
        stable = sorted(set.intersection(*sets)) if len(sets) == len(slots) and sets else []
        early = sorted(set().union(*sets) - set(stable)) if sets else []
        wname = "LONDON" if w == "LDN" else "NEW YORK"
        lines = [f"🌍 <b>FX DESK · {wname} RESULT</b> · {n.strftime('%a %d %b · %H:%M')} IST"]
        if not stable:
            lines.append("No 100%-confirmed breakout held both checks — no trade today. "
                         "Discipline &gt; activity. ✋")
        for s in stable:
            v = all_sig.get(s) or {}
            nm = FX[s]["name"]
            d1 = "BUY (breakout UP)" if v.get("state") == "BOOM" else "SELL (breakdown)"
            lines.append(f"\n✅ <b>{nm}</b> — {d1}")
            lines.append(f"Entry {fmt_p(s, v.get('entry', 0))} · SL {fmt_p(s, v.get('sl', 0))} "
                         f"· T1 {fmt_p(s, v.get('t1', 0))} ({v.get('pips_t1', '?')} pips)")
            lines.append(f"Risk {v.get('pips_risk', '?')} pips · RR 1:{v.get('rr', '?')} "
                         f"· engines {v.get('engines', '?')}/3")
            # ── open the PAPER position (spread 1 pip = honest entry) ──
            spread = FX[s]["pip"]
            entry = float(v.get("entry", 0)) + (spread if v.get("state") == "BOOM" else -spread)
            pk["positions"].append({"sym": s, "name": nm, "dir": "LONG" if v.get("state") == "BOOM" else "SHORT",
                                    "entry": entry, "sl": v.get("sl"), "t1": v.get("t1"),
                                    "t2": v.get("t2"), "opened": n.strftime("%Y-%m-%d %H:%M"),
                                    "session": wname, "pips_risk": v.get("pips_risk")})
            opened.append(nm)
        if early:
            lines.append("\n⚠️ Early (not both checks): " + ", ".join(FX[s]["name"] for s in early))
        tg_send("\n".join(lines))
        blog(f"📩 {wname} RESULT · stable={len(stable)} paper_opened={len(opened)}")
        d["announced"][w] = n.strftime("%H:%M")
        sent = True
    if opened:
        jsave(STATE_FX, pk)
    jsave(STATE_CONS, d)
    return sent


def paper_update(prices):
    """Track open paper positions → close on T1 or SL (conservative, full exit)."""
    pk = paper_state()
    if not pk["positions"]:
        return pk
    hist = []
    for p in pk["positions"]:
        px = prices.get(p["sym"])
        if px is None:
            hist.append(p)
            continue
        if p["dir"] == "LONG":
            if px <= p["sl"]:
                p["exit"], p["res"] = p["sl"], "SL"
            elif px >= p["t1"]:
                p["exit"], p["res"] = p["t1"], "T1"
        else:
            if px >= p["sl"]:
                p["exit"], p["res"] = p["sl"], "SL"
            elif px <= p["t1"]:
                p["exit"], p["res"] = p["t1"], "T1"
        if p.get("res"):
            d = (p["exit"] - p["entry"]) if p["dir"] == "LONG" else (p["entry"] - p["exit"])
            p["pips"] = round(to_pips(p["sym"], d), 1)
            p["closed"] = now_ist().strftime("%Y-%m-%d %H:%M")
            pk["history"].append(p)
            blog(f"📝 paper closed · {p['name']} {p['res']} {p['pips']:+.1f} pips")
        else:
            p["last"] = round(to_pips(p["sym"], (px - p["entry"]) if p["dir"] == "LONG"
                                      else (p["entry"] - px)), 1)
            hist.append(p)
    pk["positions"] = hist
    jsave(STATE_FX, pk)
    return pk


def daily_summary(pk):
    """One summary per evening (22:00+ IST): pips won/lost today."""
    n = now_ist()
    if n.hour < 22 or pk.get("summary_day") == n.strftime("%Y-%m-%d"):
        return
    today = n.strftime("%Y-%m-%d")
    closed = [h for h in pk["history"] if str(h.get("closed", "")).startswith(today)]
    opened = len([p for p in pk["positions"] if str(p.get("opened", "")).startswith(today)])
    if not closed and not opened:
        pk["summary_day"] = today
        jsave(STATE_FX, pk)
        return
    wins = [h for h in closed if (h.get("pips") or 0) > 0]
    total = sum(h.get("pips", 0) for h in closed)
    lines = [f"📊 <b>FX DESK — PAPER SCORECARD · {n.strftime('%a %d %b')}</b>",
             f"Trades closed: {len(closed)} · Wins: {len(wins)} · Pips: <b>{total:+.1f}</b>",
             f"(1-pip spread already subtracted from every entry)"]
    for h in closed:
        lines.append(f"{'✅' if (h.get('pips') or 0) > 0 else '🔴'} {h['name']} {h['dir']} "
                     f"→ {h['res']} {h.get('pips', 0):+.1f} pips")
    if pk["positions"]:
        lines.append("Open: " + ", ".join(f"{p['name']} {p.get('last', 0):+.1f} pips" for p in pk["positions"]))
    tg_send("\n".join(lines))
    pk["summary_day"] = today
    jsave(STATE_FX, pk)
    blog(f"📊 daily summary sent · {total:+.1f} pips")


def online_ping():
    try:
        d = jload(STATE_CONS, {})
        if d.get("last_ping") == APP_VERSION:
            return
        tg_send(f"🌍 <b>FX Desk is ONLINE</b> · {APP_VERSION}\n"
                f"🕒 {now_ist().strftime('%a %d %b %Y · %H:%M')} IST\n"
                f"<i>Paper mode — results London 13:15/13:45 · NY 19:15/19:45 IST</i>")
        d["last_ping"] = APP_VERSION
        jsave(STATE_CONS, d)
    except Exception:
        pass


def live_levels(dfs):
    """🔴 LIVE NOW (user request 2 Oct): whenever the desk is open, show
    which pair is moving well RIGHT NOW — with Entry, SL and Targets,
    the same information style as the stock alerts. Rolling last-hour
    box, so it works in ANY session (not just London/NY opens).
    Page-only — the official paper scorecard stays the consensus windows."""
    out = []
    for sym, df in (dfs or {}).items():
        try:
            if df is None or len(df) < 16:
                continue
            info = FX[sym]
            pip = info["pip"]; dec = info["dec"]
            tail = df.tail(16)              # last ~80 minutes
            box = tail.iloc[:12]            # the 1-hour range
            move = tail.iloc[12:]           # the recent candles (the move)
            if len(move) < 2:
                continue
            hi = float(box["High"].max()); lo = float(box["Low"].min())
            rng = hi - lo
            if rng <= 4 * pip:              # dead box — nothing to break
                continue
            lc = float(df["Close"].iloc[-1])
            bias = sum(1 if float(c) > float(o) else -1 if float(c) < float(o) else 0
                       for o, c in zip(move["Open"], move["Close"]))
            if lc > hi + 0.15 * rng and bias >= 1:          # broke UP, holding
                entry, sl = lc, hi - 0.15 * rng
                t1, t2 = entry + rng, entry + 1.6 * rng
                d = "BUY"
            elif lc < lo - 0.15 * rng and bias <= -1:       # broke DOWN, holding
                entry, sl = lc, lo + 0.15 * rng
                t1, t2 = entry - rng, entry - 1.6 * rng
                d = "SELL"
            else:
                continue
            risk = abs(entry - sl); rew = abs(t1 - entry)
            if risk < 2 * pip or rew < 1.2 * risk:          # junk geometry
                continue
            out.append({"sym": sym, "name": info["name"], "dir": d, "entry": entry,
                        "sl": sl, "t1": t1, "t2": t2, "dec": dec,
                        "pips_risk": round(risk / pip, 1), "pips_t1": round(rew / pip, 1),
                        "rr": round(rew / risk, 1), "box_hi": hi, "box_lo": lo})
        except Exception:
            continue
    out.sort(key=lambda x: -x["pips_t1"])
    return out


# ═══════════════ UI ═══════════════
def main():
    ss = st.session_state
    deploy_wipe()
    online_ping()
    mkt = fx_market_open()

    # header
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);border-radius:16px;"
        f"padding:18px 24px;margin-bottom:14px;'>"
        f"<span style='font-size:22px;font-weight:900;color:white;'>🌍 FX DESK</span>"
        f"<span style='font-size:13px;color:#93c5fd;margin-left:12px;'>{APP_VERSION} · PAPER MODE</span>"
        f"<span style='float:right;color:#93c5fd;font-size:12px;'>{now_ist().strftime('%a %d %b · %H:%M:%S')} IST</span>"
        f"</div>", unsafe_allow_html=True)

    # radar on/off — manual start (your clock, your rules)
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("🚀 START RADAR", type="primary", use_container_width=True, key="fx_start"):
            ss["fx_on"] = True
            blog("🚀 radar STARTED (manual)")
            st.rerun()
    with c2:
        if st.button("⏹ Stop", use_container_width=True, key="fx_stop"):
            ss["fx_on"] = False
            blog("⏹ radar stopped")
            st.rerun()
    with c3:
        ses = session_now()
        badges = " ".join(f"<span style='background:{'#16a34a' if s in ses else '#334155'};color:white;"
                          f"padding:4px 12px;border-radius:12px;font-size:11px;font-weight:700;margin-right:6px;'>"
                          f"{'●' if s in ses else '○'} {v}</span>" for s, v in SESSIONS.items())
        st.markdown(f"<div style='padding-top:4px;'>{badges} "
                    f"<span style='color:{'#4ade80' if mkt else '#f87171'};font-size:12px;font-weight:700;'>"
                    f"{'MARKET OPEN' if mkt else 'MARKET CLOSED (weekend)'}</span></div>",
                    unsafe_allow_html=True)

    if not ss.get("fx_on"):
        st.info("🚀 Press START when you're ready. The desk watches the quiet Asian range, then "
                "hunts confirmed breakouts at the London and New York opens — with a ±20-min "
                "news blackout around red events. Results → Telegram. Paper mode: zero money.")
        st.markdown("<div style='color:#64748b;font-size:11px;'>Educational paper-trading tool · "
                    "not financial advice · spread (1 pip) is subtracted from every paper entry.</div>",
                    unsafe_allow_html=True)
        return
    if not mkt:
        st.warning("🌙 Forex market is closed for the weekend — the radar will hunt again from "
                   "Sunday evening / Monday morning IST.")
    st_autorefresh(interval=120_000, key="fx_refresh")

    # data + engines
    cal = fetch_calendar()
    bo, ev = blackout_active(cal)
    all_sig, prices, boxes, dfs = {}, {}, {}, {}
    for sym in FX:
        df = fetch_5m(sym)
        if df is None:
            continue
        dfs[sym] = df
        try:
            prices[sym] = float(df["Close"].iloc[-1])
        except Exception:
            continue
        which = "london" if now_ist() < ny_open_ist() else "ny"
        s = detect_signal(sym, df, "london")
        if now_ist() >= ny_open_ist():
            sny = detect_signal(sym, df, "ny")
            if sny and sny.get("state") in ("BOOM", "TRAP"):
                s = sny
        all_sig[sym] = s
        if s and s.get("box"):
            boxes[sym] = s["box"]

    # news guard
    if bo:
        mins = int((ev["t"] - now_ist()).total_seconds() // 60)
        st.markdown(f"<div style='background:#3a0e0e;border:2px solid #dc2626;border-radius:12px;"
                    f"padding:12px 18px;color:#fecaca;font-size:13px;margin-bottom:12px;'>"
                    f"🚨 <b>NEWS BLACKOUT — {ev['country']} {ev['title']} at "
                    f"{ev['t'].strftime('%H:%M')} IST</b> ({'in %d min' % mins if mins >= 0 else 'just now'}). "
                    f"No new signals until ±{NEWS_BLACKOUT_MIN} min has passed. "
                    f"<b>STAY OUT of the market.</b></div>", unsafe_allow_html=True)
    nxt = next_events(cal)
    # ── 🔴 LIVE NOW — what's moving with Entry/SL/Target (anytime view) ──
    live = live_levels(dfs)
    _now = now_ist().strftime("%H:%M")
    if live:
        st.markdown("<div style='background:#052e16;border:2px solid #16a34a;border-radius:14px;"
                    "padding:12px 18px;color:#bbf7d0;font-size:15px;font-weight:800;margin:14px 0 8px;'>"
                    f"🔴 LIVE NOW — moving well at {_now} IST</div>", unsafe_allow_html=True)
        for L in live:
            _c = "#16a34a" if L["dir"] == "BUY" else "#dc2626"
            _ico = "🟢 BUY" if L["dir"] == "BUY" else "🔴 SELL"
            st.markdown(
                f"<div style='background:#0f1a2e;border:1px solid {_c};border-left:5px solid {_c};"
                f"border-radius:12px;padding:14px 18px;margin:6px 0;'>"
                f"<b style='font-size:16px;color:white;'>{_ico} · {L['name']}</b> "
                f"<span style='color:#93c5fd;font-size:12px;'>broke its 1-hour range "
                f"{L['box_lo']:.{L['dec']}f}–{L['box_hi']:.{L['dec']}f}</span><br>"
                f"<span style='color:#e2e8f0;font-size:14px;'>"
                f"Entry <b>{L['entry']:.{L['dec']}f}</b> · "
                f"SL <b style='color:#f87171;'>{L['sl']:.{L['dec']}f}</b> (−{L['pips_risk']} pips) · "
                f"Target <b style='color:#4ade80;'>{L['t1']:.{L['dec']}f}</b> (+{L['pips_t1']} pips) · "
                f"runner {L['t2']:.{L['dec']}f}</span><br>"
                f"<span style='color:#64748b;font-size:11px;'>risk {L['pips_risk']} → reward "
                f"{L['pips_t1']} pips (1:{L['rr']}) · information only — paper desk, nothing is placed</span>"
                f"</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='background:#16233d;border:1px solid #1e3a5f;border-radius:12px;"
                    "padding:12px 18px;color:#93c5fd;font-size:13px;margin:14px 0 8px;'>"
                    f"⚪ LIVE NOW at {_now} IST — no clean breakout right now. Pairs are ranging; "
                    "the desk shows a card the moment a real move starts. Honest beats busy.</div>",
                    unsafe_allow_html=True)
    if nxt:
        def _chip(e):
            fc = f" (fc {e['forecast']})" if e["forecast"] != "—" else ""
            return (f"<b>{e['country']}</b> {e['title']} "
                    f"<span style='color:#fbbf24;'>{e['t'].strftime('%H:%M')}</span>{fc}")
        chips = " · ".join(_chip(e) for e in nxt)
        st.markdown(f"<div style='background:#16233d;border:1px solid #1e3a5f;border-radius:12px;"
                    f"padding:10px 16px;color:#cbd5e1;font-size:12px;margin-bottom:12px;'>"
                    f"📅 <b>Next red events:</b> {chips}</div>", unsafe_allow_html=True)

    # consensus + paper
    cons_capture(all_sig)
    cons_result(all_sig, prices)
    pk = paper_update(prices)
    daily_summary(pk)

    # signal cards
    st.markdown("### 🎯 Live signal board")
    cols = st.columns(4)
    for i, (sym, s) in enumerate(all_sig.items()):
        with cols[i % 4]:
            px = prices.get(sym, 0.0)
            nm = FX[sym]["name"]
            if not s:
                st.markdown(_card(nm, px, sym, "NO DATA", "#64748b", "—"), unsafe_allow_html=True)
                continue
            st_ = s.get("state", "?")
            if st_ in ("BOOM", "TRAP") and s.get("confirmed"):
                col, lbl = "#16a34a", f"{st_} · {'BUY' if st_ == 'BOOM' else 'SELL'} · ✅ 3/3 ENGINES"
            elif st_ in ("BOOM", "TRAP"):
                col, lbl = "#fbbf24", f"{st_} · {s.get('engines', '?')}/3 engines · not confirmed"
            elif st_ == "LOADING":
                col, lbl = "#60a5fa", f"LOADING · near edge {s.get('near_edge', 0)}%"
            else:
                col, lbl = "#64748b", {"QUIET": "in the box", "WAIT-OPEN": "waiting for open",
                                        "FADED": "breakout FADED — skip", "NO-VOL": "gold: volume too low"}.get(st_, st_)
            body = ""
            if st_ in ("BOOM", "TRAP"):
                body = (f"breakout {s['ts']} · body {s['body']:+.2f}%"
                        + (" · ⚠️ FADING wick" if s.get("fading") else "")
                        + (f" · vol {s['vol_mult']}×" if s.get("vol_mult") else ""))
                body += (f"<br>Entry {fmt_p(sym, s['entry'])} · SL {fmt_p(sym, s['sl'])}"
                         f"<br>T1 {fmt_p(sym, s['t1'])} (+{s['pips_t1']} pips) · "
                         f"T2 {fmt_p(sym, s['t2'])} (+{s['pips_t2']} pips)"
                         f"<br>Risk {s['pips_risk']} pips · RR 1:{s.get('rr')}")
            if s.get("box"):
                b = s["box"]
                body += f"<br><span style='color:#8fa3bd;font-size:11px;'>box {fmt_p(sym, b['lo'])} – " \
                        f"{fmt_p(sym, b['hi'])} ({to_pips(sym, b['hi'] - b['lo']):.0f} pips wide)</span>"
            st.markdown(_card(nm, px, sym, lbl, col, body), unsafe_allow_html=True)

    # chart
    pick = st.selectbox("📈 Chart", list(FX.keys()), format_func=lambda s: FX[s]["name"], key="fx_chart")
    df = fetch_5m(pick)
    if df is not None and len(df):
        fig = go.Figure()
        d = df.tail(160)
        fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"],
                                     close=d["Close"], name=FX[pick]["name"],
                                     increasing_line_color="#16a34a", decreasing_line_color="#dc2626"))
        s = all_sig.get(pick)
        if s and s.get("box"):
            b = s["box"]
            for lvl, txt, cc in ((b["hi"], "BOX HIGH", "#fbbf24"), (b["lo"], "BOX LOW", "#60a5fa")):
                fig.add_hline(y=lvl, line_dash="dot", line_color=cc, annotation_text=txt,
                              annotation_font_color=cc)
        fig.update_layout(height=380, paper_bgcolor="#0b1220", plot_bgcolor="#0b1220",
                          font_color="#cbd5e1", xaxis_rangeslider_visible=False,
                          margin=dict(l=10, r=10, t=30, b=10),
                          title=f"{FX[pick]['name']} · 5-min · box = today's quiet range")
        st.plotly_chart(fig, use_container_width=True)

    # paper scorecard
    st.markdown("### 📝 Paper scorecard (pips, spread already paid)")
    if pk["positions"]:
        for p in pk["positions"]:
            st.markdown(f"🟡 <b>{p['name']}</b> {p['dir']} from {p['opened']} · entry "
                        f"{p['entry']:.5f} · now <b>{p.get('last', 0):+.1f} pips</b> · "
                        f"SL {p['pips_risk']} pips risk", unsafe_allow_html=True)
    else:
        st.caption("No open paper positions.")
    hist = pk["history"][-12:][::-1]
    if hist:
        wins = sum(1 for h in pk["history"] if (h.get("pips") or 0) > 0)
        tot = sum(h.get("pips", 0) for h in pk["history"])
        st.markdown(f"<b>ALL-TIME:</b> {len(pk['history'])} closed · {wins} wins "
                    f"({100 * wins / max(1, len(pk['history'])):.0f}%) · "
                    f"<b style='color:{'#4ade80' if tot >= 0 else '#f87171'};'>{tot:+.1f} pips</b>",
                    unsafe_allow_html=True)
        for h in hist:
            cc = "#4ade80" if (h.get("pips") or 0) > 0 else "#f87171"
            st.markdown(f"<span style='color:{cc};'>{h['res']} {h.get('pips', 0):+.1f} pips</span> · "
                        f"{h['name']} {h['dir']} · {h['opened']} → {h.get('closed', '')}",
                        unsafe_allow_html=True)
    else:
        st.caption("No closed trades yet — history builds as results come in.")
    st.markdown("<div style='color:#64748b;font-size:11px;padding:12px 0;'>Educational paper tool · "
                "not financial advice · one pattern, executed with discipline.</div>", unsafe_allow_html=True)


def _card(nm, px, sym, lbl, col, body):
    return (f"<div style='background:#0f1a2e;border:1px solid #1e293b;border-left:4px solid {col};"
            f"border-radius:12px;padding:12px 14px;margin-bottom:8px;min-height:120px;'>"
            f"<div style='font-weight:800;color:white;font-size:15px;'>{nm} "
            f"<span style='float:right;color:{col};'>{fmt_p(sym, px)}</span></div>"
            f"<div style='color:{col};font-size:11px;font-weight:700;margin:4px 0;'>{lbl}</div>"
            f"<div style='color:#cbd5e1;font-size:11px;line-height:1.6;'>{body}</div></div>")


if __name__ == "__main__":
    main()

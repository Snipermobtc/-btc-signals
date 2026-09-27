#!/usr/bin/env python3
"""
BTC NY Opening Signal Bot - GitHub Actions Edition
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIGURATIE
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SignalBot")

# ============================================================
# DATA FETCHING
# ============================================================

class DataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SignalBot/1.0'})

    def get_binance_klines(self, symbol="BTCUSDT", interval="1m", limit=1000):
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data or isinstance(data, dict):
                return []
            result = []
            for candle in data:
                result.append({
                    'open_time': datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc),
                    'open': float(candle[1]), 'high': float(candle[2]),
                    'low': float(candle[3]), 'close': float(candle[4]),
                    'volume': float(candle[5])
                })
            return result
        except Exception as e:
            logger.error(f"Binance error: {e}")
            return []

    def get_vix(self):
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
            r = self.session.get(url, params={"interval": "1d", "range": "1d"}, timeout=10)
            data = r.json()
            if 'chart' in data and data['chart']['result']:
                meta = data['chart']['result'][0]['meta']
                return float(meta.get('regularMarketPrice', meta.get('previousClose', 20)))
        except Exception as e:
            logger.warning(f"VIX failed: {e}")
        return None

    def get_funding(self, symbol="BTCUSDT"):
        try:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            r = self.session.get(url, params={"symbol": symbol}, timeout=10)
            return float(r.json().get('lastFundingRate', 0))
        except Exception as e:
            logger.warning(f"Funding failed: {e}")
            return 0.0

    def get_fear_index(self):
        try:
            r = self.session.get("https://api.alternative.me/fng/", timeout=10)
            data = r.json()
            if 'data' in data and len(data['data']) > 0:
                return int(data['data'][0]['value'])
        except Exception as e:
            logger.warning(f"Fear index failed: {e}")
        return 50

# ============================================================
# STRATEGIE
# ============================================================

class SignalEngine:
    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.data = []

    def load(self):
        logger.info("Loading BTC data...")
        self.data = self.fetcher.get_binance_klines(limit=1500)
        if not self.data:
            return False
        logger.info(f"Loaded {len(self.data)} candles")
        return True

    def cme_gap(self, today):
        friday = today - timedelta(days=(today.weekday() + 2) % 7)
        friday_close = datetime.combine(friday, datetime.min.time().replace(hour=21, minute=0))
        friday_close = friday_close.replace(tzinfo=timezone.utc)

        friday_price = None
        for c in self.data:
            if c['open_time'] <= friday_close:
                friday_price = c['close']

        if friday_price is None:
            return None, None

        current = self.data[-1]['close']
        gap_pct = (current - friday_price) / friday_price
        return gap_pct, abs(current - friday_price)

    def premarket(self, today):
        start = datetime.combine(today, datetime.min.time().replace(hour=12, minute=0), tzinfo=timezone.utc)
        end = datetime.combine(today, datetime.min.time().replace(hour=13, minute=25), tzinfo=timezone.utc)

        pre = [c for c in self.data if start <= c['open_time'] <= end]
        if len(pre) < 20:
            return None

        high = max(c['high'] for c in pre)
        low = min(c['low'] for c in pre)
        close = pre[-1]['close']
        pos = (close - low) / (high - low) if high != low else 0.5

        return {'high': high, 'low': low, 'close': close, 'position': pos}

    def calculate(self, today):
        logger.info("="*50)
        logger.info(f"SIGNAL ANALYSIS - {today.strftime('%Y-%m-%d')}")
        logger.info("="*50)

        gap_pct, gap_size = self.cme_gap(today)
        pre = self.premarket(today)

        if gap_pct is None or pre is None:
            logger.error("Insufficient data")
            return None

        vix = self.fetcher.get_vix()
        funding = self.fetcher.get_funding()
        fear = self.fetcher.get_fear_index()

        logger.info(f"Gap: {gap_pct:.3%} | VIX: {vix} | Funding: {funding:.4%} | Fear: {fear}")

        score = 50
        reasons = []

        if gap_pct < -0.003:
            score += 18
            reasons.append(f"CME gap DOWN {gap_pct:.2%} -> LONG")
        elif gap_pct > 0.003:
            score -= 18
            reasons.append(f"CME gap UP {gap_pct:.2%} -> SHORT")

        if pre['position'] > 0.7:
            score += 12
            reasons.append("Pre-market closing near HIGH")
        elif pre['position'] < 0.3:
            score -= 12
            reasons.append("Pre-market closing near LOW")

        if vix and vix > 30:
            score += 14
            reasons.append(f"VIX FEAR {vix:.1f}")
        elif vix and vix < 12:
            score -= 14
            reasons.append(f"VIX complacency {vix:.1f}")

        if fear < 20:
            score += 10
            reasons.append(f"Extreme FEAR {fear}/100")
        elif fear > 75:
            score -= 10
            reasons.append(f"Extreme GREED {fear}/100")

        if funding > 0.01:
            score += 8
            reasons.append(f"Positive funding {funding:.3%}")
        elif funding < -0.01:
            score -= 8
            reasons.append(f"Negative funding {funding:.3%}")

        if today.weekday() == 0:
            score += 5
            reasons.append("Monday CME gap fill bias")

        score = max(0, min(100, score))

        if score >= 75:
            direction = "LONG"
            emoji = "🚀"
        elif score <= 25:
            direction = "SHORT"
            emoji = "📉"
        else:
            direction = "NO TRADE"
            emoji = "🚫"

        atr = self._atr()
        entry = pre['close']

        if direction == "LONG":
            sl = entry - 2 * atr
            tp = entry + 3 * atr
        elif direction == "SHORT":
            sl = entry + 2 * atr
            tp = entry - 3 * atr
        else:
            sl = tp = None

        return {
            'date': today.strftime('%Y-%m-%d'),
            'time': datetime.now(timezone.utc).strftime('%H:%M UTC'),
            'direction': direction,
            'emoji': emoji,
            'score': score,
            'entry': entry,
            'stop_loss': sl,
            'take_profit': tp,
            'atr': atr,
            'gap_pct': gap_pct,
            'vix': vix,
            'funding': funding,
            'fear': fear,
            'reasons': reasons
        }

    def _atr(self, period=14):
        if len(self.data) < period + 1:
            return self.data[-1]['close'] * 0.01
        trs = []
        for i in range(1, len(self.data)):
            h, l, pc = self.data[i]['high'], self.data[i]['low'], self.data[i-1]['close']
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        return sum(trs[-period:]) / period

# ============================================================
# ALERTS - PLAIN TEXT (geen Markdown, geen formatting issues)
# ============================================================

def send_alert(signal):
    if signal['direction'] == "NO TRADE":
        msg = f"BTC NY OPEN - NO TRADE\n\n"
        msg += f"Date: {signal['date']} {signal['time']}\n"
        msg += f"Score: {signal['score']}/100 (too weak)\n"
        msg += f"BTC Price: ${signal['entry']:,.2f}\n\n"
        msg += f"Market conditions:\n"
        msg += f"- VIX: {signal['vix']}\n"
        msg += f"- Fear Index: {signal['fear']}/100\n"
        msg += f"- Funding: {signal['funding']:.4%}\n\n"
        msg += f"Stay flat today."
    else:
        msg = f"{signal['emoji']} BTC NY OPEN SIGNAL\n\n"
        msg += f"Date: {signal['date']} {signal['time']}\n"
        msg += f"Direction: {signal['direction']}\n"
        msg += f"Confidence: {signal['score']}/100\n\n"
        msg += f"Entry: ${signal['entry']:,.2f}\n"
        msg += f"Stop Loss: ${signal['stop_loss']:,.2f}\n"
        msg += f"Take Profit: ${signal['take_profit']:,.2f}\n"
        msg += f"ATR: ${signal['atr']:,.2f}\n\n"
        msg += f"Why this signal:\n"
        for r in signal['reasons']:
            msg += f"- {r}\n"
        msg += f"\nThis is a signal only. You decide if you trade."

    # Telegram - eerst plain text proberen
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': msg,
                'parse_mode': None  # GEEN Markdown - plain text
            }
            r = requests.post(url, json=payload, timeout=10)
            logger.info(f"Telegram response: {r.status_code} - {r.text}")
            if r.status_code == 200:
                logger.info("Telegram alert SENT successfully")
            else:
                logger.error(f"Telegram FAILED: {r.text}")
        except Exception as e:
            logger.error(f"Telegram exception: {e}")
    else:
        logger.warning("No Telegram credentials configured")

    # Console output
    print("\n" + "="*50)
    print(msg)
    print("="*50)

# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("BTC SIGNAL BOT STARTING")
    logger.info(f"Telegram token present: {bool(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"Telegram chat ID present: {bool(TELEGRAM_CHAT_ID)}")

    fetcher = DataFetcher()
    engine = SignalEngine(fetcher)

    now = datetime.now(timezone.utc)
    today = now.date()

    if today.weekday() >= 5:
        logger.info("Weekend - no signal")
        return

    if not engine.load():
        return

    signal = engine.calculate(today)
    if signal:
        send_alert(signal)
        logger.info("Signal sent")

    logger.info("Done")

if __name__ == "__main__":
    main()

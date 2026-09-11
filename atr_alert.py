import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PAIR = os.getenv("COINDCX_PAIR", "B-BTC_USDT")
INTERVAL = os.getenv("CANDLE_INTERVAL", "15m")
ATR_LENGTH = 14
ATR_MULTIPLIER = 1.2
MIN_BODY_PERCENT = 60.0
STATE_FILE = "alert_state.json"


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GitHub-Actions-ATR-Bot"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def get_candles():
    params = urllib.parse.urlencode({
        "pair": PAIR,
        "interval": INTERVAL,
        "limit": 100
    })

    url = f"https://public.coindcx.com/market_data/candles?{params}"
    data = get_json(url)

    if isinstance(data, dict):
        candles = data.get("data", data.get("candles", []))
    else:
        candles = data

    normalized = []

    for candle in candles:
        if isinstance(candle, dict):
            timestamp = candle.get("time", candle.get("timestamp"))
            open_price = candle.get("open")
            high_price = candle.get("high")
            low_price = candle.get("low")
            close_price = candle.get("close")
        else:
            timestamp, open_price, high_price, low_price, close_price = candle[:5]

        normalized.append({
            "time": int(float(timestamp)),
            "open": float(open_price),
            "high": float(high_price),
            "low": float(low_price),
            "close": float(close_price)
        })

    return sorted(normalized, key=lambda candle: candle["time"])


def true_range(current, previous):
    return max(
        current["high"] - current["low"],
        abs(current["high"] - previous["close"]),
        abs(current["low"] - previous["close"])
    )


def calculate_atr(candles, index, length=14):
    start = index - length + 1

    if start < 1:
        return None

    ranges = []

    for i in range(start, index + 1):
        ranges.append(true_range(candles[i], candles[i - 1]))

    return sum(ranges) / len(ranges)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def main():
    candles = get_candles()

    if len(candles) < ATR_LENGTH + 2:
        raise RuntimeError("ATR হিসাবের জন্য পর্যাপ্ত candle পাওয়া যায়নি")

    # শেষ candleটি চলমান হতে পারে, তাই তার আগের candle ব্যবহার করা হচ্ছে
    index = len(candles) - 2
    candle = candles[index]

    atr = calculate_atr(candles, index, ATR_LENGTH)

    if atr is None:
        raise RuntimeError("ATR হিসাব করা যায়নি")

    body = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range <= 0:
        print("Candle range শূন্য। কোনো signal নেই।")
        return

    body_percent = (body / candle_range) * 100

    condition_1 = body >= ATR_MULTIPLIER * atr
    condition_2 = body_percent >= MIN_BODY_PERCENT
    signal = condition_1 and condition_2

    candle_time = str(candle["time"])
    state = load_state()

    print(f"Pair: {PAIR}")
    print(f"Interval: {INTERVAL}")
    print(f"Body: {body}")
    print(f"ATR(14): {atr}")
    print(f"Body/Range: {body_percent:.2f}%")
    print(f"Condition 1: {condition_1}")
    print(f"Condition 2: {condition_2}")

    if not signal:
        print("কোনো signal নেই।")
        state["last_checked_candle"] = candle_time
        save_state(state)
        return

    if state.get("last_alert_candle") == candle_time:
        print("এই candle-এর alert আগেই পাঠানো হয়েছে।")
        return

    direction = "BUY" if candle["close"] > candle["open"] else "SELL"

    candle_time_text = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        f"🚨 {direction} ATR BODY SIGNAL

"
        f"Pair: {PAIR}
"
        f"Timeframe: {INTERVAL}
"
        f"Candle close: {candle_time_text}
"
        f"Open: {candle['open']}
"
        f"High: {candle['high']}
"
        f"Low: {candle['low']}
"
        f"Close: {candle['close']}

"
        f"Body: {body:.6f}
"
        f"ATR(14): {atr:.6f}
"
        f"1.2 × ATR: {ATR_MULTIPLIER * atr:.6f}
"
        f"Body/Range: {body_percent:.2f}%

"
        f"Condition 1: ✅
"
        f"Condition 2: ✅"
    )

    send_telegram(message)

    state["last_alert_candle"] = candle_time
    state["last_checked_candle"] = candle_time
    save_state(state)

    print("Telegram alert পাঠানো হয়েছে।")


if __name__ == "__main__":
    main()

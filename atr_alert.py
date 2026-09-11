import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta


PAIR = os.getenv("COINDCX_PAIR", "B-BTC_USDT")
INTERVAL = os.getenv("CANDLE_INTERVAL", "15m")

# শুধু Condition 2 ব্যবহার করা হবে
MIN_BODY_PERCENT = 60.0

STATE_FILE = "alert_state.json"

# India Standard Time: UTC + 5:30
IST = timezone(
    timedelta(hours=5, minutes=30),
    name="GMT+05:30"
)


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GitHub-Actions-ATR-Alert-Bot"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        response_text = response.read().decode("utf-8")

    return json.loads(response_text)


def get_candles():
    query = urllib.parse.urlencode({
        "pair": PAIR,
        "interval": INTERVAL,
        "limit": 100
    })

    url = f"https://public.coindcx.com/market_data/candles?{query}"

    print(f"CoinDCX URL: {url}")

    data = get_json(url)

    if not isinstance(data, list):
        raise RuntimeError(
            f"CoinDCX অপ্রত্যাশিত response দিয়েছে: {data}"
        )

    candles = []

    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError(
                f"অপ্রত্যাশিত candle format: {item}"
            )

        required_keys = [
            "time",
            "open",
            "high",
            "low",
            "close"
        ]

        for key in required_keys:
            if key not in item:
                raise RuntimeError(
                    f"Candle data-তে '{key}' পাওয়া যায়নি: {item}"
                )

        candles.append({
            "time": int(float(item["time"])),
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"])
        })

    if len(candles) == 0:
        raise RuntimeError(
            "CoinDCX থেকে কোনো candle data পাওয়া যায়নি"
        )

    candles.sort(key=lambda candle: candle["time"])

    return candles


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def send_telegram(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN GitHub Secret পাওয়া যায়নি"
        )

    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID GitHub Secret পাওয়া যায়নি"
        )

    telegram_url = (
        f"https://api.telegram.org/bot{bot_token}/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        telegram_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            )
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        response_text = response.read().decode("utf-8")

    result = json.loads(response_text)

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram error: {result}"
        )


def main():
    print("Body/Range alert bot শুরু হয়েছে")
    print(f"Pair: {PAIR}")
    print(f"Interval: {INTERVAL}")
    print("Timezone: GMT+05:30")
    print("Active condition: Body/Range >= 60%")

    candles = get_candles()

    print(f"মোট candle পাওয়া গেছে: {len(candles)}")

    # শেষ candleটি চলমান হতে পারে।
    # তাই তার আগের candle ব্যবহার করা হচ্ছে।
    if len(candles) < 2:
        raise RuntimeError(
            "কমপক্ষে 2টি candle দরকার"
        )

    candle_index = len(candles) - 2
    candle = candles[candle_index]

    body = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range <= 0:
        print("Candle range শূন্য। কোনো signal নেই।")
        return

    body_percent = (body / candle_range) * 100

    # শুধু Condition 2
    condition_2 = body_percent >= MIN_BODY_PERCENT

    print(f"Body: {body}")
    print(f"High - Low: {candle_range}")
    print(f"Body/Range: {body_percent:.2f}%")
    print(f"Condition 2: {condition_2}")

    state = load_state()
    candle_id = str(candle["time"])

    if not condition_2:
        print(
            "Body/Range 60%-এর কম। "
            "এই candle signal-এর শর্ত পূরণ করেনি।"
        )

        state["last_checked_candle"] = candle_id
        save_state(state)

        return

    if state.get("last_alert_candle") == candle_id:
        print("এই candle-এর alert আগেই পাঠানো হয়েছে।")
        return

    if candle["close"] > candle["open"]:
        direction = "BUY"
    elif candle["close"] < candle["open"]:
        direction = "SELL"
    else:
        print("Doji candle। কোনো signal নেই।")
        return

    candle_time = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    )

    candle_time_ist = candle_time.astimezone(IST)

    candle_time_text = candle_time_ist.strftime(
        "%Y-%m-%d %H:%M:%S GMT+05:30"
    )

    message = f"""🚨 {direction} BODY/RANGE SIGNAL

Pair: {PAIR}
Timeframe: {INTERVAL}
Candle close: {candle_time_text}

Open: {candle["open"]}
High: {candle["high"]}
Low: {candle["low"]}
Close: {candle["close"]}

Body: {body:.6f}
High - Low: {candle_range:.6f}
Body/Range: {body_percent:.2f}%

Condition 2:
Body / (High - Low) >= 60% ✅
"""

    send_telegram(message)

    state["last_alert_candle"] = candle_id
    state["last_checked_candle"] = candle_id
    save_state(state)

    print("Telegram alert সফলভাবে পাঠানো হয়েছে।")


if __name__ == "__main__":
    main()

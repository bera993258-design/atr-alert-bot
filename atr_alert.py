import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


PAIR = os.getenv("COINDCX_PAIR", "B-BTC_USDT")
INTERVAL = os.getenv("CANDLE_INTERVAL", "15m")

ATR_LENGTH = 14
ATR_MULTIPLIER = 1.2
MIN_BODY_PERCENT = 60.0

STATE_FILE = "alert_state.json"

# India Standard Time
IST = ZoneInfo("Asia/Kolkata")


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


def calculate_true_range(current_candle, previous_candle):
    high_low = current_candle["high"] - current_candle["low"]

    high_previous_close = abs(
        current_candle["high"] - previous_candle["close"]
    )

    low_previous_close = abs(
        current_candle["low"] - previous_candle["close"]
    )

    return max(
        high_low,
        high_previous_close,
        low_previous_close
    )


def calculate_atr(candles, candle_index):
    first_index = candle_index - ATR_LENGTH + 1

    if first_index < 1:
        return None

    true_ranges = []

    for index in range(first_index, candle_index + 1):
        current_candle = candles[index]
        previous_candle = candles[index - 1]

        current_true_range = calculate_true_range(
            current_candle,
            previous_candle
        )

        true_ranges.append(current_true_range)

    return sum(true_ranges) / len(true_ranges)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        print("alert_state.json সঠিক JSON নয়। নতুন state শুরু হচ্ছে।")
        return {}


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


def format_number(value):
    return f"{value:.8f}".rstrip("0").rstrip(".")


def main():
    print("ATR Body/Range alert bot শুরু হয়েছে")
    print(f"Pair: {PAIR}")
    print(f"Interval: {INTERVAL}")
    print("Timezone: Asia/Kolkata / IST")
    print("Report: প্রতি closed candle")

    candles = get_candles()

    print(f"মোট candle পাওয়া গেছে: {len(candles)}")

    # শেষ candle চলমান হতে পারে।
    # তাই তার আগের candle ব্যবহার করা হচ্ছে।
    if len(candles) < ATR_LENGTH + 2:
        raise RuntimeError(
            f"কমপক্ষে {ATR_LENGTH + 2}টি candle দরকার, "
            f"পাওয়া গেছে {len(candles)}টি"
        )

    candle_index = len(candles) - 2
    candle = candles[candle_index]

    candle_id = str(candle["time"])

    candle_time_utc = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    )

    candle_time_ist = candle_time_utc.astimezone(IST)

    candle_time_text = candle_time_ist.strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )

    # ATR(14)
    atr_value = calculate_atr(candles, candle_index)

    if atr_value is None:
        raise RuntimeError(
            "ATR(14) হিসাব করা যায়নি"
        )

    body = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range <= 0:
        print("Candle range শূন্য। কোনো report পাঠানো হবে না।")
        return

    body_percent = (body / candle_range) * 100
    atr_required_body = ATR_MULTIPLIER * atr_value

    # দুইটি condition
    condition_1 = body >= atr_required_body
    condition_2 = body_percent >= MIN_BODY_PERCENT

    all_conditions_pass = condition_1 and condition_2

    if candle["close"] > candle["open"]:
        direction = "BUY"
    elif candle["close"] < candle["open"]:
        direction = "SELL"
    else:
        direction = "DOJI"

    state = load_state()

    # একই closed candle-এর report একবারই যাবে
    if state.get("last_report_candle") == candle_id:
        print("এই candle-এর report আগেই Telegram-এ পাঠানো হয়েছে।")
        return

    condition_1_text = "PASS ✅" if condition_1 else "FAIL ❌"
    condition_2_text = "PASS ✅" if condition_2 else "FAIL ❌"

    if all_conditions_pass:
        final_result = f"{direction} SIGNAL ✅"
    else:
        final_result = "NO SIGNAL ❌"

    message = f"""📊 CLOSED CANDLE REPORT

Pair: {PAIR}
Timeframe: {INTERVAL}
Candle close: {candle_time_text}

Direction: {direction}
Final result: {final_result}

OHLC:
Open: {format_number(candle["open"])}
High: {format_number(candle["high"])}
Low: {format_number(candle["low"])}
Close: {format_number(candle["close"])}

Candle values:
Body: {format_number(body)}
High - Low: {format_number(candle_range)}
Body/Range: {body_percent:.2f}%

ATR values:
ATR({ATR_LENGTH}): {format_number(atr_value)}
1.2 × ATR: {format_number(atr_required_body)}

Condition 1:
Body >= 1.2 × ATR(14)
Body: {format_number(body)}
Required: {format_number(atr_required_body)}
Result: {condition_1_text}

Condition 2:
Body / (High - Low) >= 60%
Actual: {body_percent:.2f}%
Required: {MIN_BODY_PERCENT:.2f}%
Result: {condition_2_text}
"""

    send_telegram(message)

    state["last_report_candle"] = candle_id
    state["last_checked_candle"] = candle_id
    state["last_condition_1"] = condition_1
    state["last_condition_2"] = condition_2

    save_state(state)

    print("Closed candle report Telegram-এ পাঠানো হয়েছে।")
    print(f"Condition 1: {condition_1_text}")
    print(f"Condition 2: {condition_2_text}")
    print(f"Final result: {final_result}")


if __name__ == "__main__":
    main()

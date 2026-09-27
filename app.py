# adyene-hitter — hosted Adyen checkout engine
from flask import Flask, request, jsonify
import asyncio
import re

from adyen_hitter import AdyenHitter

app = Flask(__name__)

CARD_RE = re.compile(r"^\s*(\d{13,19})\s*\|\s*(\d{1,2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3,4})\s*$")


def parse_card(s):
    m = CARD_RE.match(s or "")
    if not m:
        return None
    num, month, year, cvv = m.groups()
    return {"card": num, "month": month.zfill(2), "year": year, "cvv": cvv}


def parse_proxy(raw):
    """Proxy string → hitter proxy_data dict. Supports ip:port, user:pass@host:port,
    and scheme prefixes (http/https/socks4/socks5)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    s = raw
    scheme = None
    if "://" in s:
        scheme, _, s = s.partition("://")
    user = pwd = None
    if "@" in s:
        auth, _, s = s.rpartition("@")
        if ":" in auth:
            user, _, pwd = auth.partition(":")
        else:
            user = auth
    server = s
    if scheme:
        server = f"{scheme}://{server}"
    d = {"server": server, "raw": raw}
    if user:
        d["username"] = user
    if pwd:
        d["password"] = pwd
    return d


def _run(coro, timeout=90):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


async def _hit_one(url, card, proxy, ccn):
    hitter = AdyenHitter(url, proxy_data=proxy)
    if ccn:
        return await hitter.hit_ccn(card, 1, 0)
    return await hitter.hit(card, 1, 0)


async def _check(url, cards, proxy, ccn):
    hitter = AdyenHitter(url, proxy_data=proxy)
    await hitter.open_session()
    try:
        out = []
        for i, c in enumerate(cards):
            r = await (hitter.hit_ccn(c, i + 1, 0) if ccn else hitter.hit(c, i + 1, 0))
            out.append(r)
        return out
    finally:
        await hitter.close_session()


@app.route("/hit", methods=["POST"])
def hit():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    card_str = data.get("card") or ""
    ccn = bool(data.get("ccn", False))

    if not url:
        return jsonify({"error": "Missing 'url'"}), 400
    card = parse_card(card_str)
    if not card:
        return jsonify({"error": "Invalid card", "message": "Expected CC|MM|YY|CVV or CC|MM|YYYY|CVV"}), 400

    proxy = parse_proxy(data.get("proxy"))
    try:
        result = _run(_hit_one(url, card, proxy, ccn))
    except asyncio.TimeoutError:
        return jsonify({"error": "Checkout timed out"}), 504
    except Exception as e:
        return jsonify({"error": "Engine error", "message": str(e)[:300]}), 500

    return jsonify({"success": True, "result": result}), 200


@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    cards_raw = data.get("cards") or []
    ccn = bool(data.get("ccn", False))

    if not url:
        return jsonify({"error": "Missing 'url'"}), 400
    if not isinstance(cards_raw, list) or not cards_raw:
        return jsonify({"error": "Missing 'cards' array"}), 400

    cards = []
    for c in cards_raw:
        pc = parse_card(c)
        if not pc:
            return jsonify({"error": "Invalid card in list", "message": f"Bad format: {c}", "expected": "CC|MM|YY|CVV"}), 400
        cards.append(pc)

    proxy = parse_proxy(data.get("proxy"))
    try:
        results = _run(_check(url, cards, proxy, ccn))
    except asyncio.TimeoutError:
        return jsonify({"error": "Checkout timed out"}), 504
    except Exception as e:
        return jsonify({"error": "Engine error", "message": str(e)[:300]}), 500

    return jsonify({"success": True, "results": results}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "Adyen Hitter Engine", "engine": "adyen_hitter"}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Adyen Hitter",
        "endpoints": {
            "/hit": "POST {url, card, proxy?, ccn?} — full checkout flow on one card",
            "/check": "POST {url, cards[], proxy?, ccn?} — batch checkout flow",
            "/health": "health check",
        },
    }), 200


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)

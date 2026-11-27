"""Provider adapters for internal workspaces."""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import requests

TEBAR_PLATFORMS = {"facebook", "instagram", "threads", "linkedin", "x"}
TEBAR_BASE = "https://api.tebar.app/v1"


def config(provider, wid):
    # Read only the requested workspace entry.
    value = os.getenv(f"TAYSRIUL_{provider}") or "{}"
    try:
        settings = json.loads(value)
    except ValueError:
        raise RuntimeError(f"Konfigurasi {provider} workspace tidak valid.") from None
    if not isinstance(settings, dict):
        raise RuntimeError(f"Konfigurasi {provider} workspace tidak valid.")
    settings = settings.get(str(wid), {})
    if not isinstance(settings, dict):
        raise RuntimeError(f"Konfigurasi {provider} workspace tidak valid.")
    return settings


def tebar_target(settings, account):
    accounts = settings.get("accounts", {})
    if not isinstance(accounts, dict):
        raise RuntimeError("Pemetaan akun Tebar tidak valid.")
    remote = accounts.get(f"{account['platform']}:{account['external_id']}")
    if remote is None:
        return None
    if account["platform"] not in TEBAR_PLATFORMS or not valid_id(remote):
        raise ValueError("Pemetaan akun atau platform Tebar tidak didukung.")
    if not isinstance(settings.get("token"), str) or not settings["token"]:
        raise ValueError("Token Tebar workspace belum disiapkan.")
    if list(accounts.values()).count(remote) > 1:
        raise ValueError("Satu akun Tebar hanya boleh dipetakan ke satu akun lokal.")
    return remote


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def provider_request(method, url, token, provider, headers=None, **kwargs):
    try:
        response = requests.request(method, url, headers={
            "Authorization": "Bearer " + token, **(headers or {})
        }, timeout=(5, 40), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise RuntimeError(f"Respons {provider} belum terkonfirmasi.") from None
    if response.status_code in {400, 401, 403, 404, 413, 415, 422, 429}:
        raise ValueError(f"{provider} menolak permintaan (HTTP {response.status_code}).")
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Respons {provider} belum terkonfirmasi (HTTP {response.status_code}).")
    try:
        result = response.json()
    except ValueError:
        result = None
    if not isinstance(result, dict):
        raise RuntimeError(f"Respons {provider} tidak dikenali.")
    return result


def create_tebar(settings, target, key, body, media_url):
    payload = {"content": body, "targets": [{"account_id": target}]}
    if media_url:
        payload["media_urls"] = [media_url]
    data = provider_request("POST", TEBAR_BASE + "/posts", settings["token"], "Tebar",
                            headers={"Idempotency-Key": key}, json=payload)
    if not valid_id(data.get("id")):
        raise RuntimeError("ID kiriman Tebar belum terkonfirmasi.")
    return data["id"]


def tebar_status(settings, remote_id, target):
    data = provider_request("GET", TEBAR_BASE + "/posts/" + quote(remote_id, safe=""),
                            settings["token"], "Tebar")
    row = next((row for row in data["targets"] if row["account_id"] == target), None)
    if row is None:
        raise RuntimeError("Tujuan kiriman tidak ditemukan di Tebar.")
    if row["status"] == "published":
        link = row.get("permalink")
        return "Terbit", link if isinstance(link, str) and urlsplit(link).scheme == "https" else None, None
    if row["status"] in {"failed", "canceled", "cancelled"}:
        return "Periksa channel", None, "Tebar melaporkan kiriman gagal atau dibatalkan. Periksa riwayat Tebar."
    return "Diproses platform", None, None


def valid_signature(raw, signature, secret):
    if not isinstance(secret, str) or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def balas_account(settings):
    workspace = settings.get("workspace")
    account = settings.get("phone_number_id")
    if (isinstance(workspace, str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", workspace)
            and isinstance(account, str) and re.fullmatch(r"[0-9]{5,30}", account)):
        return workspace, account
    raise ValueError("Workspace atau nomor WhatsApp BalasChat belum dikonfigurasi.")


def waba_message(payload):
    contact, message = payload["contact"], payload["message"]
    phone = contact["phone"]
    if not isinstance(phone, str) or not re.fullmatch(r"[1-9][0-9]{6,14}", phone):
        raise ValueError("Nomor pelanggan tidak valid.")
    mid, tid = str(message["id"]), str(payload["conversation_id"])
    if not mid.isdecimal() or not tid.isdecimal() or max(len(mid), len(tid)) > 30:
        raise ValueError("ID pesan atau percakapan tidak valid.")
    when = datetime.fromisoformat(message["created_at"])
    if when.utcoffset() is None or when > datetime.now(timezone.utc):
        raise ValueError("Timestamp pesan tidak valid.")
    attachments = []
    for attachment in message.get("attachments") or []:
        if isinstance(attachment, str):
            attachments.append({"file_url": attachment})
        elif isinstance(attachment, dict):
            attachments.append({"file_url": str(attachment.get("url") or ""), "name": str(attachment.get("name") or "Lampiran")})
    name = str(contact.get("name") or phone)[:180]
    return {"id": tid, "participants": {"data": [{"id": phone, "name": name}]},
            "messages": {"data": [{"id": mid, "from": {"id": phone}, "created_time": when.isoformat(),
                                   "message": str(message.get("text") or ""), "attachments": {"data": attachments}}]}}


def send_waba(settings, local_identity, phone, body):
    workspace, account = balas_account(settings)
    token = settings.get("token")
    if not isinstance(token, str) or not token or local_identity != f"{workspace}:{account}":
        raise ValueError("Integrasi BalasChat akun ini tidak aktif.")
    result = provider_request("POST", f"https://{workspace}.balaschat.my.id/api/v1/messages", token, "BalasChat",
                              json={"channel": "waba", "from": account, "to": phone, "text": body})
    data = result.get("data")
    message_id = result.get("message_id") or (data.get("message_id") if isinstance(data, dict) else None)
    if result.get("status") is not True or not str(message_id).isdecimal():
        raise RuntimeError("ID balasan BalasChat belum terkonfirmasi.")
    return {"message_id": str(message_id)}


def starsender_message(payload):
    if payload.get("is_group") or payload.get("is_me") or payload.get("chat_type") == "group":
        return None
    sender = payload.get("from")
    if isinstance(sender, dict):
        sender = sender.get("number") or sender.get("phone") or sender.get("id")
    sender = str(sender or "").strip()
    if "@" in sender and not sender.endswith(("@s.whatsapp.net", "@c.us")):
        return None
    phone = re.sub(r"[ ()-]", "", sender.split("@", 1)[0]).removeprefix("+")
    if phone.startswith("0"):
        phone = "62" + phone[1:]
    if not re.fullmatch(r"[1-9][0-9]{6,14}", phone):
        raise ValueError("Nomor pengirim tidak dikenali.")
    body = payload.get("message")
    if isinstance(body, dict):
        body = body.get("text") or body.get("body") or body.get("conversation")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("Isi pesan teks tidak ditemukan.")
    stamp_raw = str(payload.get("timestamp") or "").strip()
    try:
        if re.fullmatch(r"[0-9]+(?:[.][0-9]+)?", stamp_raw):
            epoch = float(stamp_raw)
            when = datetime.fromtimestamp(epoch / 1000 if epoch >= 100_000_000_000 else epoch, timezone.utc)
        else:
            when = datetime.fromisoformat(stamp_raw)
            if when.utcoffset() is None:
                from zoneinfo import ZoneInfo
                when = when.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        stamp = when.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        stamp = None  # desk_messages uses the database receipt time when absent
    fingerprint = hashlib.sha256(json.dumps([phone, stamp or stamp_raw, body], ensure_ascii=False).encode()).hexdigest()
    mid = str(payload.get("message_id") or (fingerprint if stamp_raw else os.urandom(24).hex()))
    if len(mid) > 256:
        raise ValueError("ID pesan StarSender tidak valid.")
    return {"id": phone, "participants": {"data": [{"id": phone, "name": str(payload.get("push_name") or phone)[:180]}]},
            "messages": {"data": [{"id": mid, "from": {"id": phone}, "created_time": stamp, "message": body}]}}


def send_starsender(settings, local_identity, phone, body):
    token = settings.get("token")
    if not isinstance(token, str) or not token or settings.get("device_id") != local_identity:
        raise ValueError("Perangkat StarSender ini tidak aktif.")
    result = provider_request("POST", "https://api.starsender.online/api/send", token, "StarSender",
                              headers={"Authorization": token},
                              json={"messageType": "text", "to": phone, "body": body})
    if result.get("success") is not True:
        raise RuntimeError("Pengiriman StarSender belum terkonfirmasi.")

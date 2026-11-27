import json
import re

import requests


def discord_url(value):
    match = re.fullmatch(r"https://discord\.com/api/(?:v10/)?webhooks/(\d{1,19})/([A-Za-z0-9_-]{20,})", value)
    if not match or int(match[1]) >= 2**63:
        raise ValueError("Tempel URL webhook dari pengaturan integrasi Discord.")
    return f"https://discord.com/api/v10/webhooks/{match[1]}/{match[2]}"


def discord_request(url, *, payload=None, photo=None):
    options = dict(timeout=(5, 30), allow_redirects=False)
    try:
        if payload is None:
            response = requests.get(url, **options)
        else:
            if photo:
                ext = "mp4" if photo[4:8] == b"ftyp" else ("png" if photo.startswith(b"\x89PNG") else "jpg")
                options.update(data={"payload_json": json.dumps(payload)},
                               files={"files[0]": (f"foto.{ext}", photo)})
            else:
                options["json"] = payload
            response = requests.post(url, params={"wait": "true"}, **options)
        if 400 <= response.status_code < 500:
            raise ValueError(f"Discord menolak permintaan (HTTP {response.status_code}).")
        if response.status_code != 200:
            raise RuntimeError("Respons Discord belum terkonfirmasi.")
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("Respons Discord tidak terbaca.") from None
    except requests.RequestException:
        raise RuntimeError("Koneksi Discord belum terkonfirmasi.") from None

import base64
import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import requests


@dataclass(frozen=True)
class Provider:
    label: str
    target: str
    authorize: str
    token: str
    scope: str
    client_field: str = "client_id"
    basic_auth: bool = False
    pkce: bool = False


PROVIDERS = {
    "instagram": Provider("Instagram", "Business atau Creator yang tertaut ke Halaman Facebook",
                          "https://www.facebook.com/v25.0/dialog/oauth",
                          "https://graph.facebook.com/v25.0/oauth/access_token",
                          "pages_show_list,pages_read_engagement,instagram_basic,business_management"),
    "threads": Provider("Threads", "Profil", "https://threads.com/oauth/authorize",
                        "https://graph.threads.net/oauth/access_token", "threads_basic"),
    "facebook": Provider("Facebook", "Halaman", "https://www.facebook.com/v25.0/dialog/oauth",
                         "https://graph.facebook.com/v25.0/oauth/access_token",
                         "pages_show_list,pages_read_engagement,business_management"),
    "tiktok": Provider("TikTok", "Profil", "https://www.tiktok.com/v2/auth/authorize/",
                       "https://open.tiktokapis.com/v2/oauth/token/", "user.info.basic",
                       client_field="client_key"),
    "linkedin": Provider("LinkedIn", "Profil", "https://www.linkedin.com/oauth/v2/authorization",
                         "https://www.linkedin.com/oauth/v2/accessToken", "openid profile"),
    "youtube": Provider("YouTube", "Channel", "https://accounts.google.com/o/oauth2/v2/auth",
                         "https://oauth2.googleapis.com/token",
                         "https://www.googleapis.com/auth/youtube.readonly", pkce=True),
    "x": Provider("X", "Profil", "https://x.com/i/oauth2/authorize",
                  "https://api.x.com/2/oauth2/token", "users.read tweet.read",
                  basic_auth=True, pkce=True),
    "pinterest": Provider("Pinterest", "Profil", "https://www.pinterest.com/oauth/",
                           "https://api.pinterest.com/v5/oauth/token",
                           "user_accounts:read", basic_auth=True),
}


def settings(key):
    origin = os.getenv("SOCIAL_ORIGIN", "").strip().rstrip("/")
    try:
        parts = urlsplit(origin)
    except ValueError:
        return None
    client = os.getenv(f"{key.upper()}_CLIENT_ID", "").strip()
    secret = os.getenv(f"{key.upper()}_CLIENT_SECRET", "").strip()
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.path or parts.query or parts.fragment or not client or not secret):
        return None
    return client, secret, f"{origin}/akun/oauth/{key}/callback"


def authorization_url(key, config, state, verifier):
    provider = PROVIDERS[key]
    client, _, callback = config
    params = {provider.client_field: client, "redirect_uri": callback, "scope": provider.scope,
              "response_type": "code", "state": state}
    if provider.pkce:
        params["code_challenge"] = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params["code_challenge_method"] = "S256"
    if key == "youtube":
        params["prompt"] = "select_account"
    return f"{provider.authorize}?{urlencode(params)}"


def api(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(5, 15), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Platform menolak permintaan OAuth (HTTP {response.status_code}).")
        payload = response.json()
    except requests.RequestException:
        raise ValueError("Respons platform tidak dapat dibaca. Coba sambungkan ulang.") from None
    if not isinstance(payload, dict):
        raise ValueError("Format respons platform tidak dikenali.")
    return payload


def exchange(key, config, code, verifier):
    provider = PROVIDERS[key]
    client, secret, callback = config
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": callback}
    options = {}
    if provider.basic_auth:
        options["auth"] = (client, secret)
        if key == "x":
            data["client_id"] = client
    else:
        data.update({provider.client_field: client, "client_secret": secret})
    if provider.pkce:
        data["code_verifier"] = verifier
    if key in {"instagram", "facebook"}:
        data = api("GET", provider.token, params=data)
    else:
        data = api("POST", provider.token, data=data, **options)
    if not isinstance(data.get("access_token"), str) or not data["access_token"]:
        raise ValueError("Platform tidak memberikan token akses.")
    if key in {"facebook", "instagram", "threads"}:
        threads = key == "threads"
        long_token_url = "https://graph.threads.net/access_token" if threads else provider.token
        params = {"client_secret": secret}
        if threads:
            params.update(grant_type="th_exchange_token", access_token=data["access_token"])
        else:
            params.update(grant_type="fb_exchange_token", client_id=client,
                          fb_exchange_token=data["access_token"])
        data = api("GET", long_token_url, params=params)
        if not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise ValueError("Platform tidak memberikan token jangka panjang.")
    return data


def accounts(key, token):
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    def get(url, **params):
        return api("GET", url, headers=headers, params=params)

    if key in {"facebook", "instagram"}:
        fields = "id,name,access_token"
        if key == "instagram":
            fields += ",instagram_business_account{id,username}"
        params = {"fields": fields, "limit": 100}
        rows = []
        seen_cursors = set()
        while True:
            page = get("https://graph.facebook.com/v25.0/me/accounts", **params)
            for item in page.get("data", []):
                if not item.get("access_token"):
                    continue
                if key == "facebook":
                    rows.append((item.get("id"), item.get("name"), {"access_token": item["access_token"]}))
                elif instagram := item.get("instagram_business_account"):
                    rows.append((instagram.get("id"), instagram.get("username"),
                                 {"access_token": item["access_token"]}))
            paging = page.get("paging", {})
            cursor = paging.get("cursors", {}).get("after")
            if not paging.get("next"):
                return rows
            if not cursor or cursor in seen_cursors:
                raise ValueError("Daftar akun Meta tidak dapat dimuat seluruhnya.")
            seen_cursors.add(cursor)
            params["after"] = cursor

    if key == "youtube":
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        rows = []
        seen_pages = set()
        while True:
            page = get("https://www.googleapis.com/youtube/v3/channels", **params)
            rows.extend((row.get("id"), row.get("snippet", {}).get("title"), token)
                        for row in page.get("items", []))
            cursor = page.get("nextPageToken")
            if not cursor:
                return rows
            if cursor in seen_pages:
                raise ValueError("Daftar channel YouTube tidak dapat dimuat seluruhnya.")
            seen_pages.add(cursor)
            params["pageToken"] = cursor
    if key == "threads":
        row = get("https://graph.threads.net/v1.0/me", fields="id,username")
        return [(row.get("id"), row.get("username"), token)]
    if key == "tiktok":
        row = get("https://open.tiktokapis.com/v2/user/info/",
                  fields="open_id,display_name").get("data", {}).get("user", {})
        return [(row.get("open_id"), row.get("display_name"), token)]
    if key == "linkedin":
        row = get("https://api.linkedin.com/v2/userinfo")
        return [(row.get("sub"), row.get("name"), token)]
    if key == "x":
        row = get("https://api.x.com/2/users/me").get("data", {})
        return [(row.get("id"), row.get("username"), token)]
    row = get("https://api.pinterest.com/v5/user_account")
    return [(row.get("id") or row.get("username"), row.get("username"), token)]

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
                          "pages_show_list,pages_read_engagement,instagram_basic,business_management,instagram_content_publish"),
    "threads": Provider("Threads", "Profil", "https://threads.com/oauth/authorize",
                        "https://graph.threads.net/oauth/access_token", "threads_basic,threads_content_publish"),
    "facebook": Provider("Facebook", "Halaman", "https://www.facebook.com/v25.0/dialog/oauth",
                         "https://graph.facebook.com/v25.0/oauth/access_token",
                         "pages_show_list,pages_read_engagement,business_management,pages_manage_posts"),
    "tiktok": Provider("TikTok", "Profil", "https://www.tiktok.com/v2/auth/authorize/",
                       "https://open.tiktokapis.com/v2/oauth/token/", "user.info.basic,video.upload",
                       client_field="client_key"),
    "linkedin": Provider("LinkedIn", "Profil", "https://www.linkedin.com/oauth/v2/authorization",
                         "https://www.linkedin.com/oauth/v2/accessToken", "openid profile w_member_social"),
    "youtube": Provider("YouTube", "Channel", "https://accounts.google.com/o/oauth2/v2/auth",
                         "https://oauth2.googleapis.com/token",
                         "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload", pkce=True),
    "x": Provider("X", "Profil", "https://x.com/i/oauth2/authorize",
                  "https://api.x.com/2/oauth2/token", "users.read tweet.read tweet.write media.write offline.access",
                  basic_auth=True, pkce=True),
    "pinterest": Provider("Pinterest", "Profil", "https://www.pinterest.com/oauth/",
                           "https://api.pinterest.com/v5/oauth/token",
                           "user_accounts:read,boards:read,pins:read,pins:write", basic_auth=True),
}

def instagram_direct():
    return os.getenv("INSTAGRAM_LOGIN_MODE","facebook").strip().lower()=="direct"


def instagram_unified():
    return os.getenv("INSTAGRAM_LOGIN_MODE","facebook").strip().lower()=="unified"


def _base_provider(key):
    if key=="instagram" and instagram_unified():
        return Provider("Instagram","Akun Professional (Unified Login)",
                        "https://www.facebook.com/v25.0/dialog/oauth",
                        "https://graph.facebook.com/v25.0/oauth/access_token",
                        "instagram_basic,instagram_content_publish")
    if key=="instagram" and instagram_direct():
        return Provider("Instagram","Akun Professional (Business/Creator)",
                        "https://www.instagram.com/oauth/authorize",
                        "https://api.instagram.com/oauth/access_token",
                        "instagram_business_basic,instagram_business_content_publish")
    if key == "youtube" and os.getenv("YOUTUBE_COMMENTS_ENABLED") == "1":
        from dataclasses import replace
        return replace(PROVIDERS[key], scope=PROVIDERS[key].scope + " https://www.googleapis.com/auth/youtube.force-ssl")
    if key == "facebook" and os.getenv("FACEBOOK_MESSENGER_ENABLED") == "1":
        from dataclasses import replace
        return replace(PROVIDERS[key], scope=PROVIDERS[key].scope + ",pages_messaging")
    return PROVIDERS[key]


def provider_for(key):
    from dataclasses import replace
    provider = _base_provider(key)
    if key=="threads" and os.getenv("THREADS_FEED_ENABLED")=="1":
        provider=replace(provider,scope=provider.scope+",threads_keyword_search")
    if key=="threads" and os.getenv("THREADS_COMMENTS_ENABLED")=="1":
        return replace(provider,scope=provider.scope+",threads_read_replies,threads_manage_replies")
    if key=="instagram" and os.getenv("INSTAGRAM_COMMENTS_ENABLED")=="1":
        extra="instagram_business_manage_comments" if instagram_direct() else "instagram_manage_comments"
        return replace(provider,scope=provider.scope+","+extra)
    return provider


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
    if key=="instagram" and instagram_unified():
        config_id=os.getenv("INSTAGRAM_CONFIG_ID","").strip()
        if not config_id.isascii() or not config_id.isdecimal():
            return None
    return client, secret, f"{origin}/akun/oauth/{key}/callback"


def authorization_url(key, config, state, verifier):
    provider = provider_for(key)
    client, _, callback = config
    params = {provider.client_field: client, "redirect_uri": callback, "scope": provider.scope,
              "response_type": "code", "state": state}
    if key=="instagram" and instagram_unified():
        # Permissions and asset selection are defined by the Meta configuration.
        params.pop("scope",None)
        params.update(config_id=os.environ["INSTAGRAM_CONFIG_ID"].strip(),
                      override_default_response_type="true")
    if provider.pkce:
        params["code_challenge"] = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params["code_challenge_method"] = "S256"
    if key == "youtube":
        params.update(prompt="consent select_account", access_type="offline")
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
    provider = provider_for(key)
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
    if key in {"instagram", "facebook"} and not (key=="instagram" and instagram_direct()):
        data = api("GET", provider.token, params=data)
    else:
        data = api("POST", provider.token, data=data, **options)
    if not isinstance(data.get("access_token"), str) or not data["access_token"]:
        raise ValueError("Platform tidak memberikan token akses.")
    if key=="instagram" and instagram_unified():
        # Business Login can return a system-user token; do not exchange it as
        # a short-lived Facebook user token.
        data["instagram_mode"]="unified"
        return data
    if key=="instagram" and instagram_direct():
        short=data
        data=api("GET","https://graph.instagram.com/access_token",
                 params={"grant_type":"ig_exchange_token","client_secret":secret,"access_token":short["access_token"]})
        if short.get("permissions"): data["permissions"]=short["permissions"]
        data["instagram_mode"]="direct"
        if not data.get("access_token"): raise ValueError("Instagram tidak memberikan token jangka panjang.")
        return data
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

    if key=="instagram" and token.get("instagram_mode")=="unified":
        meta=unified_token_info(token)
        targets=set()
        for grant in meta.get("granular_scopes",[]):
            if grant.get("scope")=="instagram_basic":
                targets.update(str(i) for i in grant.get("target_ids",[]) if str(i).isascii() and str(i).isdecimal())
        publish_targets=set()
        for grant in meta.get("granular_scopes",[]):
            if grant.get("scope")=="instagram_content_publish":
                publish_targets.update(str(i) for i in grant.get("target_ids",[]) if str(i).isascii() and str(i).isdecimal())
        if not targets:
            # If Meta does not report selected asset IDs, enumerate assigned IG accounts.
            cursor=None
            seen=set()
            while True:
                params={"fields":"id,username","limit":100}
                if cursor: params["after"]=cursor
                result=get("https://graph.facebook.com/v25.0/me/assigned_instagram_accounts",**params)
                targets.update(str(row["id"]) for row in result.get("data",[]) if str(row.get("id","")).isascii() and str(row.get("id","")).isdecimal())
                paging=result.get("paging",{})
                if not paging.get("next"): break
                cursor=paging.get("cursors",{}).get("after")
                if not cursor or cursor in seen: raise ValueError("Daftar Instagram tidak lengkap.")
                seen.add(cursor)
        rows=[]
        for target in sorted(targets):
            row=get(f"https://graph.facebook.com/v25.0/{target}",fields="id,username")
            if str(row.get("id")) != target or not row.get("username"):
                continue
            creds={**token,"can_publish":"instagram_content_publish" in meta.get("scopes",[]) and (not publish_targets or target in publish_targets)}
            expires=meta.get("expires_at")
            if isinstance(expires,int) and expires>0:
                import time
                creds["expires_in"]=max(1,expires-int(time.time()))
            rows.append((target,row["username"],creds))
        return rows
    if key=="instagram" and token.get("instagram_mode")=="direct":
        row=get("https://graph.instagram.com/v25.0/me",fields="user_id,username")
        return [(row.get("user_id") or row.get("id"),row.get("username"),token)]
    if key in {"facebook", "instagram"}:
        fields = "id,name,access_token,tasks"
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
                    rows.append((item.get("id"), item.get("name"), {"access_token": item["access_token"], "can_publish": "CREATE_CONTENT" in item.get("tasks", []) or "MANAGE" in item.get("tasks", [])}))
                elif instagram := item.get("instagram_business_account"):
                    rows.append((instagram.get("id"), instagram.get("username"),
                                 {"access_token": item["access_token"], "can_publish": "CREATE_CONTENT" in item.get("tasks", []) or "MANAGE" in item.get("tasks", [])}))
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
    # Pins must target a specific board; expose each board as a separate destination.
    rows, seen = [], set()
    params = {"page_size": 100}
    while True:
        page = get("https://api.pinterest.com/v5/boards", **params)
        rows.extend((row.get("id"), row.get("name"), token) for row in page.get("items", []))
        cursor = page.get("bookmark")
        if not cursor: return rows
        if cursor in seen: raise ValueError("Daftar board Pinterest tidak lengkap.")
        seen.add(cursor)
        params["bookmark"] = cursor

def unified_token_info(token):
    config=settings("instagram")
    if not config: raise ValueError("Konfigurasi Instagram Unified Login belum lengkap.")
    client,secret,_=config
    result=api("GET","https://graph.facebook.com/v25.0/debug_token",
               params={"input_token":token["access_token"]},
               headers={"Authorization":"Bearer "+client+"|"+secret}).get("data",{})
    if result.get("is_valid") is not True or str(result.get("app_id"))!=client:
        raise ValueError("Token Instagram tidak valid untuk aplikasi ini.")
    return result


def granted_scopes(key, token):
    if key=="instagram" and token.get("instagram_mode")=="unified":
        return set(unified_token_info(token).get("scopes",[]))
    if key=="instagram" and token.get("instagram_mode")=="direct":
        value=token.get("permissions") or token.get("scope")
        if isinstance(value,str): return set(value.replace(","," ").split())
        if isinstance(value,list): return set(value)
        return set(provider_for(key).scope.split(","))
    if key in {"facebook", "instagram"}:
        result = api("GET", "https://graph.facebook.com/v25.0/me/permissions",
                     headers={"Authorization": "Bearer " + token["access_token"]})
        return {row["permission"] for row in result.get("data", []) if row.get("status") == "granted"}
    value = token.get("scope")
    if isinstance(value, str):
        return set(value.replace(",", " ").split())
    # Some OAuth providers omit scope if it matches the request.
    return set(provider_for(key).scope.replace(",", " ").split())


def refresh(key, credentials):
    config = settings(key)
    if not config or not credentials.get("refresh_token"):
        raise ValueError("Token kedaluwarsa; sambungkan ulang akun.")
    client, secret, _ = config
    provider = provider_for(key)
    data = {"grant_type": "refresh_token", "refresh_token": credentials["refresh_token"]}
    kwargs = {}
    if provider.basic_auth:
        kwargs["auth"] = (client, secret)
        if key == "x": data["client_id"] = client
    else:
        data.update({provider.client_field: client, "client_secret": secret})
    result = api("POST", provider.token, data=data, **kwargs)
    if not result.get("access_token"):
        raise ValueError("Pembaruan token gagal; sambungkan ulang akun.")
    return {**credentials, **{k: result[k] for k in ("access_token","refresh_token","expires_in","scope") if k in result}}

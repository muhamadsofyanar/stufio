"""Read account metrics and recent comments using official Graph endpoints."""
from social_oauth import api

COMMENT_FLAGS = {
    "facebook":"FACEBOOK_MESSENGER_ENABLED",
    "youtube":"YOUTUBE_COMMENTS_ENABLED",
    "instagram":"INSTAGRAM_COMMENTS_ENABLED",
    "threads":"THREADS_COMMENTS_ENABLED",
}


def root(platform, credentials):
    if platform == "threads":
        return "https://graph.threads.net/v1.0"
    if platform == "instagram" and credentials.get("instagram_mode") == "direct":
        return "https://graph.instagram.com/v25.0"
    return "https://graph.facebook.com/v25.0"


def comments(platform, account, credentials, headers, observe=None):
    base = root(platform, credentials)
    posts_edge, replies_edge = ("threads","replies") if platform=="threads" else ("media","comments")
    recent = api("GET", f"{base}/{account}/{posts_edge}", headers=headers, params={"fields":"id","limit":10})
    items = []
    for post in recent["data"]:
        parent = post["id"]
        replies = api("GET", f"{base}/{parent}/{replies_edge}", headers=headers,
                      params={"fields":"id,text,username,timestamp,from" if platform=="instagram" else "id,text,username,timestamp","limit":50})
        for reply in replies["data"]:
            if observe and reply.get("timestamp"):
                observe(reply)
            items.append((reply["id"], reply.get("username") or platform, reply.get("text") or "Lampiran", parent, reply["id"]))
    return items


def stats(platform, account, credentials, headers):
    fields = ("followers_count","media_count") if platform=="instagram" else ("followers_count","fan_count")
    values = api("GET", f"{root(platform,credentials)}/{account}", headers=headers, params={"fields":",".join(fields)})
    return [(field, field, str(values[field]), None, None) for field in fields if isinstance(values.get(field),int)]


def reply(platform, account, parent, body, credentials, headers):
    base = root(platform,credentials)
    if platform == "instagram":
        return api("POST",f"{base}/{parent}/replies",headers=headers,data={"message":body}).get("id")
    container = api("POST", f"{base}/{account}/threads", headers=headers, data={"media_type":"TEXT","text":body,"reply_to_id":parent})
    if not container.get("id"):
        return None
    return api("POST", f"{base}/{account}/threads_publish", headers=headers, data={"creation_id":container["id"]}).get("id")

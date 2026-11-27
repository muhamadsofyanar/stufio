"""Official API publishing adapters. Only confirmed API responses count as success."""
import base64
import json
import re
import time
import uuid
from urllib.parse import quote, urlsplit

import requests

# Explicit per-platform capabilities; do not offer media types without adapters.
CAPABILITIES = {
    "Telegram": ("text", "image", "video"),
    "Discord": ("text", "image", "video"),
    "facebook": ("text", "image", "video"),
    "instagram": ("image", "video"),
    "threads": ("text", "image", "video"),
    "youtube": ("video",),
    "tiktok": ("video",),
    "linkedin": ("text", "image", "video"),
    "x": ("text", "image", "video"),
    "pinterest": ("image", "video"),
}
LIMITS = {"Discord": 2000, "instagram": 2200, "threads": 500,
          "linkedin": 3000, "x": 280, "pinterest": 500}
LABELS = {"facebook": "Facebook", "instagram": "Instagram", "threads": "Threads",
          "youtube": "YouTube", "tiktok": "TikTok (draf)", "linkedin": "LinkedIn",
          "x": "X", "pinterest": "Pinterest (board)"}
SCOPES = {
    "facebook": "pages_manage_posts", "instagram": "instagram_content_publish",
    "threads": "threads_content_publish", "youtube": "https://www.googleapis.com/auth/youtube.upload",
    "tiktok": "video.upload", "linkedin": "w_member_social", "x": "tweet.write",
    "pinterest": "pins:write",
}

def media_kind(data):
    if not data: return "text"
    if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")): return "image"
    if len(data) >= 12 and data[4:8] == b"ftyp": return "video"
    raise ValueError("Format media tidak didukung.")

def mime(data):
    return "video/mp4" if media_kind(data) == "video" else ("image/png" if data.startswith(b"\x89PNG") else "image/jpeg")

def validate(platform, body, media):
    kind = media_kind(media)
    if platform not in CAPABILITIES or kind not in CAPABILITIES[platform]:
        raise ValueError(f"{LABELS.get(platform,platform)} tidak mendukung jenis kiriman ini.")
    if platform == "instagram" and kind == "image" and mime(media) != "image/jpeg":
        raise ValueError("Instagram memerlukan foto JPEG.")
    if platform == "x" and kind == "image" and len(media)>5*1024**2:
        raise ValueError("Foto X maksimal 5 MB.")
    if platform == "Discord" and len(media or b"") > 8*1024**2:
        raise ValueError("Media Discord maksimal 8 MB pada konfigurasi ini.")
    limit = (1024 if media else 4096) if platform == "Telegram" else LIMITS.get(platform,4096)
    if len(body) > limit: raise ValueError(f"Teks {LABELS.get(platform,platform)} maksimal {limit} karakter.")
    if platform == "youtube" and not body.strip():
        raise ValueError("YouTube memerlukan judul pada baris pertama caption (maks. 100 karakter).")
    if platform == "youtube" and len(body.splitlines()[0].strip()) > 100:
        raise ValueError("Judul YouTube maksimal 100 karakter.")

def call(method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {}).copy()
    if token: headers["Authorization"] = "Bearer " + token
    try:
        response = requests.request(method, url, headers=headers, timeout=(10,180), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise RuntimeError("Koneksi API tidak terkonfirmasi; periksa platform sebelum mencoba ulang.") from None
    if response.status_code in (401,403):
        raise ValueError("API menolak izin atau token. Sambungkan ulang akun dan periksa permission.")
    if not 200 <= response.status_code < 300:
        if response.status_code >= 500 or response.status_code == 429:
            raise RuntimeError(f"API belum terkonfirmasi (HTTP {response.status_code}).")
        raise ValueError(f"API menolak kiriman (HTTP {response.status_code}). Periksa format, izin dan kuota.")
    return response

def payload(response):
    try: data = response.json()
    except ValueError: raise RuntimeError("Respons API tidak terbaca.") from None
    if not isinstance(data, dict): raise RuntimeError("Respons API tidak dikenali.")
    error = data.get("error")
    if error and (not isinstance(error,dict) or error.get("code") not in ("ok",)):
        raise ValueError("Platform menolak permintaan. Periksa akun, izin dan media.")
    return data

def require_id(data, name="id"):
    value = data.get(name)
    if not isinstance(value,(str,int)) or not str(value):
        raise RuntimeError("API tidak mengembalikan ID; periksa platform sebelum mencoba ulang.")
    return str(value)

def upload_url(url, domains):
    parts=urlsplit(url)
    if parts.scheme!="https" or parts.username or not parts.hostname or not any(parts.hostname==d or parts.hostname.endswith("."+d) for d in domains):
        raise ValueError("URL upload platform tidak valid.")
    return url

def publish(platform, external_id, credentials, body, media, public_url=None, cover_url=None, options=None):
    validate(platform,body,media)
    options=options or {}
    token=credentials["access_token"]
    ident=quote(str(external_id),safe="")
    kind=media_kind(media)
    if platform == "facebook":
        endpoint="feed" if kind=="text" else ("photos" if kind=="image" else "videos")
        data={"message":body} if kind!="video" else {"description":body}
        files={"source": ("media.mp4" if kind=="video" else "media",media,mime(media))} if media else None
        host="graph-video.facebook.com" if kind=="video" else "graph.facebook.com"
        result=payload(call("POST",f"https://{host}/v25.0/{ident}/{endpoint}",token,data=data,files=files))
        post_id=require_id(result,"post_id" if result.get("post_id") else "id")
        return ("Diproses platform" if kind=="video" else "Terbit", "https://www.facebook.com/"+quote(post_id,safe=""), None)
    if platform in {"instagram","threads"}:
        is_ig=platform=="instagram"
        root=("https://graph.instagram.com/v25.0" if credentials.get("instagram_mode")=="direct" else "https://graph.facebook.com/v25.0") if is_ig else "https://graph.threads.net/v1.0"
        endpoint="media" if is_ig else "threads"
        data={"caption" if is_ig else "text":body}
        if media:
            if not public_url: raise ValueError("Domain HTTPS publik diperlukan untuk media.")
            data["image_url" if kind=="image" else "video_url"]=public_url
        if is_ig and kind=="video": data["media_type"]="REELS"
        if not is_ig: data["media_type"]={"text":"TEXT","image":"IMAGE","video":"VIDEO"}[kind]
        container=require_id(payload(call("POST",f"{root}/{ident}/{endpoint}",token,data=data)))
        if is_ig or kind!="text":
            for _ in range(30):
                status=payload(call("GET",f"{root}/{quote(container,safe='')}",token,
                                    params={"fields":"status_code" if is_ig else "status"}))
                stage=status.get("status_code" if is_ig else "status")
                if stage=="FINISHED": break
                if stage in {"ERROR","EXPIRED"}: raise ValueError("Pemrosesan media ditolak platform.")
                time.sleep(5)
            else: raise RuntimeError("Container media belum siap; periksa platform.")
        post_id=require_id(payload(call("POST",f"{root}/{ident}/{endpoint}_publish",token,data={"creation_id":container})))
        return "Terbit",None,f"ID publikasi: {post_id}"
    if platform=="youtube":
        boundary="stufio_"+uuid.uuid4().hex
        metadata={"snippet":{"title":body.splitlines()[0].strip(),"description":"\n".join(body.splitlines()[1:]),"categoryId":"22"},
                  "status":{"privacyStatus":options.get("privacy","private"),"selfDeclaredMadeForKids":bool(options.get("kids",False))}}
        wire=(f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()+json.dumps(metadata).encode()+
              f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n".encode()+media+f"\r\n--{boundary}--\r\n".encode())
        result=payload(call("POST","https://www.googleapis.com/upload/youtube/v3/videos",token,
            params={"part":"snippet,status","uploadType":"multipart"},data=wire,
            headers={"Content-Type":f"multipart/related; boundary={boundary}"}))
        return "Diproses platform","https://www.youtube.com/watch?v="+quote(require_id(result),safe=""),"Upload diterima; periksa pemrosesan dan visibilitas aktual di YouTube Studio."
    if platform=="tiktok":
        result=payload(call("POST","https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",token,
            json={"source_info":{"source":"FILE_UPLOAD","video_size":len(media),"chunk_size":len(media),"total_chunk_count":1}}))
        info=result.get("data",{})
        pid=require_id(info,"publish_id")
        call("PUT",upload_url(info.get("upload_url",""),("tiktokapis.com",)),data=media,
             headers={"Content-Type":"video/mp4","Content-Range":f"bytes 0-{len(media)-1}/{len(media)}","Content-Length":str(len(media))})
        return "Draf platform",None,"Lanjutkan melalui notifikasi TikTok; ID upload: "+pid
    if platform=="linkedin":
        author=f"urn:li:person:{external_id}"
        headers={"Linkedin-Version":"202609","X-Restli-Protocol-Version":"2.0.0"}
        data={"author":author,"commentary":body,"visibility":"PUBLIC","distribution":{"feedDistribution":"MAIN_FEED","targetEntities":[],"thirdPartyDistributionChannels":[]},"lifecycleState":"PUBLISHED","isReshareDisabledByAuthor":False}
        if kind=="video":
            value=payload(call("POST","https://api.linkedin.com/rest/videos",token,headers=headers,params={"action":"initializeUpload"},
                json={"initializeUploadRequest":{"owner":author,"fileSizeBytes":len(media),"uploadCaptions":False,"uploadThumbnail":False}}))["value"]
            parts=[]
            for instruction in value["uploadInstructions"]:
                start,end=instruction["firstByte"],instruction["lastByte"]
                response=call("PUT",upload_url(instruction["uploadUrl"],("linkedin.com",)),data=media[start:end+1],
                              headers={"Content-Type":"application/octet-stream"})
                if not response.headers.get("ETag"): raise RuntimeError("Upload bagian video LinkedIn belum terkonfirmasi.")
                parts.append(response.headers["ETag"].strip('"'))
            call("POST","https://api.linkedin.com/rest/videos",token,headers=headers,params={"action":"finalizeUpload"},
                 json={"finalizeUploadRequest":{"video":value["video"],"uploadToken":value["uploadToken"],"uploadedPartIds":parts}})
            for _ in range(30):
                result=payload(call("GET","https://api.linkedin.com/rest/videos/"+quote(value["video"],safe=""),token,headers=headers))
                if result.get("status")=="AVAILABLE": break
                if result.get("status")=="PROCESSING_FAILED": raise ValueError("Video LinkedIn ditolak.")
                time.sleep(5)
            else: raise RuntimeError("Video LinkedIn masih diproses.")
            data["content"]={"media":{"id":value["video"],"title":body[:100] or "Video"}}
        elif media:
            value=payload(call("POST","https://api.linkedin.com/rest/images",token,headers=headers,params={"action":"initializeUpload"},json={"initializeUploadRequest":{"owner":author}}))["value"]
            call("PUT",upload_url(value["uploadUrl"],("linkedin.com",)),token,data=media,headers={"Content-Type":mime(media)})
            data["content"]={"media":{"id":value["image"]}}
        response=call("POST","https://api.linkedin.com/rest/posts",token,headers=headers,json=data)
        pid=response.headers.get("x-restli-id")
        if not pid: raise RuntimeError("ID posting LinkedIn belum terkonfirmasi.")
        return "Terbit","https://www.linkedin.com/feed/update/"+quote(pid,safe=":"),None
    if platform=="x":
        data={"text":body} if body else {}
        root="https://api.x.com/2/media/upload"
        if kind=="image":
            mid=require_id(payload(call("POST",root,token,json={"media":base64.b64encode(media).decode(),"media_category":"tweet_image"})).get("data",{}))
            data["media"]={"media_ids":[mid]}
        elif kind=="video":
            mid=require_id(payload(call("POST",root+"/initialize",token,json={"media_type":"video/mp4","total_bytes":len(media),"media_category":"tweet_video"})).get("data",{}))
            for ix,start in enumerate(range(0,len(media),4*1024**2)):
                call("POST",root+"/"+quote(mid,safe="")+"/append",token,data={"segment_index":ix},files={"media":("chunk.mp4",media[start:start+4*1024**2],"video/mp4")})
            info=payload(call("POST",root+"/"+quote(mid,safe="")+"/finalize",token)).get("data",{}).get("processing_info")
            for _ in range(30):
                if not info or info.get("state")=="succeeded": break
                if info.get("state")=="failed": raise ValueError("Video X ditolak.")
                time.sleep(max(1,min(10,int(info.get("check_after_secs",5)))))
                info=payload(call("GET",root,token,params={"command":"STATUS","media_id":mid})).get("data",{}).get("processing_info")
            else: raise RuntimeError("Video X masih diproses.")
            data["media"]={"media_ids":[mid]}
        result=payload(call("POST","https://api.x.com/2/tweets",token,json=data))
        return "Terbit","https://x.com/i/web/status/"+quote(require_id(result.get("data",{})),safe=""),None
    if platform=="pinterest":
        if kind=="video":
            if not cover_url: raise ValueError("Video Pinterest memerlukan foto cover.")
            info=payload(call("POST","https://api.pinterest.com/v5/media",token,json={"media_type":"video"}))
            mid=require_id(info,"media_id")
            call("POST",upload_url(info["upload_url"],("amazonaws.com","pinterest.com")),data=info["upload_parameters"],
                 files={"file":("video.mp4",media,"video/mp4")})
            for _ in range(30):
                status=payload(call("GET","https://api.pinterest.com/v5/media/"+quote(mid,safe=""),token)).get("status")
                if status=="succeeded": break
                if status=="failed": raise ValueError("Video Pinterest ditolak.")
                time.sleep(5)
            else: raise RuntimeError("Video Pinterest belum selesai diproses.")
            source={"source_type":"video_id","media_id":mid,"cover_image_url":cover_url}
        else:
            source={"source_type":"image_base64","content_type":mime(media),"data":base64.b64encode(media).decode()}
        result=payload(call("POST","https://api.pinterest.com/v5/pins",token,json={"board_id":external_id,
            "description":body,"media_source":source}))
        return "Terbit","https://www.pinterest.com/pin/"+quote(require_id(result),safe="")+"/",None
    raise ValueError("Konektor publikasi belum tersedia.")

import os
import re
from urllib.parse import urlsplit
import hmac
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from publishing import discord_request, discord_url
from flask import Response
import psycopg
import requests
from flask import Flask, abort, flash, redirect, render_template, request, session
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ["APP_KEY"]
app.config.update(MAX_CONTENT_LENGTH=9*1024**2, SESSION_COOKIE_SECURE=True,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
WIB = ZoneInfo("Asia/Jakarta")


def connect():
    return psycopg.connect("", row_factory=dict_row)


with connect() as db:
    db.execute("SELECT pg_advisory_xact_lock(782391)")
    db.execute("""CREATE EXTENSION IF NOT EXISTS pgcrypto;
    CREATE TABLE IF NOT EXISTS channels (
      id bigint PRIMARY KEY, title text NOT NULL, token bytea NOT NULL);
    CREATE TABLE IF NOT EXISTS posts (
      id bigserial PRIMARY KEY, channel bigint NOT NULL REFERENCES channels,
      body text NOT NULL, photo bytea, due timestamptz NOT NULL,
      state text NOT NULL DEFAULT 'Terjadwal', note text, link text);
    ALTER TABLE channels ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'Telegram';
    ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild text;
    CREATE TABLE IF NOT EXISTS assets(id bigserial PRIMARY KEY,name text NOT NULL,photo bytea NOT NULL);
    CREATE TABLE IF NOT EXISTS editorial(id bigserial PRIMARY KEY,body text NOT NULL,stage text NOT NULL,
                                         asset bigint REFERENCES assets);
    CREATE TABLE IF NOT EXISTS shortlinks(slug text PRIMARY KEY, destination text NOT NULL,
      title text NOT NULL, clicks bigint NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS worker_status(id integer PRIMARY KEY, seen timestamptz NOT NULL);
    CREATE TABLE IF NOT EXISTS submissions(nonce text PRIMARY KEY, created timestamptz DEFAULT now());""")


def telegram(token, method, data, files=None):
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                                 data=data, files=files, timeout=(5,30))
        result = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("Respons Telegram belum terkonfirmasi.") from None
    if not result.get("ok"):
        raise ValueError(str(result.get("description","Permintaan ditolak"))[:240])
    return result["result"]


@app.before_request
def protect():
    session.setdefault("csrf", secrets.token_urlsafe(24))
    if request.method == "POST" and not hmac.compare_digest(
            str(request.form.get("csrf","")).encode(), session["csrf"].encode()):
        abort(403)
    if request.endpoint in {"static","open_link"}:
        return
    if request.path != "/login" and not session.get("admin"):
        return redirect("/login")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if hmac.compare_digest(request.form["password"].encode(), os.environ["ADMIN_PASSWORD"].encode()):
            session.clear()
            session.update(admin=True, csrf=secrets.token_urlsafe(24))
            return redirect("/")
        time.sleep(1)
        flash("Kata sandi keliru.")
    return render_template("studio.html", page="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@app.route("/<any(akun,buat,kalender):page>")
def dashboard(page="ringkasan"):
    with connect() as db:
        channels = db.execute("SELECT id,title,platform FROM channels ORDER BY title").fetchall()
        draft = None
        media = []
        if page == "buat":
            media = media_list(db)
            if request.args.get("draft",type=int):
                draft=db.execute("SELECT * FROM editorial WHERE id=%s AND stage='Draf'",(request.args.get("draft",type=int),)).fetchone()
                if not draft:
                    abort(404)
        heartbeat = db.execute("SELECT seen > now()-interval '90 seconds' AS active FROM worker_status WHERE id=1").fetchone() if page=="ringkasan" else None
        totals = db.execute("""SELECT count(*) FILTER (WHERE state='Terjadwal') AS queued,
                            count(*) FILTER (WHERE state='Terbit') AS sent,
                            count(*) FILTER (WHERE state IN ('Gagal','Periksa channel')) AS issues
                            FROM posts""").fetchone()
        posts = db.execute("""SELECT p.id,body,due,state,note,link,title FROM posts p
                            JOIN channels c ON p.channel=c.id
                            ORDER BY (state='Terjadwal') DESC,
                            CASE WHEN state='Terjadwal' THEN due END ASC,due DESC LIMIT 200""").fetchall()
    for post in posts:
        post["local"] = post["due"].astimezone(WIB)
    if page=="kalender":
        posts.sort(key=lambda p:p["local"])
    return render_template("studio.html", page=page, channels=channels, posts=posts, totals=totals, draft=draft, media=media, heartbeat=heartbeat, nonce=secrets.token_urlsafe(18))


@app.post("/akun")
def account():
    token=request.form["token"].strip()
    target=request.form["target"].strip()
    if not token or not target:
        abort(400)
    try:
        bot=telegram(token,"getMe",{})
        chat=telegram(token,"getChat",{"chat_id":target})
        member=telegram(token,"getChatMember",{"chat_id":chat["id"],"user_id":bot["id"]})
        if chat["type"]!="channel" or not member.get("can_post_messages"):
            raise ValueError("Jadikan bot admin channel dan izinkan mengirim pesan.")
        with connect() as db:
            db.execute("""INSERT INTO channels(id,title,token) VALUES (%s,%s,pgp_sym_encrypt(%s,%s))
                       ON CONFLICT(id) DO UPDATE SET title=excluded.title, token=excluded.token""",
                       (chat["id"],chat["title"],token,app.secret_key))
        flash("Channel terhubung.")
    except (ValueError,RuntimeError) as err:
        flash(str(err))
    return redirect("/akun")


def read_due(value):
    return datetime.fromisoformat(value).replace(tzinfo=WIB) if value else datetime.now(WIB)


@app.route("/tautan",methods=["GET","POST"])
def links():
    if request.method=="POST":
        dest=request.form["destination"].strip()
        slug=request.form["slug"].strip() or secrets.token_urlsafe(6)
        parts=urlsplit(dest)
        if (parts.scheme not in {"https","http"} or not parts.hostname or parts.username
                or any(ord(c)<32 or c==chr(92) for c in dest)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",slug)):
            flash("Periksa URL tujuan dan nama tautan.")
            return redirect("/tautan")
        with connect() as db:
            saved=db.execute("""INSERT INTO shortlinks(slug,destination,title) VALUES (%s,%s,%s)
                             ON CONFLICT DO NOTHING""",(slug,dest,request.form["title"].strip()))
            flash("Tautan dibuat." if saved.rowcount else "Nama tautan sudah dipakai.")
        return redirect("/tautan")
    with connect() as db:
        rows=db.execute("SELECT * FROM shortlinks ORDER BY title,slug").fetchall()
    return render_template("studio.html",page="tautan",links=rows)


@app.get("/r/<slug>")
def open_link(slug):
    with connect() as db:
        row=db.execute("UPDATE shortlinks SET clicks=clicks+1 WHERE slug=%s RETURNING destination",(slug,)).fetchone()
    if not row:
        abort(404)
    response=redirect(row["destination"])
    response.headers["Cache-Control"]="no-store"
    return response


STAGES = ("Ide", "Dikerjakan", "Siap", "Draf")


@app.route("/studio/<any(ide,media,draf):page>")
def library_page(page):
    with connect() as db:
        items = db.execute("SELECT id,body,stage FROM editorial WHERE stage <> 'Dipakai' ORDER BY id DESC").fetchall() if page != "media" else []
        media = media_list(db) if page == "media" else []
    return render_template("studio.html", page=page, items=items, media=media, stages=STAGES)


def media_list(db):
    return db.execute("SELECT id,name FROM assets ORDER BY id DESC").fetchall()


@app.get("/media/<int:aid>")
def asset(aid):
    with connect() as db:
        row = db.execute("SELECT photo FROM assets WHERE id=%s", (aid,)).fetchone()
    if not row:
        abort(404)
    photo = bytes(row["photo"])
    return Response(photo, mimetype="image/png" if photo.startswith(b"\x89PNG") else "image/jpeg",
                    headers={"Cache-Control":"private, max-age=86400","X-Content-Type-Options":"nosniff"})


def photo_upload():
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        return None
    data = upload.read()
    if len(data) > 8*1024**2 or not data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        raise ValueError("Gunakan JPEG atau PNG hingga 8 MB.")
    return data


@app.post("/media")
def add_asset():
    try:
        photo = photo_upload()
        if not photo:
            raise ValueError("Pilih foto untuk diunggah.")
        with connect() as db:
            db.execute("INSERT INTO assets(name,photo) VALUES (%s,%s)",
                       (request.files["photo"].filename[:180], photo))
        flash("Foto tersimpan.")
    except ValueError as err:
        flash(str(err))
    return redirect("/studio/media")


@app.post("/ide")
def save_idea():
    body = request.form["body"].strip()
    stage = request.form["stage"]
    if not body or len(body)>4096 or stage not in STAGES:
        abort(400)
    with connect() as db:
        if request.form.get("id"):
            db.execute("UPDATE editorial SET body=%s, stage=%s WHERE id=%s AND stage <> 'Dipakai'",
                       (body,stage,int(request.form["id"])))
        else:
            db.execute("INSERT INTO editorial(body,stage) VALUES(%s,%s)",(body,stage))
    return redirect("/studio/draf" if stage=="Draf" else "/studio/ide")


@app.post("/discord")
def add_discord():
    try:
        url = discord_url(request.form["webhook"].strip())
        hook = discord_request(url)
        if not hook.get("guild_id") or hook.get("type") != 1:
            raise ValueError("Gunakan webhook masuk dari channel server Discord.")
        with connect() as db:
            db.execute("""INSERT INTO channels(id,title,token,platform,guild) VALUES
                 (%s,%s,pgp_sym_encrypt(%s,%s),'Discord',%s) ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title,token=excluded.token,guild=excluded.guild""",
                 (int(hook["id"]),request.form["title"].strip() or hook["name"],url,app.secret_key,hook["guild_id"]))
        flash("Webhook Discord terhubung.")
    except (RuntimeError, ValueError) as err:
        flash(str(err))
    return redirect("/akun")


@app.post("/buat")
def create():
    body = request.form["body"].strip()
    targets = list(dict.fromkeys(request.form.getlist("channel")))
    draft = request.form.get("draft", type=int)
    try:
        photo = photo_upload()
        with connect() as db:
            nonce=request.form.get("nonce","")
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}",nonce):
                abort(400)
            claimed=db.execute("INSERT INTO submissions(nonce) VALUES (%s) ON CONFLICT DO NOTHING",(nonce,))
            if not claimed.rowcount:
                flash("Permintaan ini sudah diproses.")
                return redirect("/kalender")
            if draft and not db.execute("SELECT id FROM editorial WHERE id=%s AND stage='Draf' FOR UPDATE",(draft,)).fetchone():
                raise ValueError("Draf ini sudah diproses.")
            aid = request.form.get("asset",type=int)
            if photo:
                aid=db.execute("INSERT INTO assets(name,photo) VALUES(%s,%s) RETURNING id",
                               (request.files["photo"].filename[:180],photo)).fetchone()["id"]
            elif aid:
                row=db.execute("SELECT photo FROM assets WHERE id=%s",(aid,)).fetchone()
                if not row:
                    raise ValueError("Foto tidak tersedia.")
                photo=row["photo"]
            if not body and not photo:
                raise ValueError("Tulis pesan atau pilih foto.")
            if request.form.get("action")=="draft":
                if draft:
                    db.execute("UPDATE editorial SET body=%s,asset=%s WHERE id=%s",(body,aid,draft))
                else:
                    db.execute("INSERT INTO editorial(body,asset,stage) VALUES(%s,%s,'Draf')",(body,aid))
                flash("Draf tersimpan.")
                return redirect("/studio/draf")
            if not targets:
                raise ValueError("Pilih minimal satu akun.")
            due=read_due(request.form["due"])
            for cid in targets:
                account=db.execute("SELECT platform FROM channels WHERE id=%s",(int(cid),)).fetchone()
                if not account:
                    raise ValueError("Akun tidak tersedia.")
                if account["platform"] not in {"Telegram", "Discord"}:
                    raise ValueError("Konektor akun ini belum mendukung publikasi.")
                limit=2000 if account["platform"]=="Discord" else (1024 if photo else 4096)
                if len(body)>limit:
                    raise ValueError(f"Teks untuk {account['platform']} maksimal {limit} karakter.")
                db.execute("INSERT INTO posts(channel,body,photo,due) VALUES(%s,%s,%s,%s)",(int(cid),body,photo,due))
            if draft:
                db.execute("UPDATE editorial SET stage='Dipakai' WHERE id=%s",(draft,))
        flash("Kiriman masuk antrean.")
        return redirect("/kalender")
    except ValueError as err:
        flash(str(err))
        return redirect("/buat" + (f"?draft={draft}" if draft else ""))


@app.post("/posts/<int:pid>")
def change(pid):
    with connect() as db:
        if request.form["action"]=="cancel":
            changed=db.execute("UPDATE posts SET state='Dibatalkan' WHERE id=%s AND state='Terjadwal'",(pid,))
        else:
            changed=db.execute("UPDATE posts SET due=%s WHERE id=%s AND state='Terjadwal'",
                               (read_due(request.form["due"]),pid))
        flash("Jadwal diperbarui." if changed.rowcount else "Postingan sudah diproses.")
    return redirect("/kalender")


def deliver():
    with connect() as db:
        item=db.execute("""SELECT p.*,c.platform,c.guild,pgp_sym_decrypt(c.token,%s) AS secret FROM posts p
          JOIN channels c ON c.id=p.channel WHERE state='Terjadwal' AND due<=now()
          ORDER BY due,p.id LIMIT 1 FOR UPDATE OF p SKIP LOCKED""",(app.secret_key,)).fetchone()
        if not item:
            return False
        db.execute("UPDATE posts SET state='Mengirim' WHERE id=%s",(item["id"],))
    data={"chat_id":item["channel"]}
    link=None
    note=None
    try:
        if item["platform"]=="Discord":
            payload={"content":item["body"],"allowed_mentions":{"parse":[]}}
            sent=discord_request(discord_url(item["secret"]),payload=payload,photo=bytes(item["photo"] or b""))
            link=f"https://discord.com/channels/{item['guild']}/{sent['channel_id']}/{sent['id']}"
        elif item["platform"] == "Telegram":
            if item["photo"]:
                data["caption"]=item["body"]
                sent=telegram(item["secret"],"sendPhoto",data,{"photo":("foto",bytes(item["photo"]))})
            else:
                data["text"]=item["body"]
                sent=telegram(item["secret"],"sendMessage",data)
            username=sent["chat"].get("username")
            path=username or "c/"+str(item["channel"]).removeprefix("-100")
            link=f"https://t.me/{path}/{sent['message_id']}"
        else:
            raise ValueError("Konektor akun ini belum mendukung publikasi.")
        state="Terbit"
    except ValueError as err:
        state,note="Gagal",str(err)
    except RuntimeError as err:
        state,note="Periksa channel",str(err)
    with connect() as db:
        db.execute("UPDATE posts SET state=%s,note=%s,link=%s WHERE id=%s",(state,note,link,item["id"]))
    return True


if __name__=="__main__":
    last_ping=0
    while True:
        if time.monotonic()-last_ping >= 15:
            with connect() as db:
                db.execute("""INSERT INTO worker_status VALUES (1,now())
                           ON CONFLICT(id) DO UPDATE SET seen=excluded.seen""")
            last_ping=time.monotonic()
        if not deliver():
            time.sleep(3)

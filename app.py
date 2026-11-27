import os
import hmac
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

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
      state text NOT NULL DEFAULT 'Terjadwal', note text, link text);""")


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
        channels = db.execute("SELECT id,title FROM channels ORDER BY title").fetchall()
        posts = db.execute("""SELECT p.id,body,due,state,note,link,title FROM posts p
                            JOIN channels c ON p.channel=c.id
                            ORDER BY (state='Terjadwal') DESC,
                            CASE WHEN state='Terjadwal' THEN due END ASC,due DESC LIMIT 200""").fetchall()
    for post in posts:
        post["local"] = post["due"].astimezone(WIB)
    if page=="kalender":
        posts.sort(key=lambda p:p["local"])
    return render_template("studio.html", page=page, channels=channels, posts=posts)


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
            db.execute("""INSERT INTO channels VALUES (%s,%s,pgp_sym_encrypt(%s,%s))
                       ON CONFLICT(id) DO UPDATE SET title=excluded.title, token=excluded.token""",
                       (chat["id"],chat["title"],token,app.secret_key))
        flash("Channel terhubung.")
    except (ValueError,RuntimeError) as err:
        flash(str(err))
    return redirect("/akun")


def read_due(value):
    return datetime.fromisoformat(value).replace(tzinfo=WIB) if value else datetime.now(WIB)


@app.post("/buat")
def create():
    body=request.form["body"].strip()
    upload=request.files.get("photo")
    photo=upload.read() if upload and upload.filename else None
    if photo and not (photo.startswith(b"\xff\xd8\xff") or photo.startswith(b"\x89PNG\r\n\x1a\n")):
        flash("Pilih foto JPEG atau PNG.")
        return redirect("/buat")
    if (not body and not photo) or len(body)>(1024 if photo else 4096):
        flash("Periksa isi pesan. Batas teks 4096 karakter atau 1024 untuk caption foto.")
        return redirect("/buat")
    with connect() as db:
        db.execute("INSERT INTO posts(channel,body,photo,due) VALUES(%s,%s,%s,%s)",
                   (int(request.form["channel"]),body,photo,read_due(request.form["due"])))
    flash("Postingan masuk antrean.")
    return redirect("/kalender")


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
        item=db.execute("""SELECT p.*,pgp_sym_decrypt(c.token,%s) AS secret FROM posts p
          JOIN channels c ON c.id=p.channel WHERE state='Terjadwal' AND due<=now()
          ORDER BY due,p.id LIMIT 1 FOR UPDATE OF p SKIP LOCKED""",(app.secret_key,)).fetchone()
        if not item:
            return False
        db.execute("UPDATE posts SET state='Mengirim' WHERE id=%s",(item["id"],))
    data={"chat_id":item["channel"]}
    link=None
    note=None
    try:
        if item["photo"]:
            data["caption"]=item["body"]
            sent=telegram(item["secret"],"sendPhoto",data,{"photo":("foto",bytes(item["photo"]))})
        else:
            data["text"]=item["body"]
            sent=telegram(item["secret"],"sendMessage",data)
        username=sent["chat"].get("username")
        path=username or "c/"+str(item["channel"]).removeprefix("-100")
        link=f"https://t.me/{path}/{sent['message_id']}"
        state="Terbit"
    except ValueError as err:
        state,note="Gagal",str(err)
    except RuntimeError as err:
        state,note="Periksa channel",str(err)
    with connect() as db:
        db.execute("UPDATE posts SET state=%s,note=%s,link=%s WHERE id=%s",(state,note,link,item["id"]))
    return True


if __name__=="__main__":
    while True:
        if not deliver():
            time.sleep(3)

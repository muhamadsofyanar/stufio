import workflows
import reports
import service_desk
import calendar
import csv
import io
from contextvars import ContextVar
from werkzeug.security import check_password_hash
from psycopg import sql
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import psycopg
import requests
from flask import Flask, g, has_request_context, Response, abort, flash, redirect, render_template, request, session
from psycopg.rows import dict_row

import social_oauth
from publishing import discord_request, discord_url
import multi_publish

app = Flask(__name__)
app.secret_key = os.environ["APP_KEY"]
app.config.update(MAX_CONTENT_LENGTH=34*1024**2, SESSION_COOKIE_SECURE=True,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
WIB = ZoneInfo("Asia/Jakarta")


worker_workspace = ContextVar("worker_workspace", default=1)


def schema_for(wid):
    return "public" if wid == 1 else f"studio_ws_{int(wid)}"


def raw_connection():
    return psycopg.connect("", row_factory=dict_row)


def set_workspace(db, wid):
    db.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_for(wid))))


def connect():
    db = raw_connection()
    try:
        wid = g.workspace_id if has_request_context() else worker_workspace.get()
        set_workspace(db, wid)
        return db
    except Exception:
        db.close()
        raise


def prepare_schema(db, wid):
    if db.execute("SELECT 1 FROM public.workspace_migrations WHERE workspace=%s AND version=1",(wid,)).fetchone():
        set_workspace(db,wid)
        service_desk.migrate(db,wid)
        workflows.migrate(db,wid)
        return
    schema = sql.Identifier(schema_for(wid))
    db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
    set_workspace(db, wid)
    db.execute("""CREATE EXTENSION IF NOT EXISTS pgcrypto;
    CREATE TABLE IF NOT EXISTS channels (
      id bigint PRIMARY KEY, title text NOT NULL, token bytea NOT NULL);
    CREATE TABLE IF NOT EXISTS posts (
      id bigserial PRIMARY KEY, channel bigint NOT NULL REFERENCES channels,
      body text NOT NULL, photo bytea, due timestamptz NOT NULL,
      state text NOT NULL DEFAULT 'Terjadwal', note text, link text);
    CREATE TABLE IF NOT EXISTS editorial_settings(id int PRIMARY KEY CHECK(id=1), approval boolean NOT NULL DEFAULT false);
    INSERT INTO editorial_settings VALUES(1,false) ON CONFLICT DO NOTHING;
    CREATE TABLE IF NOT EXISTS job_events(id bigserial PRIMARY KEY, post_id bigint NOT NULL REFERENCES posts,
        happened timestamptz DEFAULT now(), state text NOT NULL, note text);
    ALTER TABLE channels ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'Telegram';
    ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild text;
    ALTER TABLE channels ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
    CREATE TABLE IF NOT EXISTS assets(id bigserial PRIMARY KEY,name text NOT NULL,photo bytea NOT NULL);
    CREATE TABLE IF NOT EXISTS editorial(id bigserial PRIMARY KEY,body text NOT NULL,stage text NOT NULL,
                                         asset bigint REFERENCES assets);
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS editorial_id bigint REFERENCES editorial;
    CREATE TABLE IF NOT EXISTS editorial_history(id bigserial PRIMARY KEY, item bigint REFERENCES editorial,
        happened timestamptz DEFAULT now(), actor text NOT NULL, stage text NOT NULL, note text NOT NULL DEFAULT '');
    ALTER TABLE editorial ADD COLUMN IF NOT EXISTS composer jsonb NOT NULL DEFAULT '{}';
    CREATE TABLE IF NOT EXISTS shortlinks(slug text PRIMARY KEY, destination text NOT NULL,
      title text NOT NULL, clicks bigint NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS worker_status(id integer PRIMARY KEY, seen timestamptz NOT NULL);
    CREATE TABLE IF NOT EXISTS oauth_accounts (
      id bigserial PRIMARY KEY, platform text NOT NULL, external_id text NOT NULL,
      title text NOT NULL, credential bytea NOT NULL, expires_at timestamptz,
      UNIQUE (platform, external_id));
    CREATE TABLE IF NOT EXISTS admin_events(id bigserial PRIMARY KEY, happened timestamptz NOT NULL DEFAULT now(),
        actor text NOT NULL, action text NOT NULL, target text NOT NULL);
    ALTER TABLE oauth_accounts ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
    ALTER TABLE oauth_accounts ADD COLUMN IF NOT EXISTS sync_result text;
    ALTER TABLE oauth_accounts ADD COLUMN IF NOT EXISTS synced_at timestamptz;
    ALTER TABLE oauth_accounts ADD COLUMN IF NOT EXISTS publish_ready boolean NOT NULL DEFAULT false;
    ALTER TABLE oauth_accounts ADD COLUMN IF NOT EXISTS refreshable boolean NOT NULL DEFAULT false;
    ALTER TABLE posts ALTER COLUMN channel DROP NOT NULL;
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS oauth_id bigint;
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS target_title text;
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS cover bytea;
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS publish_options jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
    CREATE TABLE IF NOT EXISTS oauth_attempts (
      state text PRIMARY KEY, platform text NOT NULL, session_hash text NOT NULL,
      verifier text NOT NULL, created timestamptz NOT NULL DEFAULT now());
    CREATE TABLE IF NOT EXISTS metric_days(account bigint REFERENCES oauth_accounts ON DELETE CASCADE, day date NOT NULL,
        metric text NOT NULL, value numeric NOT NULL, PRIMARY KEY(account,day,metric));
    CREATE TABLE IF NOT EXISTS activity(account bigint REFERENCES oauth_accounts ON DELETE CASCADE,kind text NOT NULL,
        external_id text NOT NULL,label text NOT NULL,body text NOT NULL,video text,observed timestamptz DEFAULT now(),
        PRIMARY KEY(account,kind,external_id));
    ALTER TABLE activity ADD COLUMN IF NOT EXISTS reply_to text;
    ALTER TABLE activity ADD COLUMN IF NOT EXISTS reply_state text;
    ALTER TABLE activity ADD COLUMN IF NOT EXISTS reply_body text;
    CREATE TABLE IF NOT EXISTS submissions(nonce text PRIMARY KEY, created timestamptz DEFAULT now());""")

    db.execute("INSERT INTO public.workspace_migrations(workspace,version) VALUES(%s,1)",(wid,))
    service_desk.migrate(db,wid)
    workflows.migrate(db,wid)


with raw_connection() as db:
    db.execute("SELECT pg_advisory_xact_lock(782391)")
    db.execute("""CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
        CREATE TABLE IF NOT EXISTS public.workspaces(id bigserial PRIMARY KEY, name text NOT NULL);
        CREATE TABLE IF NOT EXISTS public.workspace_migrations(workspace bigint REFERENCES public.workspaces,version int NOT NULL,PRIMARY KEY(workspace,version));
        CREATE TABLE IF NOT EXISTS public.studio_users(id bigserial PRIMARY KEY, login text UNIQUE NOT NULL, password_hash text NOT NULL);
        CREATE TABLE IF NOT EXISTS public.memberships(workspace bigint REFERENCES public.workspaces, member bigint REFERENCES public.studio_users,
            role text NOT NULL CHECK(role IN ('manager','editor','viewer')), PRIMARY KEY(workspace,member));""")
    if not db.execute("SELECT 1 FROM public.workspaces LIMIT 1").fetchone():
        legacy = db.execute("SELECT to_regclass('public.channels') IS NOT NULL AS present").fetchone()["present"]
        names = ["IzinHukum", "StifinMulia", "Muhamad Sofyan"]
        if legacy:
            names.insert(0, "Studio lama")
        for name in names:
            db.execute("INSERT INTO public.workspaces(name) VALUES (%s)", (name,))
    for row in db.execute("SELECT id FROM public.workspaces ORDER BY id").fetchall():
        prepare_schema(db, row["id"])


def record_event(db, action, target):
    actor = "owner" if session.get("admin") else f"user:{session['user']}"
    db.execute("INSERT INTO admin_events(actor,action,target) VALUES(%s,%s,%s)", (actor, action, str(target)))


def available(db):
    if session.get("admin"):
        return db.execute("SELECT id,name,'owner' AS role FROM public.workspaces ORDER BY id").fetchall()
    return db.execute("""SELECT w.id,w.name,m.role FROM public.memberships m JOIN public.workspaces w ON w.id=m.workspace
        WHERE member=%s ORDER BY w.id""",(session.get("user"),)).fetchall()


@app.after_request
def cache_policy(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"]="private, no-store"
    return response


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
    if request.endpoint=="integration_comment":
        g.workspace_id=request.view_args["wid"]
        validate_public_workspace(g.workspace_id)
        return
    session.setdefault("csrf", secrets.token_urlsafe(24))
    if request.method == "POST" and not hmac.compare_digest(
            str(request.form.get("csrf","")).encode(), session["csrf"].encode()):
        abort(403)
    if request.endpoint in {"static","login"}:
        return
    if request.endpoint in {"open_link","publish_media"}:
        g.workspace_id = (request.view_args or {}).get("wid", 1)
        return
    if not (session.get("admin") or session.get("user")):
        return redirect("/login")
    if request.endpoint == "logout":
        return
    with raw_connection() as db:
        g.workspaces = available(db)
    if not g.workspaces:
        abort(403)
    active = session.get("workspace", g.workspaces[0]["id"])
    current = next((row for row in g.workspaces if row["id"] == active), None)
    if not current:
        if request.method != "GET": abort(403)
        current = g.workspaces[0]
    g.workspace_id, g.role, g.workspace_name = current["id"], current["role"], current["name"]
    if request.args.get("ws") is not None and request.args.get("ws", type=int) != g.workspace_id:
        abort(409)
    management = {"start_oauth","finish_oauth","disconnect_oauth","disconnect_channel","add_discord","account","settings"}
    if request.endpoint in management and g.role not in ("owner","manager"):
        abort(403)
    if request.method == "POST" and request.endpoint != "switch_workspace" and g.role == "viewer":
        abort(403)


@app.post("/workspace/switch")
def switch_workspace():
    wid = request.form.get("workspace",type=int)
    if wid not in [row["id"] for row in g.workspaces]: abort(403)
    session.update(workspace=wid, csrf=secrets.token_urlsafe(24))
    return redirect("/")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        login_name=request.form.get("login","").strip().casefold()
        if login_name:
            with raw_connection() as db:
                user=db.execute("SELECT * FROM public.studio_users WHERE login=%s",(login_name,)).fetchone()
            if user and check_password_hash(user["password_hash"],request.form["password"]):
                session.clear()
                session.update(user=user["id"], csrf=secrets.token_urlsafe(24))
                return redirect("/")
        elif hmac.compare_digest(request.form["password"].encode(), os.environ["ADMIN_PASSWORD"].encode()):
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
@app.route("/<any(akun,buat,kalender,terbit):page>")
def dashboard(page="ringkasan"):
    if page == "buat" and g.role == "viewer":
        abort(403)
    if page == "akun":
        with connect() as db:
            channels = db.execute("SELECT id,title,platform,active FROM channels ORDER BY active DESC,title,id").fetchall()
            accounts = db.execute("""SELECT id,platform,title,external_id,active,publish_ready,sync_result,synced_at,(expires_at <= now() AND NOT refreshable) AS expired
                                      FROM oauth_accounts ORDER BY title, id""").fetchall()
        providers = [(key, provider, bool(social_oauth.settings(key)))
                     for key in social_oauth.PROVIDERS for provider in [social_oauth.provider_for(key)]]
        return render_template("studio.html", page=page, channels=channels,
                               social_accounts=accounts, providers=providers,
                               provider_labels={key: provider.label for key, provider, _ in providers})
    with connect() as db:
        channels = db.execute("SELECT id,title,platform FROM channels WHERE active ORDER BY title").fetchall()
        channels += [{**row, "id": "oauth:"+str(row["id"]), "platform": multi_publish.LABELS[row["platform"]],
                      "key": row["platform"]} for row in db.execute("""SELECT id,title,platform FROM oauth_accounts
                      WHERE publish_ready AND (expires_at IS NULL OR expires_at > now() OR refreshable) ORDER BY title""").fetchall()
                     if row["platform"] in multi_publish.CAPABILITIES]
        draft = None
        media = []
        if page == "buat":
            media = media_list(db)
            if request.args.get("draft",type=int):
                draft=db.execute("SELECT * FROM editorial WHERE id=%s AND stage IN ('Draf','Perlu Revisi')",(request.args.get("draft",type=int),)).fetchone()
                if not draft:
                    abort(404)
        approval = db.execute("SELECT approval FROM editorial_settings WHERE id=1").fetchone()["approval"]
        heartbeat = db.execute("SELECT seen > now()-interval '90 seconds' AS active FROM worker_status WHERE id=1").fetchone() if page=="ringkasan" else None
        totals = db.execute("""SELECT count(*) FILTER (WHERE state='Terjadwal') AS queued,
                            count(*) FILTER (WHERE state='Terbit') AS sent,
                            count(*) FILTER (WHERE state IN ('Gagal','Periksa channel')) AS issues
                            FROM posts""").fetchone()
        month = request.args.get("month") or datetime.now(WIB).strftime("%Y-%m")
        weeks, day_counts, calendar_dates = [], {}, {}
        account_filter = request.args.get("account","") if page=="kalender" else ""
        key_expr = "CASE WHEN oauth_id IS NULL THEN channel::text ELSE 'oauth:'||oauth_id::text END"
        if page == "kalender":
            try:
                first = datetime.strptime(month, "%Y-%m").replace(tzinfo=WIB)
                end = (first + timedelta(days=32)).replace(day=1)
            except (ValueError, OverflowError):
                abort(400)
            week = request.args.get("week")
            if week:
                try:
                    chosen = datetime.strptime(week,"%Y-%m-%d").replace(tzinfo=WIB)
                    first = chosen - timedelta(days=chosen.weekday())
                    end = first + timedelta(days=7)
                except (ValueError, OverflowError):
                    abort(400)
                weeks = [[(first+timedelta(days=i)).day for i in range(7)]]
            else:
                weeks = calendar.monthcalendar(first.year, first.month)
            calendar_dates={(first+timedelta(days=i)).day:(first+timedelta(days=i)).date().isoformat() for i in range((end-first).days)}
            day_counts = {row["day"]:row["n"] for row in db.execute("""SELECT extract(day FROM due AT TIME ZONE 'Asia/Jakarta')::int AS day,count(*) AS n
                FROM posts WHERE due >= %s AND due < %s AND (%s='' OR """+key_expr+"""=%s) GROUP BY 1""", (first,end,account_filter,account_filter))}
        posts = db.execute("""SELECT p.id,p.editorial_id,body,due,state,note,link,COALESCE(c.title,p.target_title,'Akun dilepas') AS title FROM posts p
                            LEFT JOIN channels c ON p.channel=c.id
                            WHERE (%s <> 'terbit' OR state='Terbit') AND (%s <> 'kalender' OR (due >= %s AND due < %s)) AND (%s='' OR CASE WHEN oauth_id IS NULL THEN channel::text ELSE 'oauth:'||oauth_id::text END=%s) ORDER BY (state='Terjadwal') DESC,
                            CASE WHEN state='Terjadwal' THEN due END ASC,due DESC LIMIT 200""",(page,page,first if weeks else None,end if weeks else None,account_filter,account_filter)).fetchall()
        logs={}
        for event in db.execute("SELECT id,post_id,state,note,happened FROM job_events WHERE post_id=ANY(%s) ORDER BY id DESC",([p["id"] for p in posts],)):
            logs.setdefault(event["post_id"],[]).append(event)
    for post in posts:
        post["local"] = post["due"].astimezone(WIB)
    if page=="kalender":
        posts.sort(key=lambda p:p["local"])
    return render_template("studio.html", page=page, channels=channels, posts=posts, logs=logs, totals=totals, draft=draft, media=media, approval=approval, heartbeat=heartbeat, weeks=weeks, calendar_dates=calendar_dates, month=month, day_counts=day_counts, nonce=secrets.token_urlsafe(18))


@app.post("/akun")
def account():
    token=request.form["token"].strip()
    target=request.form["target"].strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not target:
        flash("Periksa token bot dan username atau ID Telegram.")
        return redirect("/akun")
    try:
        bot=telegram(token,"getMe",{})
        chat=telegram(token,"getChat",{"chat_id":target})
        member=telegram(token,"getChatMember",{"chat_id":chat["id"],"user_id":bot["id"]})
        if chat["type"] == "channel":
            if not member.get("can_post_messages"):
                raise ValueError("Jadikan bot admin channel dan izinkan mengirim pesan.")
        elif chat["type"] in {"group", "supergroup"}:
            if member["status"] not in {"administrator", "creator"}:
                raise ValueError("Jadikan bot admin grup Telegram.")
        else:
            raise ValueError("Pilih channel atau grup Telegram.")
        with connect() as db:
            db.execute("""INSERT INTO channels(id,title,token) VALUES (%s,%s,public.pgp_sym_encrypt(%s,%s))
                       ON CONFLICT(id) DO UPDATE SET active=true,title=excluded.title, token=excluded.token""",
                       (chat["id"],chat["title"],token,app.secret_key))
            record_event(db, "Hubungkan Telegram", chat["id"])
        flash("Channel terhubung.")
    except (ValueError,RuntimeError) as err:
        flash(str(err))
    return redirect("/akun")


def oauth_session_hash():
    return hashlib.sha256(session["csrf"].encode()).hexdigest()


@app.post("/akun/oauth/<platform>")
def start_oauth(platform):
    if platform not in social_oauth.PROVIDERS:
        abort(404)
    config = social_oauth.settings(platform)
    if not config:
        flash("Lengkapi konfigurasi aplikasi platform sebelum menyambungkan akun.")
        return redirect("/akun")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    with connect() as db:
        db.execute("DELETE FROM oauth_attempts WHERE created <= now() - interval '10 minutes'")
        db.execute("""INSERT INTO oauth_attempts(state,platform,session_hash,verifier)
                      VALUES (%s,%s,%s,%s)""", (state, platform, oauth_session_hash(), verifier))
    response = redirect(social_oauth.authorization_url(platform, config, state, verifier))
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/akun/oauth/<platform>/callback")
def finish_oauth(platform):
    if platform not in social_oauth.PROVIDERS:
        abort(404)
    state = request.args.get("state", "")
    attempt = None
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
        with connect() as db:
            attempt = db.execute("""DELETE FROM oauth_attempts
                WHERE state=%s AND platform=%s AND session_hash=%s
                  AND created > now() - interval '10 minutes' RETURNING verifier""",
                (state, platform, oauth_session_hash())).fetchone()
    config = social_oauth.settings(platform)
    try:
        if not config or not attempt:
            raise ValueError("Sesi koneksi kedaluwarsa atau sudah dipakai. Mulai lagi dari Akun sosial.")
        code = request.args.get("code")
        if request.args.get("error") or not code:
            raise ValueError("Izin akun dibatalkan atau ditolak.")
        token = social_oauth.exchange(platform, config, code, attempt["verifier"])
        token = {key: token[key] for key in ("access_token", "refresh_token", "expires_in", "scope", "permissions", "instagram_mode")
                 if key in token}
        granted = social_oauth.granted_scopes(platform, token)
        accounts = {str(external_id): (title, credentials)
                    for external_id, title, credentials in social_oauth.accounts(platform, token)
                    if external_id and isinstance(title, str) and title.strip()}
        if not accounts:
            raise ValueError("Platform tidak mengembalikan akun yang dapat dihubungkan.")
        with connect() as db:
            for external_id, (title, credentials) in accounts.items():
                lifetime = credentials.get("expires_in")
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(lifetime))
                              if str(lifetime).isdigit() and 0 < int(lifetime) < 10**9 else None)
                db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential,expires_at,publish_ready,refreshable)
                              VALUES (%s,%s,%s,public.pgp_sym_encrypt(%s,%s),%s,%s,%s)
                              ON CONFLICT (platform,external_id) DO UPDATE SET
                              active=true,title=excluded.title, credential=excluded.credential,
                              expires_at=excluded.expires_at,publish_ready=excluded.publish_ready,refreshable=excluded.refreshable""",
                           (platform, external_id, title, json.dumps(credentials),
                            app.secret_key, expires_at, (multi_publish.SCOPES.get(platform) in granted or (platform=="instagram" and "instagram_business_content_publish" in granted)) and credentials.get("can_publish",True), bool(credentials.get("refresh_token"))))
                record_event(db, "Hubungkan OAuth", f"{platform}:{external_id}")
        flash(f"{len(accounts)} akun {social_oauth.PROVIDERS[platform].label} tersimpan.")
    except ValueError as err:
        flash(str(err))
    except (KeyError, TypeError, AttributeError):
        flash("Format respons platform tidak dikenali.")
    response = redirect("/akun")
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/akun/oauth/lepas/<int:account_id>")
def disconnect_oauth(account_id):
    with connect() as db:
        changed = db.execute("""UPDATE oauth_accounts SET active=false,publish_ready=false,refreshable=false,
            credential=public.pgp_sym_encrypt('{}',%s),expires_at=NULL WHERE id=%s AND active RETURNING id""",
            (app.secret_key,account_id)).fetchone()
        if not changed:
            abort(404)
        db.execute("UPDATE posts SET state='Dibatalkan',note='Akun dilepas' WHERE oauth_id=%s AND state IN ('Terjadwal','Diajukan')", (account_id,))
        record_event(db, "Lepas OAuth", account_id)
    flash("Akun dilepas. Jadwal yang masih menunggu dibatalkan.")
    return redirect("/akun")


@app.post("/akun/channel/<channel>/lepas")
def disconnect_channel(channel):
    if not re.fullmatch(r"-?[0-9]{1,19}",channel): abort(400)
    with connect() as db:
        account=db.execute("SELECT id FROM channels WHERE id=%s AND active FOR UPDATE",(int(channel),)).fetchone()
        if not account: abort(404)
        db.execute("UPDATE channels SET active=false,token=public.pgp_sym_encrypt('',%s) WHERE id=%s",(app.secret_key,account["id"]))
        db.execute("UPDATE posts SET state='Dibatalkan',note='Akun dilepas' WHERE channel=%s AND state IN ('Terjadwal','Diajukan')",(account["id"],))
        record_event(db, "Lepas channel", channel)
    flash("Akun dilepas. Jadwal yang masih menunggu dibatalkan.")
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


@app.get("/w/<int:wid>/r/<slug>")
@app.get("/r/<slug>")
def open_link(slug,wid=1):
    validate_public_workspace(wid)
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
        items = db.execute("SELECT id,body,stage,composer FROM editorial WHERE stage <> 'Dipakai' ORDER BY id DESC").fetchall() if page != "media" else []
        events=db.execute("SELECT item,actor,stage,note,happened FROM editorial_history ORDER BY id DESC LIMIT 300").fetchall() if page=="draf" else []
        pending=db.execute("SELECT editorial_id,body,photo IS NOT NULL AS media, due,COALESCE(c.title,p.target_title) AS title FROM posts p LEFT JOIN channels c ON c.id=p.channel WHERE state='Diajukan' ORDER BY p.id").fetchall() if page=="draf" else []
        media = media_list(db) if page == "media" else []
    return render_template("studio.html", page=page, items=items, media=media, stages=STAGES,events=events,pending=pending)


def media_list(db):
    return db.execute("SELECT id,name,substring(photo from 5 for 4)=decode('66747970','hex') AS video FROM assets ORDER BY id DESC").fetchall()


@app.get("/media/<int:aid>")
def asset(aid):
    with connect() as db:
        row = db.execute("SELECT photo FROM assets WHERE id=%s", (aid,)).fetchone()
    if not row:
        abort(404)
    photo = bytes(row["photo"])
    return Response(photo, mimetype=multi_publish.mime(photo),
                    headers={"Cache-Control":"private, max-age=86400","X-Content-Type-Options":"nosniff"})


def photo_upload():
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        return None
    data = upload.read()
    kind = multi_publish.media_kind(data)
    if kind == "text" or len(data) > (32 if kind == "video" else 8)*1024**2:
        raise ValueError("Gunakan JPEG/PNG hingga 8 MB atau MP4 hingga 32 MB.")
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
            db.execute("UPDATE editorial SET body=%s, stage=%s WHERE id=%s AND stage IN ('Ide','Dikerjakan','Siap','Draf')",
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
                 (%s,%s,public.pgp_sym_encrypt(%s,%s),'Discord',%s) ON CONFLICT(id) DO UPDATE SET
                 active=true,title=excluded.title,token=excluded.token,guild=excluded.guild""",
                 (int(hook["id"]),request.form["title"].strip() or hook["name"],url,app.secret_key,hook["guild_id"]))
            record_event(db, "Hubungkan Discord", hook["id"])
        flash("Webhook Discord terhubung.")
    except (RuntimeError, ValueError) as err:
        flash(str(err))
    return redirect("/akun")


def asset_data(db, identity):
    if not str(identity).isdecimal() or len(str(identity)) > 18:
        raise ValueError("ID media tidak valid.")
    row=db.execute("SELECT photo FROM assets WHERE id=%s",(int(identity),)).fetchone()
    if not row:
        raise ValueError("Media tidak tersedia di workspace ini.")
    return row["photo"]


def enqueue(db, item, body, base_photo, form):
    targets=form["targets"]
    overrides=form["captions"]
    variants=form.get("media",{})
    if not targets:
        raise ValueError("Pilih minimal satu akun.")
    due=read_due(form["due"])
    cover=None
    if form.get("cover"):
        cover=asset_data(db,form["cover"])
        if multi_publish.media_kind(bytes(cover))!="image":
            raise ValueError("Cover harus berupa foto dari pustaka.")
    for cid in targets:
        photo = base_photo
        selected = variants.get(cid)
        if selected == "none":
            photo = None
        elif selected:
            photo = asset_data(db, selected)
        caption = overrides.get(cid, body)
        if not caption and not photo:
            raise ValueError("Setiap tujuan memerlukan caption atau media.")
        if cid.startswith("oauth:"):
            account_id = cid.removeprefix("oauth:")
            if not account_id.isdecimal() or len(account_id)>18: raise ValueError("Akun tidak valid.")
            account=db.execute("""SELECT id,title,platform FROM oauth_accounts WHERE id=%s AND publish_ready
                AND (expires_at IS NULL OR expires_at > now() OR refreshable) FOR SHARE""",(int(account_id),)).fetchone()
            if not account: raise ValueError("Akun OAuth belum siap; sambungkan ulang.")
            multi_publish.validate(account["platform"],caption,bytes(photo or b""))
            if account["platform"]=="pinterest" and multi_publish.media_kind(bytes(photo or b""))=="video" and not cover:
                raise ValueError("Pilih foto cover untuk video Pinterest.")
            options={}
            if account["platform"]=="youtube":
                privacy=form.get("youtube_privacy","private")
                kids=form.get("youtube_kids","")
                if privacy not in {"public","unlisted","private"} or kids not in {"yes","no"}:
                    raise ValueError("Pilih visibilitas dan audiens anak YouTube.")
                options={"privacy":privacy,"kids":kids=="yes"}
            job=db.execute("INSERT INTO posts(editorial_id,oauth_id,target_title,body,photo,due,cover,publish_options) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",
                       (item,account["id"],account["title"],caption,photo,due,cover if account["platform"]=="pinterest" else None,json.dumps(options)))
        else:
            if not re.fullmatch(r"-?[0-9]{1,19}",cid): raise ValueError("Akun tidak valid.")
            account=db.execute("SELECT platform FROM channels WHERE id=%s AND active FOR SHARE",(int(cid),)).fetchone()
            if not account: raise ValueError("Akun tidak tersedia.")
            multi_publish.validate(account["platform"],caption,bytes(photo or b""))
            job=db.execute("INSERT INTO posts(editorial_id,channel,body,photo,due) VALUES(%s,%s,%s,%s,%s) RETURNING id",(item,int(cid),caption,photo,due))
        db.execute("INSERT INTO job_events(post_id,state) VALUES(%s,'Terjadwal')",(job.fetchone()["id"],))


def history(db, item, stage, note=""):
    actor = "Admin utama" if session.get("admin") else f"Pengguna {session['user']}"
    db.execute("INSERT INTO editorial_history(item,actor,stage,note) VALUES(%s,%s,%s,%s)",(item,actor,stage,note))


def save_material(db, body, asset, form, draft, action, approval):
    if not body and not asset and not any(form["captions"].values()) and not any(v!="none" for v in form["media"].values()):
        raise ValueError("Tulis pesan atau pilih media.")
    if draft and not db.execute("SELECT id FROM editorial WHERE id=%s AND stage IN ('Draf','Perlu Revisi') FOR UPDATE",(draft,)).fetchone():
        raise ValueError("Draf ini sudah diproses.")
    stage = "Draf" if action=="draft" else "Diajukan" if approval else "Dipakai"
    values=(body,asset,json.dumps(form),stage)
    if draft:
        db.execute("UPDATE editorial SET body=%s,asset=%s,composer=%s,stage=%s WHERE id=%s",(*values,draft))
        item=draft
    else:
        item=db.execute("INSERT INTO editorial(body,asset,composer,stage) VALUES(%s,%s,%s,%s) RETURNING id",values).fetchone()["id"]
    if stage!="Draf":
        enqueue(db,item,body,asset_data(db,asset) if asset else None,form)
        if approval:
            db.execute("UPDATE posts SET state='Diajukan' WHERE editorial_id=%s AND state='Terjadwal'",(item,))
            db.execute("UPDATE job_events SET state='Diajukan' WHERE post_id IN (SELECT id FROM posts WHERE editorial_id=%s AND state='Diajukan')",(item,))
    history(db,item,stage if stage!="Dipakai" else "Terjadwal")
    return stage


@app.post("/buat")
def create():
    draft=request.form.get("draft",type=int)
    action=request.form.get("action","publish")
    if action not in ("draft","publish","bulk"): abort(400)
    targets=list(dict.fromkeys(request.form.getlist("channel")))
    form={key:request.form.get(key,"") for key in ("due","cover","youtube_kids")}
    form["youtube_privacy"]=request.form.get("youtube_privacy","private")
    form["targets"]=targets
    form["captions"]={cid:request.form["caption_"+cid].strip() for cid in targets if request.form.get("caption_"+cid,"").strip()}
    form["media"]={cid:request.form["media_"+cid] for cid in targets if request.form.get("media_"+cid)}
    try:
        photo=photo_upload()
        with connect() as db:
            nonce=request.form.get("nonce","")
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}",nonce): abort(400)
            if not db.execute("INSERT INTO submissions VALUES(%s,now()) ON CONFLICT DO NOTHING",(nonce,)).rowcount:
                flash("Permintaan ini sudah diproses.")
                return redirect("/kalender")
            approval=db.execute("SELECT approval FROM editorial_settings WHERE id=1 FOR SHARE").fetchone()["approval"]
            asset=request.form.get("asset",type=int)
            if photo:
                asset=db.execute("INSERT INTO assets(name,photo) VALUES(%s,%s) RETURNING id",(request.files["photo"].filename[:180],photo)).fetchone()["id"]
            if action=="bulk":
                if draft: abort(400)
                upload=request.files.get("csv")
                if not upload: raise ValueError("Pilih berkas CSV.")
                records=csv.DictReader(io.StringIO(upload.read(500001).decode("utf-8-sig")),strict=True)
                if upload.tell()>500000 or records.fieldnames != ["caption","due","asset"]:
                    raise ValueError("Gunakan CSV UTF-8 hingga 500 KB dengan header caption,due,asset.")
                count=0
                for count,row in enumerate(records,1):
                    if count>100 or None in row or None in row.values(): raise ValueError("CSV harus berisi maksimal 100 materi dengan tiga kolom.")
                    entry=dict(form,captions={},media={},due=row["due"].strip())
                    try:
                        identity=row["asset"].strip()
                        if identity and (not identity.isdecimal() or len(identity)>18): raise ValueError("ID media tidak valid.")
                        stage=save_material(db,row["caption"].strip(),int(identity) if identity else None,entry,None,"publish",approval)
                    except ValueError as err:
                        raise ValueError(f"Materi {count}: {err}") from err
                if not count: raise ValueError("CSV kosong.")
            else:
                for value in form["media"].values():
                    if value!="none": asset_data(db,value)
                stage=save_material(db,request.form.get("body","").strip(),asset,form,draft,action,approval)
        flash({"Dipakai":"Kiriman masuk antrean.","Diajukan":"Materi masuk antrean persetujuan.","Draf":"Draf tersimpan."}[stage])
        return redirect("/kalender" if stage=="Dipakai" else "/studio/draf")
    except (ValueError,csv.Error) as err:
        flash(str(err))
        return redirect("/buat"+(f"?draft={draft}" if draft else ""))


@app.post("/posts/<int:pid>")
def change(pid):
    with connect() as db:
        if request.form["action"]=="retry":
            changed=db.execute("""UPDATE posts SET state='Terjadwal',due=now(),note=NULL,claimed_at=NULL
                WHERE id=%s AND state='Gagal' AND %s=(SELECT COALESCE(max(id),0) FROM job_events WHERE post_id=%s)""",
                (pid,request.form.get("event",type=int),pid))
        elif request.form["action"]=="cancel":
            changed=db.execute("UPDATE posts SET state='Dibatalkan' WHERE id=%s AND state='Terjadwal'",(pid,))
        elif request.form["action"]=="save":
            changed=db.execute("UPDATE posts SET due=%s WHERE id=%s AND state='Terjadwal'",
                               (read_due(request.form["due"]),pid))
        else:
            abort(400)
        if changed.rowcount:
            db.execute("INSERT INTO job_events(post_id,state,note) SELECT id,state,%s FROM posts WHERE id=%s",(request.form["action"],pid))
        flash("Jadwal diperbarui." if changed.rowcount else "Postingan sudah diproses.")
    return redirect("/kalender")

@app.post("/editorial/<int:item>/review")
def review(item):
    if g.role not in ("owner","manager"): abort(403)
    action=request.form.get("action")
    note=request.form.get("note","").strip()
    if action not in ("approve","revise") or len(note)>2000 or (action=="revise" and not note): abort(400)
    with connect() as db:
        row=db.execute("SELECT stage FROM editorial WHERE id=%s FOR UPDATE",(item,)).fetchone()
        if not row or row["stage"]!="Diajukan": abort(409)
        stage="Terjadwal" if action=="approve" else "Perlu Revisi"
        if action=="approve" and not db.execute("SELECT 1 FROM posts WHERE editorial_id=%s AND state='Diajukan'",(item,)).fetchone():
            flash("Semua tujuan sudah dibatalkan. Minta revisi untuk memilih akun baru.")
            return redirect("/studio/draf")
        if action=="approve":
            history(db,item,"Disetujui",note)
        jobs=db.execute("UPDATE posts SET state=%s WHERE editorial_id=%s AND state='Diajukan' RETURNING id",
            (stage if action=="approve" else "Dibatalkan",item)).fetchall()
        for job in jobs:
            db.execute("INSERT INTO job_events(post_id,state,note) VALUES(%s,%s,%s)",(job["id"],stage,note))
        db.execute("UPDATE editorial SET stage=%s WHERE id=%s",("Dipakai" if action=="approve" else stage,item))
        history(db,item,stage,note)
    return redirect("/studio/draf")


@app.post("/editorial/<int:item>/copy")
def copy_material(item):
    with connect() as db:
        row=db.execute("INSERT INTO editorial(body,asset,composer,stage) SELECT body,asset,composer-'due','Draf' FROM editorial WHERE id=%s RETURNING id",(item,)).fetchone()
        if not row: abort(404)
    return redirect(f"/buat?draft={row['id']}")


def validate_public_workspace(wid):
    with raw_connection() as db:
        if not db.execute("SELECT 1 FROM public.workspaces WHERE id=%s",(wid,)).fetchone(): abort(404)


def public_media_url(pid, kind="media"):
    origin=os.getenv("SOCIAL_ORIGIN","").rstrip("/")
    expires=int(time.time())+3600
    wid=worker_workspace.get()
    signature=hmac.new(app.secret_key.encode(),f"publish:{wid}:{kind}:{pid}:{expires}".encode(),hashlib.sha256).hexdigest()
    return f"{origin}/w/{wid}/publish-media/{kind}/{pid}/{expires}/{signature}"


@app.route("/w/<int:wid>/publish-media/<any(media,cover):kind>/<int:pid>/<int:expires>/<signature>", methods=["GET","HEAD"])
@app.route("/publish-media/<any(media,cover):kind>/<int:pid>/<int:expires>/<signature>", methods=["GET","HEAD"])
def publish_media(kind,pid,expires,signature,wid=1):
    validate_public_workspace(wid)
    prefix=f"publish:{wid}" if "wid" in request.view_args else "publish"
    expected=hmac.new(app.secret_key.encode(),f"{prefix}:{kind}:{pid}:{expires}".encode(),hashlib.sha256).hexdigest()
    if expires < time.time() or not hmac.compare_digest(expected,signature): abort(404)
    with connect() as db:
        row=db.execute("SELECT photo,cover FROM posts WHERE id=%s AND oauth_id IS NOT NULL AND state IN ('Mengirim','Terbit','Diproses platform')",(pid,)).fetchone()
    field="cover" if kind=="cover" else "photo"
    if not row or not row[field]: abort(404)
    from io import BytesIO
    from flask import send_file
    media=bytes(row[field])
    response=send_file(BytesIO(media),mimetype=multi_publish.mime(media),conditional=True,max_age=0)
    response.headers["Cache-Control"]="private, no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response


def deliver():
    with connect() as db:
        item=db.execute("""SELECT p.*,c.platform,c.guild,public.pgp_sym_decrypt(c.token,%s) AS secret FROM posts p
          LEFT JOIN channels c ON c.id=p.channel WHERE state='Terjadwal' AND due<=now()
          ORDER BY due,p.id LIMIT 1 FOR UPDATE OF p SKIP LOCKED""",(app.secret_key,)).fetchone()
        if not item:
            return False
        db.execute("UPDATE posts SET state='Mengirim',claimed_at=now() WHERE id=%s",(item["id"],))
        db.execute("INSERT INTO job_events(post_id,state) VALUES(%s,'Mengirim')",(item["id"],))
    data={"chat_id":item["channel"]}
    link=None
    note=None
    try:
        if item["oauth_id"] is not None:
            with connect() as db:
                account=db.execute("""SELECT *,public.pgp_sym_decrypt(credential,%s) AS secret FROM oauth_accounts
                    WHERE id=%s AND publish_ready FOR UPDATE""",(app.secret_key,item["oauth_id"])).fetchone()
                if not account: raise ValueError("Akun OAuth dilepas atau perlu disambungkan ulang.")
                credentials=json.loads(account["secret"])
                if account["expires_at"] and account["expires_at"] <= datetime.now(timezone.utc)+timedelta(minutes=2):
                    old_refresh=credentials.get("refresh_token")
                    credentials=social_oauth.refresh(account["platform"],credentials)
                    lifetime=int(credentials.get("expires_in",3600))
                    # Some providers rotate a refresh token shared by several selected boards/channels.
                    db.execute("""UPDATE oauth_accounts SET credential=public.pgp_sym_encrypt(%s,%s),
                        expires_at=now()+%s*interval '1 second',refreshable=%s
                        WHERE platform=%s AND (id=%s OR (public.pgp_sym_decrypt(credential,%s)::jsonb->>'refresh_token')=%s)""",
                        (json.dumps(credentials),app.secret_key,lifetime,bool(credentials.get("refresh_token")),
                         account["platform"],account["id"],app.secret_key,old_refresh))
            media=bytes(item["photo"] or b"")
            url=public_media_url(item["id"]) if media and account["platform"] in {"instagram","threads"} else None
            state,link,note=multi_publish.publish(account["platform"],account["external_id"],credentials,item["body"],media,url,public_media_url(item["id"],"cover") if item["cover"] else None,item["publish_options"])
        elif item["platform"]=="Discord":
            payload={"content":item["body"],"allowed_mentions":{"parse":[]}}
            sent=discord_request(discord_url(item["secret"]),payload=payload,photo=bytes(item["photo"] or b""))
            link=f"https://discord.com/channels/{item['guild']}/{sent['channel_id']}/{sent['id']}"
        elif item["platform"] == "Telegram":
            if item["photo"]:
                data["caption"]=item["body"]
                media=bytes(item["photo"])
                video=multi_publish.media_kind(media)=="video"
                sent=telegram(item["secret"],"sendVideo" if video else "sendPhoto",data,
                              {"video" if video else "photo":("video.mp4" if video else "foto",media)})
            else:
                data["text"]=item["body"]
                sent=telegram(item["secret"],"sendMessage",data)
            chat = sent["chat"]
            path = chat.get("username")
            if not path and chat.get("type") in {"channel", "supergroup"}:
                channel_id = str(chat["id"])
                if channel_id.startswith("-100"):
                    path = "c/" + channel_id.removeprefix("-100")
            if path:
                link = f"https://t.me/{path}/{sent['message_id']}"
        else:
            raise ValueError("Konektor akun ini belum mendukung publikasi.")
        if item["oauth_id"] is None: state="Terbit"
    except ValueError as err:
        state,note="Gagal",str(err)
    except RuntimeError as err:
        state,note="Periksa channel",str(err)
    except (KeyError,TypeError,AttributeError):
        state,note="Periksa channel","Respons API tidak dikenali; cek platform sebelum ulang."
    with connect() as db:
        db.execute("UPDATE posts SET state=%s,note=%s,link=%s WHERE id=%s",(state,note,link,item["id"]))
        db.execute("INSERT INTO job_events(post_id,state,note) VALUES(%s,%s,%s)",(item["id"],state,note))
    return True


from workspace_views import register
register(app, connect, prepare_schema, record_event)
service_desk.register(app,connect)
workflows.register(app,connect)
reports.register(app,connect)


if __name__=="__main__":
    last_ping=0
    while True:
        with raw_connection() as registry:
            spaces=registry.execute("SELECT id FROM public.workspaces ORDER BY id").fetchall()
        ping=time.monotonic()-last_ping >= 15
        worked=False
        for space in spaces:
            worker_workspace.set(space["id"])
            if ping:
                with connect() as db:
                    db.execute("""UPDATE posts SET state='Periksa channel',note='Worker terhenti; periksa platform sebelum mengirim ulang.'
                        WHERE state='Mengirim' AND (claimed_at IS NULL OR claimed_at < now()-interval '30 minutes')""")
                    db.execute("""INSERT INTO worker_status VALUES (1,now())
                               ON CONFLICT(id) DO UPDATE SET seen=excluded.seen""")
            worked = deliver() or worked
            worked = workflows.process(connect,app.secret_key) or worked
        if ping:
            last_ping=time.monotonic()
        if not worked:
            time.sleep(3)

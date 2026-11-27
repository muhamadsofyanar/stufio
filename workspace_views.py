"""Workspace administration and provider-backed activity."""
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import csv
import io
import json
import os

from flask import Response, abort, flash, g, redirect, render_template, request
from werkzeug.security import generate_password_hash

import meta_activity
from social_oauth import api


def register(app, connect, prepare_schema, record_event):
    @app.route("/pengaturan", methods=["GET", "POST"])
    def settings():
        with connect() as db:
            if request.method == "POST":
                action = request.form.get("action")
                if action in {"rename", "create"}:
                    name = request.form.get("name", "").strip()
                    if not 1 <= len(name) <= 100:
                        abort(400)
                    if action == "create":
                        if g.role != "owner":
                            abort(403)
                        wid = db.execute("INSERT INTO public.workspaces(name) VALUES(%s) RETURNING id", (name,)).fetchone()["id"]
                        record_event(db, "Buat workspace", wid)
                        prepare_schema(db, wid)
                    else:
                        db.execute("UPDATE public.workspaces SET name=%s WHERE id=%s", (name, g.workspace_id))
                elif action in {"member", "remove"}:
                    login = request.form.get("login", "").strip().casefold()
                    if not 1 <= len(login) <= 120:
                        abort(400)
                    user = db.execute("SELECT id FROM public.studio_users WHERE login=%s", (login,)).fetchone()
                    if action == "remove":
                        if user:
                            db.execute("DELETE FROM public.memberships WHERE member=%s AND workspace=%s", (user["id"], g.workspace_id))
                    else:
                        role = request.form.get("role")
                        if role not in {"viewer", "editor", "manager"}:
                            abort(400)
                        if not user:
                            password = request.form.get("password", "")
                            if not 12 <= len(password) <= 256:
                                flash("Pengguna baru memerlukan kata sandi 12–256 karakter.")
                                return redirect("/pengaturan")
                            user = db.execute("""INSERT INTO public.studio_users(login,password_hash) VALUES(%s,%s)
                                ON CONFLICT(login) DO NOTHING RETURNING id""", (login, generate_password_hash(password))).fetchone()
                            if not user:
                                abort(409)
                        db.execute("""INSERT INTO public.memberships VALUES(%s,%s,%s)
                            ON CONFLICT(workspace,member) DO UPDATE SET role=excluded.role""", (g.workspace_id,user["id"],role))
                else:
                    abort(400)
                if action != "create":
                    record_event(db, action, login if action in {"member", "remove"} else g.workspace_id)
                flash("Pengaturan tersimpan.")
                return redirect("/pengaturan")
            events = db.execute("SELECT * FROM admin_events ORDER BY id DESC LIMIT 50").fetchall()
            members = db.execute("""SELECT login,role FROM public.memberships JOIN public.studio_users ON member=id
                WHERE workspace=%s ORDER BY login""", (g.workspace_id,)).fetchall()
        return render_template("studio.html", page="pengaturan", members=members, events=events)

    @app.route("/aktivitas/<any(inbox,analitik):page>")
    def activity(page):
        state = request.args.get("status","all")
        if state not in ("all","pending","done"):
            abort(400)
        aid=request.args.get("account",type=int)
        query=request.args.get("q","").strip()[:160]
        stream=request.args.get("stream","all")
        if stream not in ("all","comments","messages"): abort(400)
        today=datetime.now(ZoneInfo("Asia/Jakarta")).date()
        try:
            start=date.fromisoformat(request.args.get("start") or str(today-timedelta(days=29)))
            end=date.fromisoformat(request.args.get("end") or str(today))
        except ValueError:
            abort(400)
        if start>end: abort(400)
        with connect() as db:
            history=db.execute("""SELECT m.day,o.title,m.metric,m.value FROM metric_days m JOIN oauth_accounts o ON o.id=m.account
                WHERE day BETWEEN %s AND %s AND (%s::bigint IS NULL OR account=%s)
                ORDER BY day DESC,o.title,m.metric LIMIT 1000""",(start,end,aid,aid)).fetchall() if page=="analitik" else []
            rows = db.execute("""SELECT a.*, o.title,o.platform FROM activity a JOIN oauth_accounts o ON o.id=a.account
                WHERE a.kind=%s AND (%s::bigint IS NULL OR a.account=%s)
                AND strpos(lower(a.label||' '||a.body||' '||o.title),lower(%s))>0
                AND (%s='all' OR (%s='messages')=(o.platform='facebook')) AND (%s='all' OR (%s='done' AND a.reply_state='Terbalas')
                OR (%s='pending' AND a.reply_state IS DISTINCT FROM 'Terbalas'))
                ORDER BY a.observed DESC,a.external_id LIMIT 300""", (page,aid,aid,query,stream,stream,state,state,state)).fetchall()
            accounts = db.execute("SELECT id,title,platform FROM oauth_accounts WHERE active AND (platform IN ('youtube','facebook','instagram') OR (platform='threads' AND %s='inbox')) ORDER BY title", (page,)).fetchall()
        if page == "analitik" and request.args.get("format") == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Akun", "Metrik", "Nilai", "Waktu sinkronisasi"])
            for row in rows:
                title = row["title"]
                writer.writerow([("'" if title.lstrip().startswith(("=", "+", "-", "@")) else "") + title, row["label"], row["body"], row["observed"]])
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=stufio-report.csv"})
        return render_template("studio.html", page=page, rows=rows, history=history,start=start,end=end,stream=stream,selected_state=state, sync_accounts=accounts, reply_enabled={key:os.getenv(flag)=="1" for key,flag in meta_activity.COMMENT_FLAGS.items()})

    @app.post("/aktivitas/<any(inbox,analitik):page>/<int:aid>/sync")
    def sync_activity(page, aid):
        try:
            with connect() as db:
                account = db.execute("""SELECT external_id,platform,public.pgp_sym_decrypt(credential,%s) AS credentials
                    FROM oauth_accounts WHERE active AND id=%s AND platform IN ('facebook','youtube','instagram','threads') FOR UPDATE""", (app.secret_key,aid)).fetchone()
                if not account:
                    abort(404)
                credentials = json.loads(account["credentials"])
                headers = {"Authorization":"Bearer " + credentials["access_token"]}
                channel = account["external_id"]
                platform = account["platform"]
                if page=="analitik" and platform in ("instagram","facebook"):
                    items = meta_activity.stats(platform,channel,credentials,headers)
                elif page=="inbox" and platform in ("instagram","threads"):
                    items = meta_activity.comments(platform,channel,credentials,headers)
                elif platform=="threads":
                    abort(404)
                elif platform == "facebook":
                    if page != "inbox": abort(404)
                    data = api("GET", f"https://graph.facebook.com/v25.0/{channel}/conversations", headers=headers,
                               params={"platform":"messenger","fields":"id,participants,messages.limit(1){id,from,message,created_time}","limit":50})
                    items = []
                    for thread in data["data"]:
                        for msg in thread.get("messages", {}).get("data", []):
                            items.append((msg["id"], msg.get("from", {}).get("name", "Messenger"), msg.get("message") or "Lampiran", None, msg.get("from",{}).get("id") if msg.get("from",{}).get("id")!=channel else None))
                elif page == "inbox":
                    data = api("GET", "https://www.googleapis.com/youtube/v3/commentThreads", headers=headers,
                               params={"part":"snippet","allThreadsRelatedToChannelId":channel,"textFormat":"plainText","order":"time","maxResults":100})
                    items = []
                    for entry in data["items"]:
                        snippet = entry["snippet"]["topLevelComment"]["snippet"]
                        items.append((entry["id"], snippet["authorDisplayName"], snippet["textDisplay"], entry["snippet"].get("videoId"),entry["snippet"]["topLevelComment"].get("id")))
                else:
                    data = api("GET", "https://www.googleapis.com/youtube/v3/channels", headers=headers, params={"part":"statistics","id":channel})
                    if not data["items"]:
                        raise ValueError("Channel tidak ditemukan.")
                    metrics = data["items"][0]["statistics"]
                    items = [(k,k,str(metrics[k]),None,None) for k in ("viewCount","subscriberCount","videoCount") if k in metrics and not (k=="subscriberCount" and metrics.get("hiddenSubscriberCount"))]
                if page=="analitik":
                    db.execute("DELETE FROM activity WHERE account=%s AND kind=%s", (aid,page))
                    for metric, _, value, _, _ in items:
                        db.execute("""INSERT INTO metric_days(account,day,metric,value)
                            VALUES(%s,(now() AT TIME ZONE 'Asia/Jakarta')::date,%s,%s)
                            ON CONFLICT(account,day,metric) DO UPDATE SET value=excluded.value""",(aid,metric,value))
                for external_id, label, body, video, reply_to in items:
                    db.execute("""INSERT INTO activity(account,kind,external_id,label,body,video,reply_to) VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(account,kind,external_id) DO UPDATE SET label=excluded.label,body=excluded.body,observed=now(),video=excluded.video,reply_to=excluded.reply_to""",
                               (aid,page,external_id,label,body,video,reply_to))
                db.execute("UPDATE oauth_accounts SET synced_at=now(),sync_result=%s WHERE id=%s", (f"{page}: berhasil ({len(items)} item)", aid))
            flash(f"{len(items)} item disinkronkan.")
        except (ValueError, KeyError, IndexError, TypeError) as err:
            with connect() as db:
                db.execute("UPDATE oauth_accounts SET sync_result=%s WHERE id=%s AND active", (f"{page}: gagal", aid))
            flash(str(err) if isinstance(err, ValueError) else "Respons platform belum dapat dibaca. Periksa koneksi akun.")
        return redirect("/aktivitas/" + page)

    @app.post("/aktivitas/inbox/reply/<int:aid>")
    def reply(aid):
        item = request.form.get("item","")
        body = request.form.get("body","").strip()
        if not 1 <= len(body) <= 2000:
            abort(400)
        with connect() as db:
            row = db.execute("""SELECT a.reply_to,o.platform,o.external_id,public.pgp_sym_decrypt(o.credential,%s) AS credential
                FROM activity a JOIN oauth_accounts o ON o.id=a.account WHERE o.active AND a.account=%s AND a.kind='inbox'
                AND a.external_id=%s AND a.reply_state IS NULL AND a.reply_to IS NOT NULL FOR UPDATE OF a""",
                (app.secret_key,aid,item)).fetchone()
            if not row:
                abort(409)
            flag = meta_activity.COMMENT_FLAGS.get(row["platform"])
            if not flag or os.getenv(flag)!="1":
                abort(403)
            db.execute("UPDATE activity SET reply_state='Periksa platform',reply_body=%s WHERE account=%s AND kind='inbox' AND external_id=%s", (body,aid,item))
        credentials = json.loads(row["credential"])
        headers = {"Authorization":"Bearer "+credentials["access_token"]}
        try:
            if row["platform"] in ("instagram","threads"):
                confirmed=meta_activity.reply(row["platform"],row["external_id"],row["reply_to"],body,credentials,headers)
            elif row["platform"]=="youtube":
                result=api("POST","https://www.googleapis.com/youtube/v3/comments",headers=headers,params={"part":"snippet"},
                           json={"snippet":{"parentId":row["reply_to"],"textOriginal":body}})
                confirmed=result.get("id")
            else:
                result=api("POST",f"https://graph.facebook.com/v25.0/{row['external_id']}/messages",headers=headers,
                           json={"recipient":{"id":row["reply_to"]},"messaging_type":"RESPONSE","message":{"text":body}})
                confirmed=result.get("message_id")
        except ValueError as err:
            flash(str(err))
            confirmed=False
        if confirmed:
            with connect() as db:
                db.execute("UPDATE activity SET reply_state='Terbalas' WHERE account=%s AND kind='inbox' AND external_id=%s",(aid,item))
        return redirect("/aktivitas/inbox")

    @app.get("/feed")
    def feed():
        query=request.args.get("q","").strip()[:160]
        order=request.args.get("order","TOP")
        media=request.args.get("media","")
        if order not in ("TOP","RECENT") or media not in ("","TEXT_POST","IMAGE","VIDEO"): abort(400)
        enabled=os.getenv("THREADS_FEED_ENABLED")=="1"
        results=[]
        with connect() as db:
            accounts=db.execute("SELECT id,title FROM oauth_accounts WHERE active AND platform='threads' ORDER BY title,id").fetchall()
            if query and enabled and accounts:
                row=db.execute("""SELECT public.pgp_sym_decrypt(credential,%s) AS token FROM oauth_accounts WHERE active AND platform='threads' AND id=%s""",
                    (app.secret_key,request.args.get("account",type=int) or accounts[0]["id"])).fetchone()
                if not row: abort(404)
                try:
                    data=api("GET","https://graph.threads.net/v1.0/keyword_search",
                        headers={"Authorization":"Bearer "+json.loads(row["token"])["access_token"]},
                        params={"q":query,"search_type":order,"fields":"id,username,text,media_type,permalink,timestamp"})
                    results=[r for r in data["data"] if not media or r.get("media_type")==media]
                except (KeyError,ValueError,TypeError):
                    flash("Pencarian gagal. Periksa izin pencarian Threads dan koneksi akun.")
        return render_template("studio.html",page="feed",feed_accounts=accounts,enabled=enabled,results=results)

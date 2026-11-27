"""Workspace-scoped customer service and Messenger conversation history."""
import workflows
import integrations
import json
import os
import secrets
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import abort, flash, g, redirect, render_template, request, session, url_for
from social_oauth import api


MESSAGE_FIELDS = "id,from,message,created_time,attachments{id,name,mime_type,image_data,video_data,file_url}"


def migrate(db, wid):
    if db.execute("SELECT 1 FROM public.workspace_migrations WHERE workspace=%s AND version=2",(wid,)).fetchone():
        return
    db.execute("""
        CREATE TABLE desk_policy(id int PRIMARY KEY, routing boolean DEFAULT false,
            last_agent bigint DEFAULT 0, opens time DEFAULT '09:00', closes time DEFAULT '17:00');
        INSERT INTO desk_policy(id) VALUES(1);
        CREATE TABLE desk_agents(member bigint PRIMARY KEY REFERENCES public.studio_users, department text NOT NULL);
        CREATE TABLE desk_pages(account bigint PRIMARY KEY REFERENCES oauth_accounts, after_cursor text);
        CREATE TABLE desk_contacts(id bigserial PRIMARY KEY, account bigint NOT NULL REFERENCES oauth_accounts,
            external_id text NOT NULL, name text NOT NULL, notes text NOT NULL DEFAULT '', UNIQUE(account,external_id));
        CREATE TABLE desk_threads(id bigserial PRIMARY KEY, contact bigint NOT NULL REFERENCES desk_contacts,
            remote_id text NOT NULL, older_cursor text, owner_id bigint REFERENCES public.studio_users, tags text DEFAULT '',
            resolved timestamptz, last_message timestamptz, UNIQUE(contact,remote_id));
        CREATE TABLE desk_messages(id bigserial PRIMARY KEY, thread bigint NOT NULL REFERENCES desk_threads,
            remote_id text, sent_at timestamptz NOT NULL DEFAULT now(), outbound boolean NOT NULL,
            body text NOT NULL, attachments jsonb NOT NULL DEFAULT '[]', state text NOT NULL,
            nonce text UNIQUE, UNIQUE(thread,remote_id));
        CREATE INDEX desk_message_history ON desk_messages(thread,sent_at,id);
        CREATE TABLE desk_events(id bigserial PRIMARY KEY, thread bigint NOT NULL REFERENCES desk_threads,
            happened timestamptz NOT NULL DEFAULT now(), actor text NOT NULL, detail text NOT NULL,
            recipient bigint REFERENCES public.studio_users, seen boolean NOT NULL DEFAULT false);
        CREATE TABLE desk_replies(id bigserial PRIMARY KEY, body text NOT NULL UNIQUE);
        ALTER TABLE activity ADD COLUMN followup text NOT NULL DEFAULT 'Terbuka';
    """)
    db.execute("INSERT INTO public.workspace_migrations VALUES(%s,2)",(wid,))


def eligible(db):
    return db.execute("""SELECT m.member,u.login,coalesce(a.department,'') AS department
        FROM public.memberships m JOIN public.studio_users u ON u.id=m.member
        LEFT JOIN desk_agents a ON a.member=m.member WHERE m.workspace=%s
        AND m.role IN ('manager','editor') ORDER BY m.member""",(g.workspace_id,)).fetchall()


def log(db, thread, detail, recipient=None, actor=None):
    actor=actor or ("Admin utama" if session.get("admin") else f"Pengguna {session['user']}")
    db.execute("INSERT INTO desk_events(thread,actor,detail,recipient) VALUES(%s,%s,%s,%s)",(thread,actor,detail,recipient))


def assign(db, thread, agent, actor=None):
    db.execute("UPDATE desk_threads SET owner_id=%s WHERE id=%s",(agent["member"],thread))
    log(db,thread,"Ditugaskan kepada "+agent["login"],agent["member"],actor)


def ingest(db, aid, page_id, thread, older=False, source="Messenger"):
    messages=thread.get("messages",{}).get("data",[])
    people=thread.get("participants",{}).get("data",[])
    customer=next((p for p in people if p.get("id") and p["id"]!=page_id),None)
    if not customer:
        customer=next((m["from"] for m in messages if m.get("from",{}).get("id") not in (None,page_id)),None)
    if not customer or not messages or not thread.get("id"):
        return
    contact=db.execute("""INSERT INTO desk_contacts(account,external_id,name) VALUES(%s,%s,%s)
        ON CONFLICT(account,external_id) DO UPDATE SET name=excluded.name RETURNING id""",
        (aid,customer["id"],customer.get("name") or customer["id"])).fetchone()["id"]
    new=db.execute("""INSERT INTO desk_threads(contact,remote_id) VALUES(%s,%s)
        ON CONFLICT DO NOTHING RETURNING id""",(contact,thread["id"])).fetchone()
    row=db.execute("SELECT * FROM desk_threads WHERE contact=%s AND remote_id=%s FOR UPDATE",(contact,thread["id"])).fetchone()
    tid=row["id"]
    paging=thread.get("messages",{}).get("paging",{})
    cursor=paging.get("cursors",{}).get("after") if paging.get("next") else None
    if new or older:
        db.execute("UPDATE desk_threads SET older_cursor=%s WHERE id=%s",(cursor,tid))
    if new:
        log(db,tid,"Percakapan diterima",actor=source)
        policy=db.execute("SELECT * FROM desk_policy WHERE id=1 FOR UPDATE").fetchone()
        agents=eligible(db) if policy["routing"] else []
        if agents:
            agent=next((a for a in agents if a["member"]>policy["last_agent"]),agents[0])
            assign(db,tid,agent,"Routing otomatis")
            db.execute("UPDATE desk_policy SET last_agent=%s WHERE id=1",(agent["member"],))
    for m in messages:
        if not m.get("id") or not m.get("from",{}).get("id"): continue
        attachments=[]
        for att in m.get("attachments",{}).get("data",[]):
            url=att.get("file_url") or att.get("image_data",{}).get("url") or att.get("video_data",{}).get("url") or ""
            attachments.append({"name":att.get("name") or att.get("mime_type") or "Lampiran",
                                "url":url if urlsplit(url).scheme=="https" else ""})
        outbound=m["from"]["id"]==page_id
        added=db.execute("""INSERT INTO desk_messages(thread,remote_id,sent_at,outbound,body,attachments,state)
            VALUES(%s,%s,coalesce(%s::timestamptz,now()),%s,%s,%s,'Tersinkron') ON CONFLICT(thread,remote_id)
            DO NOTHING RETURNING sent_at""",(tid,m["id"],m.get("created_time"),outbound,m.get("message",""),json.dumps(attachments))).fetchone()
        if added:
            timestamp=added["sent_at"]
            if source=="Messenger" and not outbound and not older and m.get("created_time"):
                workflows.capture(db,"message",aid,m["id"],m.get("message",""),timestamp,customer["id"],tid)
            db.execute("UPDATE desk_threads SET last_message=greatest(last_message,%s) WHERE id=%s",(timestamp,tid))
            if not outbound and row["resolved"] and timestamp>row["resolved"]:
                db.execute("UPDATE desk_threads SET resolved=NULL WHERE id=%s",(tid,))
                log(db,tid,"Dibuka kembali oleh pesan pelanggan",row["owner_id"],source)
                row["resolved"]=None


def register(app,connect):
    @app.post("/integrasi/<int:wid>/balaschat")
    def balaschat_webhook(wid):
        request.max_content_length = 256 * 1024
        settings = integrations.config("BALASCHAT", wid)
        raw = request.get_data()
        if not integrations.valid_signature(raw, request.headers.get("X-BalasChat-Signature", ""),
                                            settings.get("secret")):
            abort(403)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        if payload.get("event") == "webhook.test":
            return "", 204
        if payload.get("event") != "message.received" or payload.get("channel") != "waba":
            return "", 204
        try:
            workspace, number = integrations.balas_account(settings)
            if payload.get("workspace") != workspace or str(payload.get("account")) != number:
                abort(403)
            thread = integrations.waba_message(payload)
        except (ValueError, TypeError, KeyError):
            abort(400)
        with connect() as db:
            aid = db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential)
                VALUES('balaschat_waba',%s,%s,public.pgp_sym_encrypt('{}',%s))
                ON CONFLICT(platform,external_id) DO UPDATE SET title=excluded.title RETURNING id""",
                (f"{workspace}:{number}",f"WhatsApp Business · {workspace}",app.secret_key)).fetchone()["id"]
            ingest(db, aid, number, thread, source="BalasChat")
        return "", 204


    @app.post("/integrasi/<int:wid>/starsender/<secret>")
    def starsender_webhook(wid, secret):
        request.max_content_length = 256 * 1024
        settings = integrations.config("STARSENDER", wid)
        expected = settings.get("secret")
        device = settings.get("device_id")
        if not isinstance(expected, str) or len(expected) < 32 or not secrets.compare_digest(expected.encode(), secret.encode()):
            abort(403)
        if not integrations.valid_id(device):
            abort(403)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        if payload.get("device_id") is not None and str(payload["device_id"]) != device:
            abort(403)
        try:
            thread = integrations.starsender_message(payload)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            abort(400)
        if thread is None:
            return "", 204
        with connect() as db:
            aid = db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential)
                VALUES('starsender',%s,'WhatsApp · StarSender',public.pgp_sym_encrypt('{}',%s))
                ON CONFLICT(platform,external_id) DO UPDATE SET title=excluded.title RETURNING id""",
                (device,app.secret_key)).fetchone()["id"]
            ingest(db, aid, "", thread, source="StarSender")
        return "", 204

    @app.get("/layanan")
    def desk():
        selected=request.args.get("thread",type=int)
        status=request.args.get("status","all")
        if status not in ("all","open","done"): abort(400)
        with connect() as db:
            agents=eligible(db)
            accounts=db.execute("SELECT a.id,a.title,a.active,a.platform,p.after_cursor FROM oauth_accounts a LEFT JOIN desk_pages p ON p.account=a.id WHERE platform IN ('facebook','balaschat_waba','starsender') ORDER BY title").fetchall()
            query=request.args.get("q","").strip()[:160]
            account=request.args.get("account",type=int)
            rows=db.execute("""SELECT t.*,c.name,a.title,u.login FROM desk_threads t JOIN desk_contacts c ON t.contact=c.id
                JOIN oauth_accounts a ON c.account=a.id LEFT JOIN public.studio_users u ON t.owner_id=u.id
                WHERE (%s::bigint IS NULL OR c.account=%s) AND (%s='all' OR (%s='done')=(t.resolved IS NOT NULL))
                AND (strpos(lower(concat_ws(' ',c.name,c.external_id,t.tags,a.title)),lower(%s))>0 OR
                EXISTS(SELECT 1 FROM desk_messages m WHERE m.thread=t.id AND strpos(lower(m.body),lower(%s))>0))
                ORDER BY t.last_message DESC NULLS LAST,t.id DESC LIMIT 200""",(account,account,status,status,query,query)).fetchall()
            selected=selected or (rows[0]["id"] if rows else None)
            current=db.execute("""SELECT t.*,c.name,c.notes,c.external_id,c.account,a.title,a.active,a.platform,a.external_id AS device_id,u.login
                FROM desk_threads t JOIN desk_contacts c ON c.id=t.contact JOIN oauth_accounts a ON a.id=c.account
                LEFT JOIN public.studio_users u ON u.id=t.owner_id WHERE t.id=%s""",(selected,)).fetchone()
            if selected and not current: abort(404)
            messages=db.execute("SELECT * FROM desk_messages WHERE thread=%s ORDER BY sent_at,id",(selected,)).fetchall()
            events=db.execute("SELECT * FROM desk_events WHERE thread=%s ORDER BY id DESC",(selected,)).fetchall()
            replies=db.execute("SELECT * FROM desk_replies ORDER BY id").fetchall()
            policy=db.execute("SELECT * FROM desk_policy WHERE id=1").fetchone()
            reports=db.execute("""SELECT coalesce(u.login,'Belum ditugaskan') AS agent,count(*) AS total,
                count(*) FILTER(WHERE resolved IS NULL) AS opened,count(resolved) AS done
                FROM desk_threads t LEFT JOIN public.studio_users u ON u.id=t.owner_id GROUP BY 1 ORDER BY 1""").fetchall()
            notices=db.execute("SELECT * FROM desk_events WHERE recipient=%s AND NOT seen ORDER BY id DESC LIMIT 50",(session.get("user"),)).fetchall()
        local=datetime.now(ZoneInfo("Asia/Jakarta")).time()
        starsender = integrations.config("STARSENDER", g.workspace_id)
        return render_template("studio.html",page="layanan",threads=rows,current=current,messages=messages,events=events,
            agents=agents,accounts=accounts,replies=replies,policy=policy,reports=reports,notices=notices,
            office_open=policy["opens"]<=local<policy["closes"],nonce=secrets.token_urlsafe(24),
            send_enabled=os.getenv("FACEBOOK_MESSENGER_ENABLED")=="1",
            waba_enabled=bool(integrations.config("BALASCHAT", g.workspace_id).get("token")),
            starsender_device=starsender.get("device_id") if starsender.get("token") else None)

    @app.post("/layanan/pengaturan")
    def desk_settings():
        if g.role not in ("owner","manager"): abort(403)
        action=request.form.get("action")
        with connect() as db:
            if action=="policy":
                from datetime import time
                try:
                    opens=time.fromisoformat(request.form["opens"])
                    closes=time.fromisoformat(request.form["closes"])
                except ValueError: abort(400)
                if opens>=closes: abort(400)
                db.execute("UPDATE desk_policy SET routing=%s,opens=%s,closes=%s WHERE id=1",(request.form.get("routing")=="1",opens,closes))
            elif action=="department":
                member=request.form.get("member",type=int)
                if member not in {a["member"] for a in eligible(db)}: abort(400)
                dep=request.form.get("department","").strip()
                if len(dep)>100: abort(400)
                db.execute("INSERT INTO desk_agents VALUES(%s,%s) ON CONFLICT(member) DO UPDATE SET department=excluded.department",(member,dep))
            elif action=="saved":
                body=request.form.get("body","").strip()
                if not 1<=len(body)<=2000: abort(400)
                db.execute("INSERT INTO desk_replies(body) VALUES(%s) ON CONFLICT DO NOTHING",(body,))
            elif action=="remove_saved":
                db.execute("DELETE FROM desk_replies WHERE id=%s",(request.form.get("id",type=int),))
            else: abort(400)
        return redirect("/layanan")

    @app.post("/layanan/<int:tid>")
    def handle_thread(tid):
        action=request.form.get("action")
        with connect() as db:
            row=db.execute("""SELECT t.*,c.external_id,a.active,a.external_id AS page_id,
                a.id AS account,a.platform FROM desk_threads t JOIN desk_contacts c ON c.id=t.contact
                JOIN oauth_accounts a ON a.id=c.account WHERE t.id=%s FOR UPDATE OF t""",(tid,)).fetchone()
            if not row: abort(404)
            if action=="assign":
                member=request.form.get("member",type=int)
                agent=next((a for a in eligible(db) if a["member"]==member),None)
                if not agent: abort(400)
                if g.role=="editor" and row["owner_id"] not in (None,session["user"]): abort(403)
                if member!=row["owner_id"]: assign(db,tid,agent)
            elif g.role=="editor" and row["owner_id"] not in (None,session["user"]): abort(403)
            elif action in ("takeover","resume"):
                db.execute("UPDATE desk_threads SET human_control=%s WHERE id=%s",(action=="takeover",tid))
                log(db,tid,"Petugas mengambil alih" if action=="takeover" else "Otomasi dilanjutkan")
            elif action in ("resolve","open"):
                if bool(row["resolved"])!=(action=="resolve"):
                    db.execute("UPDATE desk_threads SET resolved=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s",(action=="resolve",tid))
                    log(db,tid,"Selesai" if action=="resolve" else "Dibuka kembali")
            elif action=="profile":
                notes=request.form.get("notes","").strip()
                tags=request.form.get("tags","").strip()
                if len(notes)>2000 or len(tags)>250: abort(400)
                db.execute("UPDATE desk_contacts SET notes=%s WHERE id=%s",(notes,row["contact"]))
                db.execute("UPDATE desk_threads SET tags=%s WHERE id=%s",(tags,tid))
                log(db,tid,"Profil dan tag diperbarui")
            elif action=="send":
                db.execute("UPDATE desk_threads SET human_control=true WHERE id=%s",(tid,))
                if not row["active"]: abort(403)
                is_waba = row["platform"] == "balaschat_waba"
                is_starsender = row["platform"] == "starsender"
                if is_starsender:
                    settings = integrations.config("STARSENDER", g.workspace_id)
                    if not settings.get("token") or settings.get("device_id") != row["page_id"]: abort(403)
                elif is_waba:
                    settings = integrations.config("BALASCHAT", g.workspace_id)
                    if not settings.get("token"): abort(403)
                    recent = db.execute("""SELECT 1 FROM desk_messages WHERE thread=%s AND NOT outbound
                        AND sent_at > now()-interval '24 hours' LIMIT 1""",(tid,)).fetchone()
                    if not recent:
                        flash("Balasan teks WhatsApp tersedia hingga 24 jam sejak pesan terakhir pelanggan.")
                        return redirect(url_for("desk",thread=tid))
                elif row["platform"]!="facebook" or os.getenv("FACEBOOK_MESSENGER_ENABLED")!="1":
                    abort(403)
                body=request.form.get("body","").strip()
                nonce=request.form.get("nonce","")
                if not 1<=len(body)<=2000 or not 20<=len(nonce)<=80: abort(400)
                if not (is_waba or is_starsender):
                    secret=db.execute("SELECT public.pgp_sym_decrypt(credential,%s) AS value FROM oauth_accounts WHERE id=%s AND active FOR SHARE",(app.secret_key,row["account"])).fetchone()
                    if not secret: abort(409)
                    token=json.loads(secret["value"])["access_token"]
                pending=db.execute("""INSERT INTO desk_messages(thread,nonce,outbound,body,state) VALUES(%s,%s,true,%s,'Periksa platform')
                    ON CONFLICT(nonce) DO NOTHING RETURNING id""",(tid,nonce,body)).fetchone()
                if not pending: abort(409)
            else: abort(400)
        if action=="send":
            try:
                if is_starsender:
                    integrations.send_starsender(settings, row["page_id"], row["external_id"], body)
                    with connect() as db:
                        db.execute("UPDATE desk_messages SET state='Diterima API' WHERE id=%s",(pending["id"],))
                        db.execute("UPDATE desk_threads SET last_message=greatest(last_message,now()) WHERE id=%s",(tid,))
                        log(db,tid,"Balasan diterima API StarSender")
                    return redirect(url_for("desk",thread=tid))
                if is_waba:
                    result = integrations.send_waba(settings, row["page_id"], row["external_id"], body)
                else:
                    result=api("POST",f"https://graph.facebook.com/v25.0/{row['page_id']}/messages",
                        headers={"Authorization":"Bearer "+token},json={"recipient":{"id":row["external_id"]},"messaging_type":"RESPONSE","message":{"text":body}})
                if not result.get("message_id"): raise ValueError("Pengiriman belum terkonfirmasi.")
                with connect() as db:
                    db.execute("SELECT id FROM desk_threads WHERE id=%s FOR UPDATE",(tid,))
                    db.execute("DELETE FROM desk_messages WHERE thread=%s AND remote_id=%s AND nonce IS NULL",(tid,result["message_id"]))
                    db.execute("UPDATE desk_messages SET state='Terkirim',remote_id=%s WHERE id=%s",(result["message_id"],pending["id"]))
                    db.execute("UPDATE desk_threads SET last_message=greatest(last_message,now()) WHERE id=%s",(tid,))
                    log(db,tid,"Balasan terkirim")
            except (ValueError, RuntimeError) as e: flash(str(e))
        return redirect(url_for("desk",thread=tid))

    @app.post("/layanan/<int:tid>/riwayat")
    def older_messages(tid):
        try:
            with connect() as db:
                t=db.execute("""SELECT t.remote_id,t.older_cursor,c.account,c.name,c.external_id,a.external_id AS page_id,
                    public.pgp_sym_decrypt(a.credential,%s) AS token FROM desk_threads t JOIN desk_contacts c ON c.id=t.contact
                    JOIN oauth_accounts a ON a.id=c.account WHERE t.id=%s AND a.active FOR UPDATE OF t""",(app.secret_key,tid)).fetchone()
                if not t: abort(404)
                if t["older_cursor"]:
                    data=api("GET",f"https://graph.facebook.com/v25.0/{t['remote_id']}/messages",
                        headers={"Authorization":"Bearer "+json.loads(t["token"])["access_token"]},
                        params={"fields":MESSAGE_FIELDS,"limit":50,"after":t["older_cursor"]})
                    if not data.get("data"):
                        db.execute("UPDATE desk_threads SET older_cursor=NULL WHERE id=%s",(tid,))
                    else:
                        ingest(db,t["account"],t["page_id"],{"id":t["remote_id"],"participants":{"data":[{"id":t["external_id"],"name":t["name"]}]},"messages":data},older=True)
        except ValueError as e: flash(str(e))
        return redirect(url_for("desk",thread=tid))

    @app.post("/layanan/notifikasi")
    def read_notices():
        with connect() as db:
            db.execute("UPDATE desk_events SET seen=true WHERE recipient=%s",(session.get("user"),))
        return redirect("/layanan")

    @app.post("/komentar/<int:aid>/status")
    def comment_status(aid):
        state=request.form.get("state")
        if state not in ("Terbuka","Selesai"): abort(400)
        with connect() as db:
            updated=db.execute("""UPDATE activity SET followup=%s FROM oauth_accounts o WHERE o.id=activity.account
                AND o.platform<>'facebook' AND account=%s AND kind='inbox' AND activity.external_id=%s""",
                (state,aid,request.form.get("item","")))
            if not updated.rowcount: abort(404)
        return redirect("/aktivitas/inbox?stream=comments")

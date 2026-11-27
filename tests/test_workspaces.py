"""Run only in an explicitly provisioned, disposable PostgreSQL database."""
import io
import os
import secrets
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


@unittest.skipUnless(os.getenv("STUFIO_TEST_DATABASE") == "1", "requires disposable PostgreSQL")
class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as studio
        cls.studio = studio
        studio.app.testing = True

    def setUp(self):
        self.client = self.studio.app.test_client()
        self.client.get("/login")
        self.post("/login", password=os.environ["ADMIN_PASSWORD"])
        with self.studio.raw_connection() as db:
            self.space = db.execute("INSERT INTO public.workspaces(name) VALUES('Test') RETURNING id").fetchone()["id"]
            self.studio.prepare_schema(db, self.space)
        self.post("/workspace/switch", workspace=self.space)

    def post(self, path, **form):
        with self.client.session_transaction() as session:
            form.setdefault("csrf", session["csrf"])
        return self.client.post(path, data=form)

    def test_pages_and_isolation(self):
        for path in ("/", "/akun", "/buat", "/kalender", "/terbit", "/studio/draf", "/studio/ide", "/studio/media", "/tautan", "/pengaturan", "/aktivitas/inbox", "/aktivitas/analitik"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.post("/media", photo=(io.BytesIO(b"\x89PNG\r\n\x1a\nfixture"), "example.png"))
        self.post("/buat", body="draft fixture", asset=1, nonce=secrets.token_urlsafe(), action="draft")
        self.assertIn(b"draft fixture", self.client.get("/buat?draft=1").data)
        self.post("/buat", body="revised draft", draft=1, asset=1, nonce=secrets.token_urlsafe(), action="draft")
        self.assertIn(b"revised draft", self.client.get("/studio/draf").data)
        with self.client.session_transaction() as sess:
            previous = sess["csrf"]
        self.post("/workspace/switch", workspace=1)
        self.assertEqual(self.post("/ide", csrf=previous, body="stale").status_code, 403)
        self.assertEqual(self.client.get(f"/media/1?ws={self.space}").status_code, 409)
        self.assertNotIn(b"revised draft", self.client.get("/studio/draf").data)

    def test_role_and_membership(self):
        login = secrets.token_hex(12)
        self.post("/pengaturan", action="member", login=login, password="temporary-password", role="viewer")
        self.post("/logout")
        self.client.get("/login")
        self.post("/login", login=login, password="temporary-password")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/pengaturan").status_code, 403)
        self.assertEqual(self.post("/buat", body="blocked").status_code, 403)
        self.assertEqual(self.post("/workspace/switch", workspace=1).status_code, 403)
        with self.studio.raw_connection() as db:
            db.execute("UPDATE public.memberships SET role='editor' WHERE workspace=%s", (self.space,))
        self.assertEqual(self.post("/ide", body="editor", stage="Ide").status_code,302)
        self.assertEqual(self.post("/akun").status_code,403)
        with self.studio.raw_connection() as db:
            db.execute("DELETE FROM public.memberships WHERE workspace=%s", (self.space,))
        self.assertEqual(self.client.get("/").status_code,403)

    def test_queue_and_worker(self):
        token = self.studio.worker_workspace.set(self.space)
        self.addCleanup(self.studio.worker_workspace.reset, token)
        with self.studio.connect() as db:
            for cid in (-1,-2,-3):
                db.execute("INSERT INTO channels(id,title,token) VALUES(%s,%s,public.pgp_sym_encrypt('fixture',%s))", (cid,f"Channel {cid}",self.studio.app.secret_key))
        self.post("/buat", body="Hello", channel=["-1","-2","-3"], due="2099-12-01T12:00", nonce=secrets.token_urlsafe())
        self.assertFalse(self.studio.deliver())
        for pid in (1,2):
            self.post(f"/posts/{pid}", action="save", due="2020-01-01T10:00")
        self.post("/posts/3", action="cancel")
        with patch.object(self.studio, "telegram", return_value={"message_id":42,"chat":{"username":"fixture"}}) as send:
            self.assertTrue(self.studio.deliver())
            self.assertTrue(self.studio.deliver())
            self.assertFalse(self.studio.deliver())
            self.assertEqual(send.call_count,2)
        self.assertIn(b"https://t.me/fixture/42",self.client.get("/terbit").data)

    def test_oauth_and_reporting(self):
        env = {"YOUTUBE_CLIENT_ID":"test","YOUTUBE_CLIENT_SECRET":"test","SOCIAL_ORIGIN":"https://example.org"}
        credentials = {"access_token":"test","scope":"https://www.googleapis.com/auth/youtube.upload"}
        with patch.dict(os.environ,env), patch.object(self.studio.social_oauth,"exchange",return_value=credentials) as exchange, patch.object(self.studio.social_oauth,"accounts",return_value=[("channel","My channel",credentials)]):
            start=self.post("/akun/oauth/youtube")
            state=parse_qs(urlsplit(start.location).query)["state"][0]
            callback=f"/akun/oauth/youtube/callback?code=ok&state={state}"
            self.client.get(callback)
            self.client.get(callback)
            self.assertEqual(exchange.call_count,1)
            self.assertIn(b"My channel",self.client.get("/akun").data)
            start=self.post("/akun/oauth/youtube")
            state=parse_qs(urlsplit(start.location).query)["state"][0]
            self.post("/workspace/switch",workspace=1)
            self.client.get(f"/akun/oauth/youtube/callback?code=ok&state={state}")
            self.assertEqual(exchange.call_count,1)
        self.post("/workspace/switch",workspace=self.space)
        with patch("workspace_views.api",return_value={"items":[{"statistics":{"viewCount":"123"}}]}):
            self.post("/aktivitas/analitik/1/sync")
            self.assertIn(b"viewCount,123",self.client.get("/aktivitas/analitik?format=csv").data)
        with patch("workspace_views.api",return_value={"items":[{"id":"t","snippet":{"videoId":"v","topLevelComment":{"snippet":{"authorDisplayName":"Reader","textDisplay":"A comment"}}}}]}):
            self.post("/aktivitas/inbox/1/sync")
            self.assertIn(b"A comment",self.client.get("/aktivitas/inbox").data)

    def test_messenger_reply(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential)
                VALUES('facebook','123','Page',public.pgp_sym_encrypt(%s,%s))""", ('{"access_token":"fixture"}',self.studio.app.secret_key))
        response = {"data":[{"messages":{"data":[{"id":"m","message":"Hello","from":{"name":"Reader","id":"88"}}]}}]}
        with patch("workspace_views.api",return_value=response):
            self.post("/aktivitas/inbox/1/sync")
        self.assertIn(b"Reader",self.client.get("/aktivitas/inbox").data)
        self.assertEqual(self.post("/aktivitas/inbox/reply/1",item="m",body="Hi").status_code,403)
        with patch.dict(os.environ,{"FACEBOOK_MESSENGER_ENABLED":"1"}), patch("workspace_views.api",return_value={"message_id":"ok"}) as api:
            self.post("/aktivitas/inbox/reply/1",item="m",body="Hi")
            self.assertEqual(api.call_args.kwargs["json"]["recipient"],{"id":"88"})
            self.assertEqual(self.post("/aktivitas/inbox/reply/1",item="m",body="Hi").status_code,409)
        self.assertIn(b"Terbalas",self.client.get("/aktivitas/inbox").data)

    def test_public_media_and_shortlinks(self):
        token=self.studio.worker_workspace.set(self.space)
        self.addCleanup(self.studio.worker_workspace.reset,token)
        with self.studio.connect() as db:
            db.execute("""INSERT INTO posts(body,photo,due,state,oauth_id) VALUES('',%s,now(),'Mengirim',1)""",(b"\x89PNG\r\n\x1a\nfixture",))
        path=urlsplit(self.studio.public_media_url(1)).path
        guest=self.studio.app.test_client()
        self.assertEqual(guest.get(path).status_code,200)
        self.assertEqual(guest.get(path.replace(f"/w/{self.space}/","/w/1/")).status_code,404)
        self.post("/tautan",slug="uji",destination="https://example.org/campaign",title="Campaign")
        self.assertEqual(guest.get(f"/w/{self.space}/r/uji").location,"https://example.org/campaign")
        self.assertEqual(guest.get("/w/999999/r/uji").status_code,404)

    def test_atomic_multi_account_and_caption(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            for cid in (-1,-2):
                db.execute("INSERT INTO channels(id,title,token) VALUES(%s,'Fixture',public.pgp_sym_encrypt('test',%s))",(cid,self.studio.app.secret_key))
        base=dict(body="shared",due="2099-12-01T12:00")
        self.post("/buat",channel=["-1","-3"],nonce=secrets.token_urlsafe(),**base)
        self.post("/buat",channel=["-1","-2"],nonce=secrets.token_urlsafe(),**base,**{"caption_-2":"custom"})
        self.post("/akun/channel/-1/lepas")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            rows=db.execute("SELECT body,state FROM posts ORDER BY id").fetchall()
            self.assertEqual(rows,[{"body":"shared","state":"Dibatalkan"},{"body":"custom","state":"Terjadwal"}])

    def test_meta_comments_and_metrics(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            for platform in ("instagram","threads"):
                db.execute("INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES(%s,'123',%s,public.pgp_sym_encrypt(%s,%s))",
                           (platform,platform,'{"access_token":"fixture"}',self.studio.app.secret_key))
        for aid,platform in enumerate(("instagram","threads"),1):
            with patch("meta_activity.api",side_effect=[{"data":[{"id":"p"}]},{"data":[{"id":"c","text":"Message","username":"User"}]}]):
                self.post(f"/aktivitas/inbox/{aid}/sync")
            with patch.dict(os.environ,{platform.upper()+"_COMMENTS_ENABLED":"1"}),patch("meta_activity.api",side_effect=[{"id":"replied"},{"id":"published"}]) as api:
                self.post(f"/aktivitas/inbox/reply/{aid}",item="c",body="Reply")
                self.assertEqual(api.call_count,1 if platform=="instagram" else 2)
        with patch("meta_activity.api",return_value={"followers_count":241,"media_count":12}):
            self.post("/aktivitas/analitik/1/sync")
        self.assertIn(b"followers_count,241",self.client.get("/aktivitas/analitik?format=csv").data)

    def test_daily_history_and_account_search(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            for platform in ("instagram","facebook"):
                db.execute("INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES(%s,'123',%s,public.pgp_sym_encrypt(%s,%s))",
                           (platform,platform,'{"access_token":"fixture"}',self.studio.app.secret_key))
            for account in (1,2):
                db.execute("INSERT INTO activity(account,kind,external_id,label,body) VALUES(%s,'inbox','1','Reader',%s)",(account,f"post-{account}"))
        for count in (123,157):
            with patch("meta_activity.api",return_value={"followers_count":count}):
                self.post("/aktivitas/analitik/1/sync")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            self.assertEqual(db.execute("SELECT value FROM metric_days").fetchall(),[{"value":157}])
        self.assertIn(b"157",self.client.get("/aktivitas/analitik?account=1").data)
        html=self.client.get("/aktivitas/inbox?stream=messages&q=reader").data
        self.assertIn(b"post-2",html)
        self.assertNotIn(b"post-1",html)
        self.assertNotIn(b"post-2",self.client.get("/aktivitas/inbox?stream=comments").data)

    def test_feed_workspace_and_filters(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES('threads','123','Threads test',public.pgp_sym_encrypt(%s,%s))",
                       ('{"access_token":"fixture"}',self.studio.app.secret_key))
        with patch.dict(os.environ,{"THREADS_FEED_ENABLED":"1"}), patch("workspace_views.api",return_value={"data":[{"username":"Writer","text":"Public example","media_type":"IMAGE"}]}) as api:
            self.assertIn(b"Public example",self.client.get("/feed?q=test&account=1&media=IMAGE&order=RECENT").data)
            self.assertEqual(api.call_args.kwargs["params"]["search_type"],"RECENT")
            self.assertNotIn(b"Public example",self.client.get("/feed?q=test&media=VIDEO").data)
            self.assertEqual(self.client.get("/feed?q=test&account=9999").status_code,404)

    def test_disconnect_retains_history_and_cancels_only_selected_target(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db, self.space)
            for external in ("page-first", "page-second"):
                account = db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential,publish_ready)
                    VALUES('facebook',%s,'Same name',public.pgp_sym_encrypt('{"access_token":"fixture"}',%s),true)
                    RETURNING id""", (external,self.studio.app.secret_key)).fetchone()["id"]
                db.execute("INSERT INTO posts(oauth_id,body,due) VALUES(%s,'scheduled',now())",(account,))
                db.execute("INSERT INTO metric_days VALUES(%s,current_date,'followers',4)", (account,))
        page = self.client.get("/akun").data
        self.assertIn(b"page-first",page)
        self.assertIn(b"page-second",page)
        self.assertEqual(self.post("/akun/oauth/lepas/1").status_code,302)
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            states=db.execute("SELECT state FROM posts ORDER BY id").fetchall()
            self.assertEqual([row["state"] for row in states],["Dibatalkan","Terjadwal"])
            self.assertEqual(db.execute("SELECT count(*) AS n FROM metric_days").fetchone()["n"],2)
            row=db.execute("SELECT active,public.pgp_sym_decrypt(credential,%s) AS secret FROM oauth_accounts WHERE id=1",(self.studio.app.secret_key,)).fetchone()
            self.assertFalse(row["active"])
            self.assertEqual(row["secret"],"{}")
            self.assertTrue(db.execute("SELECT 1 FROM admin_events WHERE action='Lepas OAuth'").fetchone())
        self.assertEqual(self.post("/aktivitas/inbox/1/sync").status_code,404)
        self.assertIn(b"Dilepas",self.client.get("/akun").data)

    def test_sync_result_preserves_last_success_after_failure(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential)
                VALUES('youtube','channel-123','Channel',public.pgp_sym_encrypt('{"access_token":"fixture"}',%s))""",
                (self.studio.app.secret_key,))
        with patch("workspace_views.api", return_value={"items":[]}):
            self.post("/aktivitas/inbox/1/sync")
        self.assertIn(b"inbox: berhasil (0 item)",self.client.get("/akun").data)
        with patch("workspace_views.api", side_effect=ValueError("provider error")):
            self.post("/aktivitas/inbox/1/sync")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            row=db.execute("SELECT synced_at,sync_result FROM oauth_accounts WHERE id=1").fetchone()
            self.assertIsNotNone(row["synced_at"])
            self.assertEqual(row["sync_result"],"inbox: gagal")

    def seed_targets(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            for cid in (-1,-2):
                db.execute("INSERT INTO channels(id,title,token) VALUES(%s,%s,public.pgp_sym_encrypt('test',%s))",
                           (cid,f"Akun {cid}",self.studio.app.secret_key))

    def test_review_variants_revision_and_week(self):
        self.seed_targets()
        self.post("/media", photo=(io.BytesIO(b"\x89PNG\r\n\x1a\nfixture"),"foto.png"))
        self.post("/pengaturan",action="approval",enabled="1")
        form=dict(body="Materi",channel=["-1","-2"],asset="1",due="2027-02-01T08:00",
                  **{"caption_-2":"Versi dua","media_-2":"none"})
        self.post("/buat",action="draft",nonce=secrets.token_urlsafe(),**form)
        self.assertIn(b"Versi dua",self.client.get("/buat?draft=1").data)
        for action in ("revise","approve"):
            self.post("/buat",draft="1",nonce=secrets.token_urlsafe(),**form)
            self.assertIn(b"Setujui dan jadwalkan",self.client.get("/studio/draf").data)
            with self.studio.raw_connection() as db:
                self.studio.set_workspace(db,self.space)
                self.assertFalse(db.execute("SELECT 1 FROM posts WHERE state='Terjadwal'").fetchone())
            self.assertEqual(self.post("/editorial/1/review",action=action,note="Catatan").status_code,302)
        self.assertEqual(self.post("/editorial/1/review",action="approve").status_code,409)
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            rows=db.execute("SELECT body,photo IS NOT NULL AS media FROM posts WHERE state='Terjadwal' ORDER BY id").fetchall()
            self.assertEqual(rows,[{"body":"Materi","media":True},{"body":"Versi dua","media":False}])
        self.assertIn(b"Versi dua",self.client.get("/kalender?week=2027-02-03&account=-2").data)
        self.assertNotIn(b"Versi dua",self.client.get("/kalender?week=2027-02-12").data)
        self.assertEqual(self.post("/editorial/1/copy").status_code,302)

    def test_bulk_rollback_replay_and_target_retry(self):
        self.seed_targets()
        nonce=secrets.token_urlsafe()
        def upload(contents):
            return self.post("/buat",action="bulk",nonce=nonce,channel=["-1","-2"],
                             csv=(io.BytesIO(contents.encode()),"materi.csv"))
        upload("caption,due,asset\nPertama,,\nKedua,salah,")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            self.assertFalse(db.execute("SELECT 1 FROM posts").fetchone())
        for _ in range(2):
            upload("caption,due,asset\nPertama,,\nKedua,,")
        ctx=self.studio.worker_workspace.set(self.space)
        self.addCleanup(self.studio.worker_workspace.reset,ctx)
        sent={"message_id":22,"chat":{"username":"test"}}
        with patch.object(self.studio,"telegram",side_effect=[ValueError("Ditolak"),sent,sent,sent,sent]) as provider:
            for _ in range(4): self.assertTrue(self.studio.deliver())
            with self.studio.connect() as db:
                failed=db.execute("SELECT id FROM posts WHERE state='Gagal'").fetchone()["id"]
                succeeded=db.execute("SELECT id FROM posts WHERE state='Terbit' LIMIT 1").fetchone()["id"]
                event=db.execute("SELECT max(id) AS id FROM job_events WHERE post_id=%s",(failed,)).fetchone()["id"]
            self.post(f"/posts/{succeeded}",action="retry",event=event)
            self.post(f"/posts/{failed}",action="retry",event=event)
            self.assertTrue(self.studio.deliver())
            self.assertFalse(self.studio.deliver())
            self.assertEqual(provider.call_count,5)
        with self.studio.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM posts WHERE state='Terbit'").fetchone()["n"],4)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM job_events WHERE post_id=%s AND state='Mengirim'",(failed,)).fetchone()["n"],2)

    def test_desk_routing_transfer_reopen_and_isolation(self):
        for name in ("agent-a","agent-b"):
            self.post("/pengaturan",action="member",login=name,password="password-local",role="editor")
        self.post("/layanan/pengaturan",action="policy",routing="1",opens="09:00",closes="17:00")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES('facebook','page','Page A',public.pgp_sym_encrypt(%s,%s))",('{"access_token":"test"}',self.studio.app.secret_key))
        def thread(key):
            return {"id":"thread"+key,"messages":{"data":[{"id":"m"+key,"from":{"id":key,"name":"Customer "+key},"message":"Halo","created_time":"2025-01-01T08:00:00+0000"}]}}
        payload={"data":[thread("1"),thread("2")]}
        def sync():
            with patch("workspace_views.api",return_value=payload):
                self.assertEqual(self.post("/aktivitas/inbox/1/sync",desk="1").status_code,302)
        sync()
        self.assertIn(b"Customer 1",self.client.get("/layanan?thread=1").data)
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            members=[r["owner_id"] for r in db.execute("SELECT owner_id FROM desk_threads ORDER BY id")]
            self.assertNotEqual(members[0],members[1])
        self.post("/layanan/1",action="assign",member=members[1])
        self.post("/layanan/1",action="profile",notes="Pelanggan lama",tags="tag-unik")
        self.post("/layanan/1",action="resolve")
        sync()
        self.assertIn(b"Customer 1",self.client.get("/layanan?status=done").data)
        payload["data"][0]["messages"]["data"].append({"id":"m-new","message":"Pesan baru","from":{"id":"1","name":"Customer 1"},"created_time":"2099-01-01T08:10:00+0000"})
        sync()
        html=self.client.get("/layanan?status=open&q=tag-unik").data
        self.assertIn(b"Dibuka kembali oleh pesan pelanggan",html)
        self.assertIn(b"Pesan baru",html)
        self.assertIn(b"Pelanggan lama",html)
        self.assertIn(b"agent-b",html)
        with patch.dict(os.environ,{"FACEBOOK_MESSENGER_ENABLED":"1"}), patch("service_desk.api",return_value={"message_id":"out1"}) as provider:
            nonce=secrets.token_urlsafe()
            self.assertEqual(self.post("/layanan/1",action="send",body="Balasan",nonce=nonce).status_code,302)
            self.assertEqual(self.post("/layanan/1",action="send",body="Balasan",nonce=nonce).status_code,409)
            self.assertEqual(provider.call_count,1)
        self.post("/workspace/switch",workspace=1)
        self.assertEqual(self.client.get("/layanan?thread=1").status_code,404)
        self.assertNotIn(b"Customer 1",self.client.get("/layanan").data)

    def test_service_paging_attachments_and_permissions(self):
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES('facebook','page','Page',
                public.pgp_sym_encrypt(%s,%s))""",('{"access_token":"test"}',self.studio.app.secret_key))
        thread={"id":"T","participants":{"data":[{"id":"page"},{"id":"C","name":"Customer"}]},
                "messages":{"data":[{"id":"m","from":{"id":"C"},"message":"Foto","created_time":"2024-01-10T00:00:00Z",
                "attachments":{"data":[{"name":"Foto pelanggan","image_data":{"url":"https://example.org/photo.jpg"}}]}}],
                "paging":{"next":"next","cursors":{"after":"older"}}}}
        with patch("workspace_views.api",return_value={"data":[thread],"paging":{"next":"next","cursors":{"after":"threads"}}}):
            self.post("/aktivitas/inbox/1/sync",desk="1")
        with patch("workspace_views.api",return_value={"data":[]}) as pages:
            self.post("/aktivitas/inbox/1/sync",desk="1",more="1")
            self.assertEqual(pages.call_args.kwargs["params"]["after"],"threads")
        self.post("/layanan/1",action="resolve")
        with patch("service_desk.api",return_value={"data":[{"id":"old","from":{"id":"C"},"message":"Pesan terdahulu","created_time":"2024-01-01T00:00:00Z"}]}) as older:
            self.post("/layanan/1/riwayat")
            self.assertEqual(older.call_args.kwargs["params"]["after"],"older")
        html=self.client.get("/layanan?status=done").data
        self.assertIn(b"Foto pelanggan",html)
        self.assertIn(b"Pesan terdahulu",html)
        self.post("/layanan/pengaturan",action="saved",body="Terima kasih")
        self.assertIn(b"Terima kasih",self.client.get("/layanan").data)
        self.post("/pengaturan",action="member",login="viewer-desk",password="test-password-12",role="viewer")
        self.post("/logout")
        self.client.get("/login")
        self.post("/login",login="viewer-desk",password="test-password-12")
        self.assertEqual(self.client.get("/layanan").status_code,200)
        self.assertEqual(self.post("/layanan/1",action="open").status_code,403)
        self.assertEqual(self.post("/layanan/pengaturan",action="saved",body="Denied").status_code,403)

    def test_final_automation_human_control_ai_and_report(self):
        import workflows
        from datetime import datetime,timezone
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            db.execute("""INSERT INTO oauth_accounts(platform,external_id,title,credential)
                VALUES('facebook','page','My Page',public.pgp_sym_encrypt(%s,%s))""",('{"access_token":"test"}',self.studio.app.secret_key))
        self.post("/otomasi",action="create",trigger="message",account="1",name="Jam layanan",keyword="jam",body="Buka jam 9")
        self.post("/otomasi",action="toggle",id="1")
        self.assertIn(b"Buka jam 9",self.post("/otomasi",action="simulate",trigger="message",account="1",sample="Jam berapa?").data)
        def sync(mid):
            payload={"data":[{"id":"thread","messages":{"data":[{"id":mid,"created_time":datetime.now(timezone.utc).isoformat(),"message":"Jam berapa?","from":{"id":"customer","name":"Customer"}}]}}]}
            with patch("workspace_views.api",return_value=payload): self.post("/aktivitas/inbox/1/sync")
        sync("m1")
        sync("m1")
        ctx=self.studio.worker_workspace.set(self.space)
        self.addCleanup(self.studio.worker_workspace.reset,ctx)
        with patch.dict(os.environ,{"FACEBOOK_MESSENGER_ENABLED":"1"}), patch("workflows.api",return_value={"message_id":"out1"}) as provider:
            self.assertTrue(workflows.process(self.studio.connect,self.studio.app.secret_key))
            self.post("/layanan/1",action="takeover")
            sync("m2")
            self.assertTrue(workflows.process(self.studio.connect,self.studio.app.secret_key))
            self.assertFalse(workflows.process(self.studio.connect,self.studio.app.secret_key))
            self.assertEqual(provider.call_count,1)
        self.post("/otomasi",action="knowledge",title="Jam kerja",body="Kami buka jam 9.")
        with patch.dict(os.environ,{"TAYSRIUL_AI_KEY":"example","TAYSRIUL_AI_MODEL":"example"}),patch("workflows.requests.post") as model:
            model.return_value.json.return_value={"choices":[{"message":{"content":'{"source_id":1,"quote":"Kami buka jam 9."}'}}]}
            self.assertIn(b"Kami buka jam 9.",self.post("/layanan/1/asisten").data)
            model.return_value.json.return_value={"choices":[{"message":{"content":'{"source_id":1,"quote":"Tidak ada di sumber"}'}}]}
            self.assertEqual(self.post("/layanan/1/asisten").status_code,302)
        self.assertIn(b"Belum tersedia",self.client.get("/laporan").data)
        self.assertIn(b"Belum ditugaskan,1,1,0,1",self.client.get("/laporan?csv=layanan").data)
        self.assertEqual(self.client.get("/laporan?start=2027-02-28&end=2027-01-01").status_code,400)

    def test_final_signed_integration_and_private_reply(self):
        import workflows,json,time,hmac,hashlib
        from datetime import datetime,timezone
        self.post("/otomasi",action="hook")
        with self.studio.raw_connection() as db:
            self.studio.set_workspace(db,self.space)
            secret=db.execute("SELECT public.pgp_sym_decrypt(hook_key::bytea,%s) AS key FROM flow_config",(self.studio.app.secret_key,)).fetchone()["key"]
            db.execute("INSERT INTO oauth_accounts(platform,external_id,title,credential) VALUES('instagram','ig','IG',public.pgp_sym_encrypt(%s,%s))",('{"access_token":"test"}',self.studio.app.secret_key))
        self.post("/otomasi",action="create",trigger="comment",keyword="info",body="Detail",name="Balas")
        self.post("/otomasi",action="toggle",id=1)
        def send(kind,payload,key):
            path=f"/integrasi/{self.space}/{kind}"
            ts=str(int(time.time()))
            raw=json.dumps(payload).encode()
            signature=hmac.new(key.encode(),ts.encode()+b"."+path.encode()+b"."+raw,hashlib.sha256).hexdigest()
            return self.client.post(path,data=raw,content_type="application/json",headers={"X-Taysriul-Time":ts,"X-Taysriul-Signature":signature})
        payload={"account":1,"comment_id":"12345","sender_id":"456","text":"info","created_time":datetime.now(timezone.utc).isoformat()}
        self.assertEqual(send("komentar",payload,"wrong").status_code,403)
        for _ in range(2): self.assertEqual(send("komentar",payload,secret).status_code,204)
        ctx=self.studio.worker_workspace.set(self.space)
        self.addCleanup(self.studio.worker_workspace.reset,ctx)
        with patch.dict(os.environ,{"INSTAGRAM_PRIVATE_REPLIES_ENABLED":"1"}),patch("workflows.api",return_value={"message_id":"dm","recipient_id":"456"}) as api:
            self.assertTrue(workflows.process(self.studio.connect,self.studio.app.secret_key))
            self.assertFalse(workflows.process(self.studio.connect,self.studio.app.secret_key))
            self.assertEqual(api.call_count,1)
        self.assertIn(b"Detail",self.client.get("/layanan?thread=1").data)
        metric={"account":1,"date":"2026-11-01","metric":"reach","value":0}
        self.assertEqual(send("metrik",metric,secret).status_code,204)
        self.assertIn(b"reach,0",self.client.get("/laporan?start=2026-11-01&end=2026-11-01&csv=metrik").data)

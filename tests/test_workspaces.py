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

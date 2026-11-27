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

import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

# Offline tests exercise constructed requests, not network credentials.
try:
    import requests
except ImportError:
    sys.modules["requests"] = types.SimpleNamespace(RequestException=Exception)
import multi_publish as mp
import social_oauth as oauth

JPG=b"\xff\xd8\xfftest"
PNG=b"\x89PNG\r\n\x1a\nabc"
MP4=b"\x00\x00\x00\x18ftypmp42"+b"x"*48
C={"access_token":"test-token"}
class Response:
    def __init__(self, data=None,headers=None):
        self.data=data or {};self.headers=headers or {}
    def json(self): return self.data

class PublishTests(unittest.TestCase):
    def test_media_and_validation(self):
        self.assertEqual(mp.media_kind(MP4),"video")
        self.assertEqual(mp.mime(PNG),"image/png")
        with self.assertRaises(ValueError): mp.validate("instagram","",PNG)
        with self.assertRaises(ValueError): mp.validate("youtube","",MP4)
        with self.assertRaises(ValueError): mp.validate("x","x"*281,b"")
        with self.assertRaises(ValueError): mp.upload_url("http://linkedin.com/",("linkedin.com",))
        with self.assertRaises(ValueError): mp.upload_url("https://fake-linkedin.com/",("linkedin.com",))
    def test_facebook_feed_photo_video(self):
        for media,endpoint,status in [(b"","feed","Terbit"),(JPG,"photos","Terbit"),(MP4,"videos","Diproses platform")]:
            with self.subTest(endpoint=endpoint),patch.object(mp,"call",return_value=Response({"id":"123"})) as call:
                result=mp.publish("facebook","42",C,"test",media)
                self.assertEqual(result[0],status)
                self.assertTrue(call.call_args.args[1].endswith("/42/"+endpoint))
    def test_instagram_direct(self):
        with patch.object(mp,"call",side_effect=[Response({"id":"container"}),Response({"status_code":"FINISHED"}),Response({"id":"published"})]) as call:
            result=mp.publish("instagram","42",{**C,"instagram_mode":"direct"},"caption",JPG,"https://example.org/media")
            self.assertEqual(result[0],"Terbit")
            self.assertIn("graph.instagram.com",call.call_args_list[0].args[1])
            self.assertTrue(call.call_args_list[-1].args[1].endswith("/media_publish"))
    def test_threads_text(self):
        with patch.object(mp,"call",side_effect=[Response({"id":"container"}),Response({"id":"post"})]) as call:
            self.assertEqual(mp.publish("threads","42",C,"text",b"")[0],"Terbit")
            self.assertTrue(call.call_args_list[-1].args[1].endswith("/threads_publish"))
    def test_youtube(self):
        with patch.object(mp,"call",return_value=Response({"id":"vid"})) as call:
            result=mp.publish("youtube","42",C,"Judul\nDeskripsi",MP4,options={"privacy":"unlisted","kids":True})
            self.assertEqual(result[0],"Diproses platform")
            self.assertIn(b'"privacyStatus": "unlisted"',call.call_args.kwargs["data"])
            self.assertIn(b'"selfDeclaredMadeForKids": true',call.call_args.kwargs["data"])
    def test_tiktok_draft(self):
        with patch.object(mp,"call",side_effect=[Response({"data":{"publish_id":"test","upload_url":"https://open-upload.tiktokapis.com/video"},"error":{"code":"ok"}}),Response()]) as call:
            self.assertEqual(mp.publish("tiktok","42",C,"caption",MP4)[0],"Draf platform")
            self.assertEqual(call.call_args.args[0],"PUT")
            self.assertNotIn("Authorization",call.call_args.kwargs["headers"])
    def test_linkedin_text(self):
        with patch.object(mp,"call",return_value=Response(headers={"x-restli-id":"urn:li:share:123"})):
            self.assertEqual(mp.publish("linkedin","42",C,"text",b"")[0],"Terbit")
    def test_linkedin_video(self):
        info={"value":{"video":"urn:li:video:1","uploadToken":"t","uploadInstructions":[{"firstByte":0,"lastByte":len(MP4)-1,"uploadUrl":"https://www.linkedin.com/upload"}]}}
        with patch.object(mp,"call",side_effect=[Response(info),Response(headers={"ETag":"part"}),Response(),Response({"status":"AVAILABLE"}),Response(headers={"x-restli-id":"urn:li:share:1"})]):
            self.assertEqual(mp.publish("linkedin","42",C,"caption",MP4)[0],"Terbit")
    def test_x_text_image_video(self):
        with patch.object(mp,"call",return_value=Response({"data":{"id":"123"}})):
            self.assertEqual(mp.publish("x","42",C,"text",b"")[0],"Terbit")
            self.assertEqual(mp.publish("x","42",C,"text",JPG)[0],"Terbit")
            self.assertEqual(mp.publish("x","42",C,"text",MP4)[0],"Terbit")
    def test_pinterest_image_and_video(self):
        with patch.object(mp,"call",return_value=Response({"id":"pin"})):
            self.assertEqual(mp.publish("pinterest","42",C,"caption",JPG)[0],"Terbit")
        info={"media_id":"99","upload_url":"https://s3.amazonaws.com/bucket","upload_parameters":{}}
        with patch.object(mp,"call",side_effect=[Response(info),Response(),Response({"status":"succeeded"}),Response({"id":"pin"})]):
            self.assertEqual(mp.publish("pinterest","42",C,"caption",MP4,cover_url="https://example.org/cover")[0],"Terbit")
    def test_missing_id_not_success(self):
        with patch.object(mp,"call",return_value=Response({})):
            with self.assertRaises(RuntimeError): mp.publish("facebook","42",C,"test",b"")
    def test_oauth_permissions(self):
        config=("id","secret","https://example.org/callback")
        url=oauth.authorization_url("facebook",config,"state","verifier")
        self.assertIn("pages_manage_posts",parse_qs(urlsplit(url).query)["scope"][0])
        with patch.dict("os.environ",{"INSTAGRAM_LOGIN_MODE":"direct"}):
            url=oauth.authorization_url("instagram",config,"state","verifier")
            self.assertIn("instagram_business_content_publish",parse_qs(urlsplit(url).query)["scope"][0])
            self.assertEqual(urlsplit(url).hostname,"www.instagram.com")
if __name__=="__main__": unittest.main()

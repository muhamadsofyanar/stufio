import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
try:
    import requests
except ImportError:
    import sys, types
    sys.modules['requests']=types.SimpleNamespace(RequestException=Exception)
import social_oauth as oauth

ENV={"SOCIAL_ORIGIN":"https://example.org","INSTAGRAM_LOGIN_MODE":"unified",
     "INSTAGRAM_CLIENT_ID":"123","INSTAGRAM_CLIENT_SECRET":"secret","INSTAGRAM_CONFIG_ID":"456"}
class UnifiedTests(unittest.TestCase):
    def test_login_preserves_state_and_config(self):
        with patch.dict(os.environ,ENV):
            config=oauth.settings("instagram")
            query=parse_qs(urlsplit(oauth.authorization_url("instagram",config,"csrf-state","test")).query)
            self.assertEqual(query["config_id"],["456"])
            self.assertEqual(query["state"],["csrf-state"])
            self.assertEqual(query["response_type"],["code"])
            self.assertNotIn("scope",query)
    def test_missing_config(self):
        with patch.dict(os.environ,{**ENV,"INSTAGRAM_CONFIG_ID":""}):
            self.assertIsNone(oauth.settings("instagram"))
    def test_exchange_not_fb_long_token(self):
        with patch.dict(os.environ,ENV),patch.object(oauth,"api",return_value={"access_token":"test"}) as call:
            self.assertEqual(oauth.exchange("instagram",oauth.settings("instagram"),"code","verifier")["instagram_mode"],"unified")
            self.assertEqual(call.call_count,1)
    def test_verified_target_and_permission(self):
        token={"access_token":"test","instagram_mode":"unified"}
        meta={"is_valid":True,"app_id":"123","scopes":["instagram_basic","instagram_content_publish"],"granular_scopes":[{"scope":"instagram_basic","target_ids":["42"]},{"scope":"instagram_content_publish","target_ids":["42"]}]}
        with patch.dict(os.environ,ENV),patch.object(oauth,"api",side_effect=[{"data":meta},{"id":"42","username":"example"}]):
            rows=oauth.accounts("instagram",token)
            self.assertEqual(rows[0][:2],("42","example"))
            self.assertTrue(rows[0][2]["can_publish"])
        with patch.dict(os.environ,ENV),patch.object(oauth,"api",return_value={"data":{"is_valid":True,"app_id":"other"}}):
            with self.assertRaises(ValueError): oauth.granted_scopes("instagram",token)
    def test_facebook_unchanged(self):
        with patch.dict(os.environ,ENV):
            query=parse_qs(urlsplit(oauth.authorization_url("facebook",("id","secret","https://example.org"),"state","v")).query)
            self.assertIn("pages_manage_posts",query["scope"][0])
            self.assertNotIn("config_id",query)
if __name__=="__main__": unittest.main()

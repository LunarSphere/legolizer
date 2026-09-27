"""Google ID token checks, auth configuration and session cookies; Google's key set is stubbed."""

import os
import time
import unittest
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from legolizer import auth

CLIENT = "client-123.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(key=KEY, **claims):
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "sub": "1234",
        "email": "ada@example.com",
        "email_verified": True,
        "given_name": "Ada",
        "picture": "https://lh3.googleusercontent.com/a/ada",
        "iat": now,
        "exp": now + 3600,
        **claims,
    }
    payload = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "k1"})


class VerifyGoogleTests(unittest.TestCase):
    def setUp(self):
        self.certs = mock.Mock()
        self.certs.get_signing_key_from_jwt.return_value = mock.Mock(key=KEY.public_key())
        for patch in (
            mock.patch.object(auth, "_certs", self.certs),
            mock.patch.dict(os.environ, {"LEGOLIZER_GOOGLE_CLIENT_ID": CLIENT}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_valid_token_yields_a_profile_keyed_on_the_google_subject(self):
        claims = auth.verify_google(google_token())
        self.assertEqual(
            auth.profile(claims),
            {
                "id": "google-1234",
                "email": "ada@example.com",
                "name": "Ada",
                "picture": "https://lh3.googleusercontent.com/a/ada",
            },
        )
        self.assertEqual(
            auth.profile({"sub": "9"}),
            {"id": "google-9", "email": "", "name": "Builder", "picture": None},
        )

    def test_rejects_other_apps_issuers_expired_unverified_and_forged_tokens(self):
        forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tokens = {
            "audience": google_token(aud="someone-else"),
            "issuer": google_token(iss="https://evil.test"),
            "expired": google_token(exp=int(time.time()) - 120),
            "unverified": google_token(email_verified=False),
            "no subject": google_token(sub=None),
            "forged": google_token(key=forger),
            "garbage": "not-a-jwt",
        }
        for reason, token in tokens.items():
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                auth.verify_google(token)

    def test_unknown_key_is_rejected_and_an_outage_is_reported(self):
        self.certs.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("no key")
        with self.assertRaises(ValueError):
            auth.verify_google(google_token())
        self.certs.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("down")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            auth.verify_google(google_token())

    def test_needs_a_client_id(self):
        with mock.patch.dict(os.environ, {"LEGOLIZER_GOOGLE_CLIENT_ID": ""}):
            with self.assertRaisesRegex(RuntimeError, "LEGOLIZER_GOOGLE_CLIENT_ID"):
                auth.verify_google(google_token())

    def test_google_key_set_client_is_created_once(self):
        with (
            mock.patch.object(auth, "_certs", None),
            mock.patch("jwt.PyJWKClient") as client,
        ):
            client.return_value.get_signing_key_from_jwt.return_value = mock.Mock(
                key=KEY.public_key()
            )
            auth.verify_google(google_token())
            auth.verify_google(google_token())
        client.assert_called_once_with(auth.GOOGLE_CERTS, cache_keys=True, timeout=10)


class ConfigurationTests(unittest.TestCase):
    def test_mode_defaults_to_off_and_google_needs_a_client_id(self):
        cases = [
            ({}, "off", None),
            ({"LEGOLIZER_AUTH": "Google", "LEGOLIZER_GOOGLE_CLIENT_ID": CLIENT}, "google", None),
            ({"LEGOLIZER_AUTH": "google"}, "google", "needs LEGOLIZER_GOOGLE_CLIENT_ID"),
        ]
        for env, mode, problem in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(auth.mode(), mode)
                if problem:
                    self.assertIn(problem, auth.configuration_problem())
                else:
                    self.assertIsNone(auth.configuration_problem())

    def test_admins_are_listed_by_email_ignoring_case_and_spaces(self):
        with mock.patch.dict(
            os.environ, {"LEGOLIZER_ADMIN_EMAILS": " Ada@Example.com , ,bob@x.io"}
        ):
            self.assertTrue(auth.is_admin_email("ada@example.com"))
            self.assertTrue(auth.is_admin_email(" BOB@X.IO"))
            self.assertFalse(auth.is_admin_email("eve@example.com"))
            self.assertFalse(auth.is_admin_email(""))
            self.assertFalse(auth.is_admin_email(None))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(auth.is_admin_email("ada@example.com"))

    def test_unknown_mode_is_a_configuration_problem(self):
        with mock.patch.dict(os.environ, {"LEGOLIZER_AUTH": "cognito"}):
            with self.assertRaises(RuntimeError):
                auth.mode()
            self.assertIn("off or google", auth.configuration_problem())


class CookieTests(unittest.TestCase):
    def test_secure_hosts_use_a_host_prefixed_secure_cookie(self):
        self.assertEqual(
            auth.set_cookie("tok", secure=True),
            "__Host-lgz_session=tok; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000; Secure",
        )
        self.assertEqual(
            auth.set_cookie("tok", secure=False),
            "lgz_session=tok; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000",
        )
        self.assertIn("Max-Age=0", auth.clear_cookie(secure=True))
        self.assertTrue(auth.clear_cookie(secure=True).endswith("; Secure"))
        self.assertTrue(auth.clear_cookie(secure=False).startswith("lgz_session=;"))

    def test_reads_only_the_cookie_name_for_the_context(self):
        header = "theme=dark; lgz_session=plain; __Host-lgz_session=prefixed"
        self.assertEqual(auth.read_cookie(header, secure=True), "prefixed")
        self.assertEqual(auth.read_cookie(header, secure=False), "plain")
        self.assertIsNone(auth.read_cookie("lgz_session=plain", secure=True))
        self.assertIsNone(auth.read_cookie("lgz_session=", secure=False))
        self.assertIsNone(auth.read_cookie(None, secure=False))

    def test_other_sites_cookies_do_not_hide_the_session(self):
        header = 'g_state={"i_l":0}; _vcrcs=a b; __Host-lgz_session=token; lgz_session=plain'
        self.assertEqual(auth.read_cookie(header, secure=True), "token")
        self.assertEqual(auth.read_cookie(header, secure=False), "plain")

    def test_tokens_are_random_and_stored_only_as_hashes(self):
        first, second = auth.new_token(), auth.new_token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(auth.token_hash(first), auth.token_hash(first))
        self.assertNotIn(first, auth.token_hash(first))
        self.assertEqual(len(auth.token_hash(first)), 64)


if __name__ == "__main__":
    unittest.main()

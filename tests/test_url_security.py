import socket
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi import HTTPException

from backend.routes import validate_public_http_url


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append(dict(attrs))


def resolve_to(*addresses):
    def resolver(_hostname, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, type, 6, "", (address, port))
                for address in addresses]
    return resolver


class UrlSecurityTests(unittest.TestCase):
    def test_public_http_url_is_allowed(self):
        url = "https://fund.example/opportunity"
        self.assertEqual(validate_public_http_url(url, resolve_to("93.184.216.34")), url)

    def test_private_literal_and_resolved_addresses_are_blocked(self):
        cases = [
            ("http://127.0.0.1/admin", resolve_to("93.184.216.34")),
            ("http://169.254.169.254/latest/meta-data", resolve_to("93.184.216.34")),
            ("https://fund.example/rfp", resolve_to("10.0.0.8")),
            ("https://fund.example/rfp", resolve_to("93.184.216.34", "127.0.0.1")),
        ]
        for url, resolver in cases:
            with self.subTest(url=url), self.assertRaises(HTTPException):
                validate_public_http_url(url, resolver)

    def test_non_http_credentials_and_invalid_ports_are_blocked(self):
        for url in ("file:///etc/passwd", "https://user:pass@fund.example/rfp", "https://fund.example:99999/rfp"):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                validate_public_http_url(url, resolve_to("93.184.216.34"))

    def test_remote_scripts_have_integrity_and_anonymous_cors(self):
        parser = ScriptParser()
        parser.feed((Path(__file__).parents[1] / "frontend" / "index.html").read_text())
        remote_scripts = [script for script in parser.scripts if script.get("src", "").startswith("https://")]
        self.assertEqual(len(remote_scripts), 4)
        for script in remote_scripts:
            self.assertTrue(script.get("integrity", "").startswith("sha384-"))
            self.assertEqual(script.get("crossorigin"), "anonymous")


if __name__ == "__main__":
    unittest.main()

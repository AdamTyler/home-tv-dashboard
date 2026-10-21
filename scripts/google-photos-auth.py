#!/usr/bin/env python3
"""One-time Google sign-in for the photos widget, run on your computer.

Usage:
  scripts/google-photos-auth.py <client_secret.json> [output.json]

<client_secret.json> is the "Desktop app" OAuth client downloaded from Google
Cloud Console. Opens your browser to sign in, then writes the credentials the
Pi needs (default: google-photos.json, git-ignored). Copy that file to
/opt/tv-dashboard/google-photos.json on the Pi.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        client = json.load(f)["installed"]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "google-photos.json"

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if q.get("state") == state:
                result.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            msg = "Signed in. You can close this tab." if "code" in q else "Sign-in failed: %s" % q.get("error")
            self.wfile.write(("<h2 style='font-family:sans-serif'>%s</h2>" % msg).encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
    redirect = "http://127.0.0.1:%d/" % server.server_port
    url = client["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening your browser to sign in to Google...\nIf it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    if "error" in result:
        sys.exit("Sign-in failed: %s" % result["error"])

    body = urllib.parse.urlencode({
        "code": result["code"], "client_id": client["client_id"],
        "client_secret": client["client_secret"], "redirect_uri": redirect,
        "grant_type": "authorization_code", "code_verifier": verifier}).encode()
    with urllib.request.urlopen(client["token_uri"], body, timeout=30) as r:
        tokens = json.load(r)
    if "refresh_token" not in tokens:
        sys.exit("Google didn't return a refresh token; remove the app's access at "
                 "myaccount.google.com/permissions and run this again.")

    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"client_id": client["client_id"], "client_secret": client["client_secret"],
                   "refresh_token": tokens["refresh_token"]}, f, indent=2)
    print("Saved %s. Copy it to the Pi:\n  scp %s <pi>:/opt/tv-dashboard/google-photos.json"
          % (out_path, out_path))


if __name__ == "__main__":
    main()

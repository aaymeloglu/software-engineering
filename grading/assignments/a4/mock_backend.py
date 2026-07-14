"""Permissive mock BBS backend on :8000 for VISUAL grading of A4 frontends.

Each frontend really talks to its own A2 contract, so a single mock can't satisfy every
envelope shape. This returns the most common bronze shapes (bare arrays for list endpoints,
objects for single-resource) with wide-open CORS so as many apps as possible render populated;
the ones expecting envelopes/auth will fall to their error/empty states — which is itself
graded design surface. Purpose is to SEE the apps, not to validate their contracts.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, re

NOW = "2026-05-18T15:30:00Z"
USERS = [{"username": u, "bio": f"{u}'s bio — building things at UATX.", "created_at": NOW}
         for u in ["alice", "bob", "carol", "dave", "erin", "frank"]]
POSTS = [{"id": i,
          "message": m,
          "username": u,
          "created_at": NOW}
         for i, (u, m) in enumerate([
            ("alice", "first post on the new feed — looks clean"),
            ("bob", "anyone else getting CORS errors? fixed with the middleware snippet"),
            ("carol", "the mobile layout actually holds up at 320px, nice"),
            ("dave", "optimistic delete + rollback is so satisfying when it works"),
            ("erin", "pushed my agent on the loading states and it finally listened"),
            ("frank", "dark mode that respects prefers-color-scheme >>>"),
            ("alice", "@bob did you wire the 422 detail inline?"),
            ("carol", "load more vs infinite scroll — went with load more"),
         ], start=1)]
POSTS.reverse()


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Expose-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self._send({}, 204)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/posts":
            self._send(POSTS)
        elif path == "/users":
            self._send(USERS)
        elif re.match(r"^/posts/\d+$", path):
            self._send(POSTS[0])
        elif re.match(r"^/posts/\d+/thread$", path):
            self._send({"post": POSTS[0], "replies": []})
        elif re.match(r"^/users/[^/]+/posts$", path):
            self._send(POSTS[:4])
        elif re.match(r"^/users/[^/]+$", path):
            self._send(USERS[0])
        elif path == "/posts/stream":
            self._send({})
        else:
            self._send(POSTS)  # be generous: anything else gets the feed

    def do_POST(self):
        if self.path.startswith("/posts"):
            self._send({**POSTS[0], "id": 999, "message": "(your new post)"}, 201)
        else:
            self._send(USERS[0], 201)

    def do_DELETE(self):
        self._send({}, 204)

    def do_PATCH(self):
        self._send(POSTS[0])


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8055), H).serve_forever()

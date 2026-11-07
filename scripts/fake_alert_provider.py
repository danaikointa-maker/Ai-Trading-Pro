"""A local server that speaks the Telegram + LINE shapes.

    python3 scripts/fake_alert_provider.py 8099
    NO7_TELEGRAM_API_BASE=http://127.0.0.1:8099 NO7_LINE_API_BASE=http://127.0.0.1:8099 \
      NO7_TELEGRAM_ENABLED=true TELEGRAM_BOT_TOKEN=test NO7_TELEGRAM_CHAT_ID=1 \
      NO7_LINE_ENABLED=true LINE_CHANNEL_TOKEN=test NO7_LINE_TARGET_ID=U1 scripts/run.sh

Then press "ทดสอบการแจ้งเตือน" in the System page (or POST /api/system/alerts/test) and
watch the payload arrive here: this is how the delivery path is verified without
sending anything to a real account. The first Telegram call answers 429 on purpose,
so the retry path is exercised too. Never point production at this.
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"telegram_calls": 0}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"_raw": body}
        if "/sendMessage" in self.path:
            STATE["telegram_calls"] += 1
            if STATE["telegram_calls"] == 1:
                status, resp, extra = 429, {"ok": False, "description": "Too Many Requests"}, {"Retry-After": "0"}
            else:
                status, resp, extra = 200, {"ok": True, "result": {"message_id": 7}}, {}
        elif "/message/push" in self.path:
            status, resp, extra = 200, {"sentMessages": [{"id": "1"}]}, {}
        else:
            status, resp, extra = 404, {"error": "unknown path"}, {}
        print(f"[fake] {self.path.split('/bot')[0] or self.path} -> {status} "
              f"payload={json.dumps(payload, ensure_ascii=False)} "
              f"auth={'yes' if self.headers.get('Authorization') else 'no'}", flush=True)
        data = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        return

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"[fake] listening on 127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

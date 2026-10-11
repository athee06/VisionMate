# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Tiny local HTTP server with Range support, used by the tests in place of GitHub."""
import http.server
import os
import threading


def serve(root, failAfterBytes=None):
	"""Serve files from root on a free port. If failAfterBytes is set, the first full download is cut off there.
	Returns (baseUrl, server)."""
	state = {"failAfter": failAfterBytes}

	class Handler(http.server.BaseHTTPRequestHandler):
		def log_message(self, *a):
			pass

		def do_GET(self):
			path = os.path.join(root, self.path.lstrip("/").split("?")[0])
			if not os.path.isfile(path):
				self.send_error(404)
				return
			size = os.path.getsize(path)
			start = 0
			rng = self.headers.get("Range")
			if rng:
				start = int(rng.split("=")[1].split("-")[0])
				self.send_response(206)
				self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
			else:
				self.send_response(200)
			self.send_header("Content-Length", str(size - start))
			self.end_headers()
			limit = size
			if state["failAfter"] is not None and not rng:
				limit, state["failAfter"] = state["failAfter"], None
			with open(path, "rb") as f:
				f.seek(start)
				sent = start
				while sent < limit:
					block = f.read(min(1 << 20, limit - sent))
					if not block:
						break
					try:
						self.wfile.write(block)
					except OSError:
						return
					sent += len(block)
			if sent < size:
				self.connection.close()

	server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return f"http://127.0.0.1:{server.server_address[1]}", server

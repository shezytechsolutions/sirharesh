"""
Start the website.

    python run.py            production-style server (Waitress, multi-threaded)  <- use this
    python run.py --debug    Flask development server with auto-reload (local only!)

Settings come from environment variables or a .env file (see .env.example).
"""
import os
import socket
import sys

from app import create_app

app = create_app()


def _lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main():
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")

    if "--debug" in sys.argv:
        print(f"Development server: http://127.0.0.1:{port}  (never expose this one to the internet)")
        app.run(host="127.0.0.1", port=port, debug=True)
        return

    if os.environ.get("OPEN_BROWSER", "0") == "1":
        import threading, time, webbrowser
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(f"http://localhost:{port}")), daemon=True).start()

    print("=" * 62)
    print("  AIMS SUKKUR - website is running")
    print(f"  Local:  http://localhost:{port}")
    if host == "0.0.0.0":
        print(f"  LAN:    http://{_lan_ip()}:{port}")
    print(f"  Admin:  http://localhost:{port}/admin/login")
    print("  Press Ctrl+C to stop.")
    print("=" * 62)

    from waitress import serve
    # Waitress hands finished responses to its network thread, so slow phones downloading a big PDF
    # do not tie up the worker threads. 16 workers comfortably serve hundreds of visitors.
    serve(app, host=host, port=port,
          threads=int(os.environ.get("THREADS", "16")),
          connection_limit=int(os.environ.get("CONNECTION_LIMIT", "500")),
          channel_timeout=300,                       # slow mobile connections get 5 min of silence
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"] + 1024 * 1024,
          ident="aims-site")


if __name__ == "__main__":
    main()

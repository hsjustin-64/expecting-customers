"""Temporary, sample-only public demo. Never opens the local shop database."""
import os
import secrets
from pathlib import Path
from app import app

def configure_demo(directory):
    app.config.update(PUBLIC_DEMO=True, DEMO_DATA_DIR=str(directory),
        SECRET_KEY=secrets.token_hex(32), SESSION_COOKIE_NAME='morning_demo',
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=1024*1024)
    return app

if __name__ == '__main__':
    from waitress import serve
    configure_demo(Path(os.environ.get('MORNING_DEMO_DATA', Path(__file__).parent/'demo-data')))
    # One worker thread keeps the existing single-store read/update operations serialized.
    serve(app, host='127.0.0.1', port=8766, threads=1, connection_limit=50,
          channel_timeout=30, max_request_body_size=1024*1024)

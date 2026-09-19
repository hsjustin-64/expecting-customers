import os

def load_dotenv(path):
    if not path.exists():return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=line.split('=',1);key=key.strip();value=value.strip()
        if key.replace('_','').isalnum():os.environ.setdefault(key,value.strip(chr(34)).strip(chr(39)))

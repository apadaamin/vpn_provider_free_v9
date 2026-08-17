import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
BOT_USERNAME=os.getenv("BOT_USERNAME","").strip().lstrip("@")
BASE_URL=os.getenv("BASE_URL","http://127.0.0.1:8080").rstrip("/")
PORT=int(os.getenv("PORT","10000"))
# Render free services require real inbound traffic to stay awake.
# This internal watchdog is useful for health monitoring while the process is alive,
# but it is NOT a substitute for an external ping service.
KEEPALIVE_ENABLED=os.getenv("KEEPALIVE_ENABLED","false").lower() in {"1","true","yes","on"}
KEEPALIVE_INTERVAL=int(os.getenv("KEEPALIVE_INTERVAL","180"))
KEEPALIVE_URL=os.getenv("KEEPALIVE_URL","").strip().rstrip("/")
ADMIN_IDS={int(x.strip()) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()}
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is missing")

TURSO_DATABASE_URL=os.getenv("TURSO_DATABASE_URL","").strip()
TURSO_AUTH_TOKEN=os.getenv("TURSO_AUTH_TOKEN","").strip()
USE_TURSO=bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

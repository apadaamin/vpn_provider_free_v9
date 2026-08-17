import sqlite3,time,secrets,os,datetime
from pathlib import Path
IRAN_TZ=datetime.timezone(datetime.timedelta(hours=3,minutes=30))
def today_str():
    return datetime.datetime.now(IRAN_TZ).strftime("%Y-%m-%d")
DB=Path(__file__).resolve().parent.parent/"data.db"
class CompatCursor:
    def __init__(self,cur):
        self._cur=cur
        self.description=getattr(cur,"description",None)
    @property
    def lastrowid(self): return getattr(self._cur,"lastrowid",None)
    @property
    def rowcount(self): return getattr(self._cur,"rowcount",-1)
    def _conv(self,rows):
        names=[d[0] for d in (self.description or [])]
        return [dict(zip(names,row)) if not isinstance(row,dict) else row for row in rows]
    def fetchone(self):
        r=self._cur.fetchone(); return None if r is None else self._conv([r])[0]
    def fetchall(self): return self._conv(self._cur.fetchall())
    def __iter__(self): return iter(self.fetchall())
class CompatConn:
    def __init__(self,conn,remote=False): self.conn=conn; self.remote=remote
    def execute(self,sql,args=()): return CompatCursor(self.conn.execute(sql,args))
    def executemany(self,sql,args): return CompatCursor(self.conn.executemany(sql,args))
    def executescript(self,script):
        if self.remote:
            for stmt in [x.strip() for x in script.split(";") if x.strip()]: self.conn.execute(stmt)
        else: return self.conn.executescript(script)
    def commit(self): return self.conn.commit()
    def close(self): return self.conn.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.commit(); self.close()
def cx():
    url=os.getenv("TURSO_DATABASE_URL","").strip(); token=os.getenv("TURSO_AUTH_TOKEN","").strip()
    if url and token:
        import libsql
        return CompatConn(libsql.connect(database=url,auth_token=token),True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return CompatConn(c,False)
def init():
    with cx() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY,username TEXT,first_name TEXT,referrer INTEGER,qualified_refs INTEGER DEFAULT 0,rewards INTEGER DEFAULT 0,created INTEGER,last_seen INTEGER);
        CREATE TABLE IF NOT EXISTS referrals(invited INTEGER PRIMARY KEY,inviter INTEGER,qualified INTEGER DEFAULT 0,created INTEGER,qualified_at INTEGER);
        CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id TEXT UNIQUE,title TEXT,username TEXT,url TEXT,enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,url TEXT,fmt TEXT,enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER,created INTEGER,remaining INTEGER DEFAULT 0,replacements_used INTEGER DEFAULT 0,status TEXT DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS configs(id INTEGER PRIMARY KEY AUTOINCREMENT,batch_id INTEGER,uid INTEGER,uri TEXT,source TEXT,status TEXT DEFAULT 'active',connected INTEGER DEFAULT 0,reported_bad INTEGER DEFAULT 0,created INTEGER,checked INTEGER DEFAULT 0,health TEXT DEFAULT 'unknown',latency_ms INTEGER,check_error TEXT);
        CREATE TABLE IF NOT EXISTS health_checks(id INTEGER PRIMARY KEY AUTOINCREMENT,config_id INTEGER,ok INTEGER,latency_ms INTEGER,method TEXT,error TEXT,created INTEGER);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER,type TEXT,meta TEXT,created INTEGER);
        CREATE INDEX IF NOT EXISTS ix_health_cfg ON health_checks(config_id);
        CREATE INDEX IF NOT EXISTS ix_events_uid ON events(uid);
        CREATE TABLE IF NOT EXISTS rewards(id INTEGER PRIMARY KEY AUTOINCREMENT,uid INTEGER,token TEXT UNIQUE,config_id INTEGER,created INTEGER);
        CREATE INDEX IF NOT EXISTS ix_cfg_uid ON configs(uid);
        CREATE INDEX IF NOT EXISTS ix_ref_inviter ON referrals(inviter);
        CREATE INDEX IF NOT EXISTS ix_cfg_source ON configs(source);
        """)
        # Lightweight migrations for deployments created before the daily
        # free-config feature existed. ALTER TABLE ADD COLUMN is a no-op
        # error (caught and ignored) if the column already exists.
        for stmt in (
            "ALTER TABLE batches ADD COLUMN kind TEXT DEFAULT 'referral'",
            "ALTER TABLE batches ADD COLUMN day TEXT",
            "ALTER TABLE batches ADD COLUMN replacement_limit INTEGER",
        ):
            try: c.execute(stmt)
            except Exception: pass
        defaults={
          "brand":"FreeGate",
          "required":"2",
          "batch_size":"5",
          "replacement_limit":"5",
          "daily_replacement_limit":"1",
          "purchase_url":"https://t.me/YourPurchaseBot",
          "sales_bot_url":"https://t.me/YourSalesBot",
          "welcome_title":"🌐 به FreeGate خوش آمدی",
          "welcome":"FreeGate کانفیگ‌های رایگان و عمومی رو از منابع مختلف جمع‌آوری، تست و اعتبارسنجی می‌کنه. این کانفیگ‌ها روزانه عوض می‌شن، ظرفیت محدودی دارن و پایداری‌شون تضمین‌شده نیست — برای همینه که کنارش یه مسیر ثابت و پرسرعت هم برات آماده کردیم؛ هر وقت خواستی داخل ربات به سرویس اختصاصی وصل شو.",
          "disclaimer":"این کانفیگ‌ها توسط ما ساخته یا میزبانی نمی‌شن؛ از منابع عمومی اینترنت جمع‌آوری شدن. ممکنه هر لحظه کند بشن یا از دسترس خارج بشن، چون کاملاً به سرویس‌دهنده اصلی‌شون وابسته‌ن. اگه دنبال یه اتصال همیشه‌پایدار و بدون دردسری هستی، سرویس اختصاصی گزینه‌ی مطمئن‌تریه.",
          "purchase":"🚀 خسته شدی از کانفیگ‌های رایگان که هر روز عوض می‌شن؟ سرویس اختصاصی FreeGate رو داخل ربات فروش امتحان کن؛ سرعت بالا، همیشه‌آنلاین، بدون محدودیت روزانه — و امکان تست رایگان قبل از خرید هم داری.",
          "join_prompt":"👇 <b>قدم اول همینه:</b> کانال‌های بالا رو عضو شو، بعد دکمه‌ی «بررسی عضویت» رو بزن تا وارد داشبورد بشی.",
          "delivery_ready":"🎁 <b>بسته ۵تایی‌ت آماده شد!</b>\n\nهر ۵ سرویس قبل از ارسال تست شدن. یکی‌یکی امتحان کن و زیر هرکدوم نتیجه رو بزن — اگه یکی وصل نشد، بلافاصله جایگزینش رو می‌فرستیم.\n\n⏳ این کانفیگ‌ها رایگان و موقتن. اگه یه اتصال ثابت و بدون نگرانی می‌خوای، سرویس اختصاصی همیشه آماده‌ست.",
          "delivery_empty":"⚠️ <b>فعلاً استخر رایگان خالیه</b>\n\nدر همین لحظه ۵ سرویس سالم برای بسته‌ت پیدا نکردیم؛ سیستم به‌زودی دوباره تلاش می‌کنه و پیام میدیم.\n\n💡 نمی‌خوای منتظر بمونی؟ سرویس اختصاصی همین الان و بدون وقفه در دسترسه — از دکمه‌ی زیر برو داخل ربات فروش.",
          "config_caption":"🔹 <b>سرویس #{i} از بسته‌ی دعوت</b>\n\n🔐 نوع: <b>{type}</b>\n⚡ وضعیت: <b>تست‌شده، آماده اتصال</b>\n\n<code>{uri}</code>\n\n👇 بعد از تست نتیجه رو بزن. اگه وصل نشد، جایگزین می‌فرستیم:",
          "replacement_caption":"🔄 <b>جایگزین سالم فرستادیم</b>\n\n🔐 نوع: <b>{type}</b>\n\n<code>{uri}</code>\n\n👇 نتیجه‌ی این یکی رو هم بعد از تست ثبت کن:",
          "dashboard_intro":"خوش اومدی! از این‌جا وضعیت دعوت‌ها، سرویس‌های رایگان و کانفیگ روزانه‌ت رو مدیریت می‌کنی.",
          "daily_locked":"🔒 <b>کانفیگ رایگان روزانه هنوز قفله</b>\n\nاین قابلیت وقتی باز می‌شه که <b>{need} نفر</b> رو با لینک اختصاصی‌ت دعوت کنی.\n\n👥 دعوت موفق فعلی: <b>{have}</b> از {need}\n🔗 لینک دعوتت رو از منوی اصلی بردار و بفرست.\n\n⚡ عجله داری؟ سرویس اختصاصی نیازی به دعوت نداره و همین الان در دسترسه.",
          "daily_caption":"🎲 <b>کانفیگ رایگان امروزت</b>\n\n🔐 نوع: <b>{type}</b>\n\n<code>{uri}</code>\n\n👇 بعد از تست نتیجه رو بزن. اگه وصل نشد یک جایگزین دیگه داری:",
          "daily_replacement_caption":"🔄 <b>آخرین جایگزین امروزت</b>\n\n🔐 نوع: <b>{type}</b>\n\n<code>{uri}</code>\n\n👇 نتیجه این یکی رو ثبت کن — این آخرین جایگزین سهمیه‌ی امروزته:",
          "daily_empty":"⚠️ الان کانفیگ سالمی برای سهمیه‌ی روزانه پیدا نکردیم؛ چند دقیقه دیگه دوباره امتحان کن.\n\n💡 اگه دنبال یه گزینه‌ی مطمئن‌تری، سرویس اختصاصی همیشه آماده‌ست.",
          "daily_pending":"📌 امروز کانفیگت رو قبلاً گرفتی. نتیجه اتصال رو زیر همون پیام ثبت کن؛ فردا یه کانفیگ تازه اینجا منتظرته.",
          "quota_exhausted":"⛔️ <b>سهمیه‌ی این دوره تموم شد</b>\n\nهمه جایگزین‌های این بسته رو مصرف کردی. از این‌جا به بعد دو راه داری:\n\n1️⃣ با دعوت افراد بیشتر، بسته بعدی رو فوری فعال کن\n2️⃣ فردا سهمیه رایگان روزانه‌ت دوباره باز می‌شه\n\n🚀 یا اگه دیگه نمی‌خوای منتظر بمونی و صبر کنی، همین الان از سرویس اختصاصی و پایدار FreeGate استفاده کن — سریع، بدون قطعی و بدون محدودیت."
        }
        for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)",(k,v))
    ensure_default_sources()

# Sources that are known to work at the time this list was curated. Kept
# separate from init() so existing deployments also receive additions/
# removals on the next deploy, without duplicating or wiping admin-added
# custom sources.
DEFAULT_SOURCES=[
    ("Au1rxx","https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/v2ray-base64.txt","base64"),
    ("MatinGhanbari-Super","https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt","base64"),
    ("BarryFar-All","https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt","text"),
    ("Mahdibland-Aggregator","https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt","base64"),
]
# Old sources that went offline (404) and should be auto-disabled instead
# of silently returning nothing to the collector.
DEAD_SOURCE_NAMES={"RezFlare","0xRadikal"}

def ensure_default_sources():
    with cx() as c:
        existing={row["name"] for row in c.execute("SELECT name FROM sources")}
        for name,url,fmt in DEFAULT_SOURCES:
            if name not in existing:
                c.execute("INSERT INTO sources(name,url,fmt,enabled) VALUES(?,?,?,1)",(name,url,fmt))
        for name in DEAD_SOURCE_NAMES:
            c.execute("UPDATE sources SET enabled=0 WHERE name=?",(name,))
# ============================================================
# Editable text/brand registry — every admin-editable string that
# shapes what end-users see, from /start to config delivery.
# key -> (label shown in admin panel, help text shown while editing)
# ============================================================
EDITABLE_TEXTS={
    "brand":("🏷 نام برند","نامی که بالای پیام‌ها نشان داده می‌شود، مثلاً FreeGate"),
    "welcome_title":("👋 عنوان خوش‌آمدگویی","تیتر پیام /start، قبل از جوین اجباری"),
    "welcome":("📝 متن خوش‌آمدگویی","متن اصلی معرفی پروژه در پیام /start"),
    "join_prompt":("📢 متن جوین اجباری","خط راهنمای زیر لیست کانال‌ها در پیام /start"),
    "dashboard_intro":("💎 متن ابتدای داشبورد","خط اول داشبورد بعد از تأیید عضویت"),
    "delivery_ready":("🎁 متن آماده شدن بسته","پیامی که همراه بسته ۵تایی کانفیگ ارسال می‌شود"),
    "delivery_empty":("🚫 متن نبود کانفیگ سالم","وقتی بسته کامل پیدا نشود این پیام ارسال می‌شود"),
    "config_caption":("🔹 قالب پیام هر کانفیگ","از {i}, {type}, {uri} استفاده کن"),
    "replacement_caption":("🔄 قالب پیام کانفیگ جایگزین","از {type}, {uri} استفاده کن"),
    "disclaimer":("ℹ️ متن سلب مسئولیت","زیر هر بسته کانفیگ نمایش داده می‌شود"),
    "purchase":("🛒 متن تبلیغ سرویس اختصاصی","بالای دکمه خرید نمایش داده می‌شود"),
    "daily_locked":("🔒 متن قفل‌بودن کانفیگ روزانه","از {need} و {have} استفاده کن"),
    "daily_caption":("🎲 قالب پیام کانفیگ روزانه","از {type}, {uri} استفاده کن"),
    "daily_replacement_caption":("🔄 قالب جایگزین کانفیگ روزانه","از {type}, {uri} استفاده کن"),
    "daily_empty":("🚫 متن نبود کانفیگ روزانه سالم",""),
    "daily_pending":("📌 متن کانفیگ روزانه قبلاً گرفته‌شده",""),
    "quota_exhausted":("⛔️ متن اتمام سهمیه (بعد از آخرین جایگزین)","بعد از مصرف کامل جایگزین‌های بسته یا سهمیه روزانه نمایش داده می‌شود"),
}

def get(k,d=""):
    with cx() as c:
        r=c.execute("SELECT v FROM settings WHERE k=?",(k,)).fetchone(); return r["v"] if r else d
def put(k,v):
    with cx() as c: c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(k,str(v)))
def user(uid,username="",first_name=""):
    now=int(time.time())
    with cx() as c:
        r=c.execute("SELECT * FROM users WHERE uid=?",(uid,)).fetchone()
        if r: c.execute("UPDATE users SET username=?,first_name=?,last_seen=? WHERE uid=?",(username or r["username"],first_name or r["first_name"],now,uid))
        else: c.execute("INSERT INTO users(uid,username,first_name,created,last_seen) VALUES(?,?,?,?,?)",(uid,username,first_name,now,now))
        return dict(c.execute("SELECT * FROM users WHERE uid=?",(uid,)).fetchone())
def byid(uid):
    with cx() as c:
        r=c.execute("SELECT * FROM users WHERE uid=?",(uid,)).fetchone(); return dict(r) if r else None
def add_ref(invited,inviter):
    if invited==inviter:return False
    with cx() as c:
        if c.execute("SELECT 1 FROM referrals WHERE invited=?",(invited,)).fetchone():return False
        c.execute("INSERT INTO referrals(invited,inviter,created) VALUES(?,?,?)",(invited,inviter,int(time.time())))
        c.execute("UPDATE users SET referrer=? WHERE uid=?",(inviter,invited)); return True
def qualify(invited):
    with cx() as c:
        r=c.execute("SELECT * FROM referrals WHERE invited=? AND qualified=0",(invited,)).fetchone()
        if not r:return None
        c.execute("UPDATE referrals SET qualified=1,qualified_at=? WHERE invited=?",(int(time.time()),invited))
        c.execute("UPDATE users SET qualified_refs=qualified_refs+1 WHERE uid=?",(r["inviter"],))
        return r["inviter"]
def channels(all_rows=False):
    q="SELECT * FROM channels"+("" if all_rows else " WHERE enabled=1")+" ORDER BY id"
    with cx() as c:return [dict(x) for x in c.execute(q)]
def add_channel(chat_id,title,username,url):
    with cx() as c:c.execute("INSERT OR REPLACE INTO channels(chat_id,title,username,url,enabled) VALUES(?,?,?,?,1)",(str(chat_id),title,username,url))
def del_channel(i):
    with cx() as c:c.execute("DELETE FROM channels WHERE id=?",(i,))
def sources():
    with cx() as c:return [dict(x) for x in c.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY id")]
def new_batch(uid,configs,kind="referral",day=None,replacement_limit=None):
    now=int(time.time())
    if replacement_limit is None:
        replacement_limit=int(get("replacement_limit","5"))
    with cx() as c:
        cur=c.execute("INSERT INTO batches(uid,created,remaining,replacements_used,status,kind,day,replacement_limit) VALUES(?,?,?,?,?,?,?,?)",
                      (uid,now,len(configs),0,"active",kind,day,replacement_limit))
        bid=cur.lastrowid
        ids=[]
        for uri,src in configs:
            cur=c.execute("INSERT INTO configs(batch_id,uid,uri,source,created) VALUES(?,?,?,?,?)",(bid,uid,uri,src,now)); ids.append(cur.lastrowid)
        return bid,ids

def new_daily_batch(uid,uri,src):
    day=today_str()
    limit=int(get("daily_replacement_limit","1"))
    bid,ids=new_batch(uid,[(uri,src)],kind="daily",day=day,replacement_limit=limit)
    return bid,ids[0]

def daily_batch_for(uid,day=None):
    day=day or today_str()
    with cx() as c:
        r=c.execute("SELECT * FROM batches WHERE uid=? AND kind='daily' AND day=? ORDER BY id DESC LIMIT 1",(uid,day)).fetchone()
        return dict(r) if r else None

def batch_by_id(bid):
    with cx() as c:
        r=c.execute("SELECT * FROM batches WHERE id=?",(bid,)).fetchone()
        return dict(r) if r else None

def mark_batch_exhausted(bid):
    with cx() as c: c.execute("UPDATE batches SET status='exhausted' WHERE id=?",(bid,))

def unlocked(uid):
    u=byid(uid)
    if not u: return False
    return int(u.get("qualified_refs",0) or 0) >= int(get("required","2"))

def add_config_to_batch(batch_id,uid,uri,src):
    with cx() as c:
        cur=c.execute("INSERT INTO configs(batch_id,uid,uri,source,created) VALUES(?,?,?,?,?)",(batch_id,uid,uri,src,int(time.time())))
        return cur.lastrowid

def config_for(cid,uid):
    with cx() as c:
        r=c.execute("SELECT * FROM configs WHERE id=? AND uid=?",(cid,uid)).fetchone()
        return dict(r) if r else None

def _batch_limit(b):
    # Per-batch limit set at creation time; falls back to the global
    # referral limit for legacy rows created before this column existed.
    lim=b.get("replacement_limit")
    return int(lim) if lim not in (None,"") else int(get("replacement_limit","5"))

def replacement_available(batch_id):
    with cx() as c:
        b=c.execute("SELECT * FROM batches WHERE id=?",(batch_id,)).fetchone()
        if not b:return False
        b=dict(b)
        return int(b["replacements_used"] or 0) < _batch_limit(b)

def consume_replacement(batch_id):
    with cx() as c:
        b=c.execute("SELECT * FROM batches WHERE id=?",(batch_id,)).fetchone()
        if not b:return False
        b=dict(b)
        used=int(b["replacements_used"] or 0); lim=_batch_limit(b)
        if used>=lim:return False
        c.execute("UPDATE batches SET replacements_used=replacements_used+1 WHERE id=?",(batch_id,))
        return True

def batch_configs(uid):
    with cx() as c:return [dict(x) for x in c.execute("SELECT * FROM configs WHERE uid=? ORDER BY id DESC",(uid,))]
def set_feedback(cid,uid,ok):
    with cx() as c:
        r=c.execute("SELECT * FROM configs WHERE id=? AND uid=?",(cid,uid)).fetchone()
        if not r or r["status"]!="active": return False
        if ok:
            c.execute("UPDATE configs SET connected=1,status='confirmed' WHERE id=?",(cid,))
        else:
            c.execute("UPDATE configs SET reported_bad=1,status='replaced' WHERE id=?",(cid,))
        return True
def save_reward(uid,cid):
    token=secrets.token_urlsafe(18)
    with cx() as c:c.execute("INSERT INTO rewards(uid,token,config_id,created) VALUES(?,?,?,?)",(uid,token,cid,int(time.time())))
    return token
def reward(token):
    with cx() as c:
        r=c.execute("SELECT r.*,c.uri FROM rewards r JOIN configs c ON c.id=r.config_id WHERE r.token=?",(token,)).fetchone()
        return dict(r) if r else None
def stats():
    with cx() as c:return {
      "users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
      "refs":c.execute("SELECT COUNT(*) n FROM referrals WHERE qualified=1").fetchone()["n"],
      "configs":c.execute("SELECT COUNT(*) n FROM configs").fetchone()["n"],
      "confirmed":c.execute("SELECT COUNT(*) n FROM configs WHERE connected=1").fetchone()["n"],
      "bad":c.execute("SELECT COUNT(*) n FROM configs WHERE reported_bad=1").fetchone()["n"]
    }
def users(limit=40,off=0):
    with cx() as c:return [dict(x) for x in c.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?",(limit,off))]

def rewards(uid):
    with cx() as c:
        return [dict(x) for x in c.execute("""SELECT r.token,r.created,c.id,c.source,c.uri,c.status
          FROM rewards r JOIN configs c ON c.id=r.config_id WHERE r.uid=? ORDER BY r.id DESC""",(uid,))]
def issue_rewards(uid, config_ids):
    with cx() as c:
        for cid in config_ids:
            save_reward(uid,cid)
        c.execute("UPDATE users SET rewards=rewards+1 WHERE uid=?",(uid,))
def log_event(uid,typ,meta=""):
    with cx() as c:c.execute("INSERT INTO events(uid,type,meta,created) VALUES(?,?,?,?)",(uid,typ,meta,int(time.time())))
def save_health(cid,ok,latency,method,error=""):
    with cx() as c:
        c.execute("INSERT INTO health_checks(config_id,ok,latency_ms,method,error,created) VALUES(?,?,?,?,?,?)",(cid,int(ok),latency,method,error,int(time.time())))
        c.execute("UPDATE configs SET checked=1,health=?,latency_ms=?,check_error=?,status=? WHERE id=?",
                  ("healthy" if ok else "dead",latency,error,"active" if ok else "dead",cid))
def quality_stats():
    with cx() as c:
        sources=c.execute("""SELECT source,
          COUNT(*) total,
          SUM(CASE WHEN health='healthy' THEN 1 ELSE 0 END) healthy,
          SUM(CASE WHEN connected=1 THEN 1 ELSE 0 END) confirmed,
          SUM(CASE WHEN reported_bad=1 THEN 1 ELSE 0 END) bad,
          AVG(CASE WHEN health='healthy' AND latency_ms IS NOT NULL THEN latency_ms END) latency
          FROM configs GROUP BY source ORDER BY confirmed DESC, healthy DESC""").fetchall()
        top=c.execute("""SELECT id,source,health,latency_ms,connected,reported_bad,created
          FROM configs ORDER BY connected DESC, reported_bad ASC, latency_ms ASC LIMIT 20""").fetchall()
        return [dict(x) for x in sources],[dict(x) for x in top]

def active_batch(uid):
    with cx() as c: return c.execute("SELECT * FROM batches WHERE uid=? AND status='active' ORDER BY id DESC LIMIT 1",(uid,)).fetchone()
def consume_batch_replacement(uid):
    # Backward-compatible helper: consumes from the current active package.
    b=active_batch(uid)
    return bool(b and consume_replacement(b["id"]))

def close_active_batch(uid):
    # Only referral-kind batches are superseded by a new referral package;
    # the daily free-config batch has its own independent lifecycle keyed
    # by calendar day and must never be closed by this.
    with cx() as c: c.execute("UPDATE batches SET status='closed' WHERE uid=? AND status='active' AND kind='referral'",(uid,))


def events_for(uid,limit=100):
    with cx() as c:
        return c.execute("SELECT * FROM events WHERE uid=? ORDER BY id DESC LIMIT ?",(uid,limit)).fetchall()


# ============================================================
# Source Manager compatibility layer
# ============================================================

def source_list(all_rows=False):
    """Return sources in the shape expected by Source Manager."""
    q = "SELECT * FROM sources"
    if not all_rows:
        q += " WHERE enabled=1"
    q += " ORDER BY id"

    with cx() as c:
        rows = [dict(x) for x in c.execute(q)]
        for row in rows:
            row["kind"] = row.get("fmt") or "url"
            row["endpoint"] = row.get("url") or ""
            row["priority"] = int(row.get("priority") or 100)

            name = row.get("name", "")
            stats = c.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN health='healthy' THEN 1 ELSE 0 END) AS healthy,
                    SUM(CASE WHEN connected=1 THEN 1 ELSE 0 END) AS confirmed,
                    SUM(CASE WHEN reported_bad=1 THEN 1 ELSE 0 END) AS bad
                FROM configs
                WHERE source=?
            """, (name,)).fetchone()

            total = int(stats["total"] or 0)
            healthy = int(stats["healthy"] or 0)
            confirmed = int(stats["confirmed"] or 0)
            bad = int(stats["bad"] or 0)

            row["health_rate"] = healthy / total * 100 if total else 0
            row["success_rate"] = (
                confirmed / (confirmed + bad) * 100
                if confirmed + bad else 0
            )
        return rows


def source_add(name, kind, endpoint, priority=100):
    """Add a source using the existing sources schema."""
    name = str(name).strip()
    kind = str(kind).strip().lower()
    endpoint = str(endpoint).strip()
    if not name or not endpoint:
        raise ValueError("name and endpoint are required")

    fmt = "base64" if kind == "base64" else "text"
    with cx() as c:
        c.execute(
            "INSERT INTO sources(name,url,fmt,enabled) VALUES(?,?,?,1)",
            (name, endpoint, fmt)
        )


def source_update(source_id, name=None, kind=None,
                  endpoint=None, priority=None):
    """Update an existing source."""
    source_id = int(source_id)
    with cx() as c:
        current = c.execute(
            "SELECT * FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if not current:
            return False

        new_name = name if name is not None else current["name"]
        new_url = endpoint if endpoint is not None else current["url"]

        if kind is not None:
            kind = str(kind).lower()
            new_fmt = "base64" if kind == "base64" else "text"
        else:
            new_fmt = current["fmt"]

        c.execute(
            "UPDATE sources SET name=?, url=?, fmt=? WHERE id=?",
            (new_name, new_url, new_fmt, source_id)
        )
        return True


def source_delete(source_id):
    """Delete a source."""
    with cx() as c:
        c.execute("DELETE FROM sources WHERE id=?", (int(source_id),))


def source_toggle(source_id):
    """Enable/disable a source."""
    with cx() as c:
        row = c.execute(
            "SELECT enabled FROM sources WHERE id=?", (int(source_id),)
        ).fetchone()
        if not row:
            return False

        state = 0 if int(row["enabled"]) else 1
        c.execute(
            "UPDATE sources SET enabled=? WHERE id=?",
            (state, int(source_id))
        )
        return True

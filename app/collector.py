import aiohttp,asyncio,base64,re,time
from .db import sources
P=("vless://","vmess://","trojan://","ss://","ssr://","hy2://","hysteria2://","tuic://","wireguard://")
cache={"x":[],"t":0}
def b64(s):
    s=re.sub(r"\s+","",s);s+="="*((4-len(s)%4)%4)
    try:return base64.b64decode(s).decode("utf8","ignore")
    except:return ""
def parse(s,fmt):
    s=b64(s) if fmt=="base64" else s
    out=[]
    for l in s.replace("\r","\n").splitlines():
        l=l.strip()
        if l.startswith(P):out.append(l)
        else:
            m=re.search(r'((?:vless|vmess|trojan|ss|ssr|hy2|hysteria2|tuic|wireguard)://\S+)',l)
            if m:out.append(m.group(1).rstrip('"\',]'))
    return out
async def collect(force=False):
    if cache["x"] and not force and time.time()-cache["t"]<600:return cache["x"]
    timeout=aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout,headers={"User-Agent":"FreeGateCollector/3.0"}) as s:
        async def one(src):
            try:
                async with s.get(src["url"],allow_redirects=True) as r:
                    if r.status!=200:return []
                    return [(x,src["name"]) for x in parse(await r.text(errors="ignore"),src["fmt"])]
            except:return []
        chunks=await asyncio.gather(*(one(x) for x in sources()))
    seen=set();out=[]
    for ch in chunks:
        for item in ch:
            if item[0] not in seen:seen.add(item[0]);out.append(item)
    cache.update(x=out,t=time.time());return out
async def five():
    items=await collect()
    if len(items)<5: raise RuntimeError("کمتر از ۵ کانفیگ در منابع عمومی موجود است")
    # rotate through the pool so users do not always receive the same first 5
    start=int(time.time()*1000)%len(items)
    chosen=[]
    for i in range(len(items)):
        x=items[(start+i)%len(items)]
        if x[0] not in [a[0] for a in chosen]: chosen.append(x)
        if len(chosen)==5:return chosen
    return chosen

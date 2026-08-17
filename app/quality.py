import asyncio, shutil, tempfile, os, json, time, re, base64, socket
from urllib.parse import urlparse, parse_qs, unquote

import aiohttp

BINARIES = ("sing-box", "mihomo", "clash-meta", "clash")


def installed():
    return [x for x in BINARIES if shutil.which(x)]


def _b64pad(s):
    s = re.sub(r"\s+", "", s)
    return s + "=" * ((4 - len(s) % 4) % 4)


def extract_host_port(uri):
    try:
        u = urlparse(uri)
        host = u.hostname
        port = u.port
        if host and port:
            return host, port
    except Exception:
        pass
    return None, None


# ------------------------------------------------------------------
# TCP / UDP baseline reachability (used when sing-box is unavailable
# or when a config cannot be parsed into a sing-box outbound)
# ------------------------------------------------------------------

async def tcp_probe(uri, timeout=5):
    host, port = extract_host_port(uri)
    if not host or not port:
        return False, None, "parse"
    t = time.perf_counter()
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True, int((time.perf_counter() - t) * 1000), "tcp"
    except Exception as e:
        return False, None, f"tcp:{type(e).__name__}"


async def udp_probe(uri, timeout=4):
    """Best-effort reachability probe for UDP/QUIC based protocols
    (hysteria2/tuic). A plain TCP connect against these always fails,
    so treating them with tcp_probe silently marks every node as dead.
    We send a junk datagram and only fail on an explicit ICMP
    port-unreachable / connection-refused response; a timeout with no
    error is treated as "likely reachable" (QUIC servers do not reply
    to garbage datagrams, which is expected and not a failure signal).
    """
    host, port = extract_host_port(uri)
    if not host or not port:
        return False, None, "parse"
    t = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except Exception as e:
        return False, None, f"udp:dns:{type(e).__name__}"
    if not infos:
        return False, None, "udp:noaddr"
    fam, socktype, proto, _, sockaddr = infos[0]
    sock = socket.socket(fam, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, sockaddr)
        sock.send(b"\x00\x01\x02probe")
        try:
            fut = loop.sock_recv(sock, 64)
            await asyncio.wait_for(fut, timeout)
            return True, int((time.perf_counter() - t) * 1000), "udp"
        except asyncio.TimeoutError:
            return True, int((time.perf_counter() - t) * 1000), "udp:noresp"
    except (ConnectionRefusedError, OSError) as e:
        return False, None, f"udp:{type(e).__name__}"
    finally:
        sock.close()


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ------------------------------------------------------------------
# URI -> sing-box outbound parsing
# ------------------------------------------------------------------

def _tls_block(sni=None, insecure=False, alpn=None, reality_pbk=None, reality_sid=None, fp=None):
    tls = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    if insecure:
        tls["insecure"] = True
    if alpn:
        tls["alpn"] = alpn if isinstance(alpn, list) else [alpn]
    if reality_pbk:
        tls["reality"] = {"enabled": True, "public_key": reality_pbk, "short_id": reality_sid or ""}
        tls["utls"] = {"enabled": True, "fingerprint": fp or "chrome"}
    elif fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    return tls


def _transport_block(net, q, host_hdr=None):
    net = (net or "tcp").lower()
    path = unquote((q.get("path", [""])[0]) or "/")
    if net in ("ws", "websocket"):
        headers = {}
        h = q.get("host", [host_hdr or ""])[0]
        if h:
            headers["Host"] = h
        return {"type": "ws", "path": path or "/", "headers": headers}
    if net == "grpc":
        svc = q.get("serviceName", q.get("path", [""]))[0]
        return {"type": "grpc", "service_name": unquote(svc or "")}
    if net in ("h2", "http"):
        h = q.get("host", [host_hdr or ""])[0]
        return {"type": "http", "host": [h] if h else [], "path": path or "/"}
    return None


def _parse_vless(uri):
    u = urlparse(uri)
    q = parse_qs(u.query)
    security = (q.get("security", ["none"])[0] or "none").lower()
    net = (q.get("type", ["tcp"])[0] or "tcp").lower()
    out = {
        "type": "vless",
        "tag": "proxy",
        "server": u.hostname,
        "server_port": u.port,
        "uuid": u.username,
    }
    flow = q.get("flow", [""])[0]
    if flow:
        out["flow"] = flow
    if security in ("tls", "reality"):
        out["tls"] = _tls_block(
            sni=q.get("sni", q.get("host", [None]))[0],
            insecure=q.get("allowInsecure", q.get("insecure", ["0"]))[0] in ("1", "true"),
            alpn=q.get("alpn", [None])[0].split(",") if q.get("alpn") else None,
            reality_pbk=q.get("pbk", [None])[0] if security == "reality" else None,
            reality_sid=q.get("sid", [None])[0],
            fp=q.get("fp", [None])[0],
        )
    if net not in ("tcp", "raw") and not flow:
        t = _transport_block(net, q)
        if t:
            out["transport"] = t
    return out


def _parse_trojan(uri):
    u = urlparse(uri)
    q = parse_qs(u.query)
    net = (q.get("type", ["tcp"])[0] or "tcp").lower()
    out = {
        "type": "trojan",
        "tag": "proxy",
        "server": u.hostname,
        "server_port": u.port,
        "password": unquote(u.username or ""),
        "tls": _tls_block(
            sni=q.get("sni", q.get("peer", [u.hostname]))[0],
            insecure=q.get("allowInsecure", q.get("insecure", ["0"]))[0] in ("1", "true"),
            alpn=q.get("alpn", [None])[0].split(",") if q.get("alpn") else None,
            fp=q.get("fp", [None])[0],
        ),
    }
    if net not in ("tcp", "raw"):
        t = _transport_block(net, q)
        if t:
            out["transport"] = t
    return out


def _parse_ss(uri):
    u = urlparse(uri)
    userinfo = u.username or ""
    method, password = None, None
    if u.password:
        method, password = unquote(u.username), unquote(u.password)
    else:
        try:
            dec = base64.urlsafe_b64decode(_b64pad(userinfo)).decode("utf8", "ignore")
            method, password = dec.split(":", 1)
        except Exception:
            return None
    if not method or not u.hostname or not u.port:
        return None
    return {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": u.hostname,
        "server_port": u.port,
        "method": method,
        "password": password,
    }


def _parse_vmess(uri):
    raw = uri[len("vmess://"):]
    try:
        data = json.loads(base64.b64decode(_b64pad(raw)).decode("utf8", "ignore"))
    except Exception:
        return None
    host = data.get("add")
    port = int(data.get("port", 0) or 0)
    if not host or not port:
        return None
    out = {
        "type": "vmess",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "uuid": data.get("id"),
        "security": data.get("scy") or "auto",
        "alter_id": int(data.get("aid", 0) or 0),
    }
    if str(data.get("tls", "")).lower() == "tls":
        out["tls"] = _tls_block(sni=data.get("sni") or data.get("host") or host,
                                 insecure=True)
    net = (data.get("net") or "tcp").lower()
    if net in ("ws", "grpc", "h2", "http"):
        q = {"path": [data.get("path", "/")], "host": [data.get("host", "")],
             "serviceName": [data.get("path", "")]}
        t = _transport_block(net, q)
        if t:
            out["transport"] = t
    return out


def _parse_hysteria2(uri):
    u = urlparse(uri)
    q = parse_qs(u.query)
    pw = unquote(u.username or (q.get("password", [""])[0]))
    out = {
        "type": "hysteria2",
        "tag": "proxy",
        "server": u.hostname,
        "server_port": u.port,
        "password": pw,
        "tls": _tls_block(
            sni=q.get("sni", q.get("peer", [u.hostname]))[0],
            insecure=q.get("insecure", ["0"])[0] in ("1", "true"),
        ),
    }
    obfs = q.get("obfs", [None])[0]
    if obfs and obfs.lower() != "none":
        out["obfs"] = {"type": obfs, "password": q.get("obfs-password", [""])[0]}
    return out


def _parse_tuic(uri):
    u = urlparse(uri)
    q = parse_qs(u.query)
    user = u.username or ""
    password = unquote(u.password or "")
    out = {
        "type": "tuic",
        "tag": "proxy",
        "server": u.hostname,
        "server_port": u.port,
        "uuid": user,
        "password": password,
        "congestion_control": q.get("congestion_control", ["bbr"])[0],
        "tls": _tls_block(
            sni=q.get("sni", [u.hostname])[0],
            insecure=q.get("allow_insecure", q.get("insecure", ["0"]))[0] in ("1", "true"),
            alpn=q.get("alpn", [None])[0].split(",") if q.get("alpn") else None,
        ),
    }
    return out


PARSERS = {
    "vless": _parse_vless,
    "trojan": _parse_trojan,
    "ss": _parse_ss,
    "vmess": _parse_vmess,
    "hysteria2": _parse_hysteria2,
    "hy2": _parse_hysteria2,
    "tuic": _parse_tuic,
}


def uri_to_outbound(uri):
    scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
    fn = PARSERS.get(scheme)
    if not fn:
        return None
    try:
        out = fn(uri)
        if not out or not out.get("server") or not out.get("server_port"):
            return None
        return out
    except Exception:
        return None


# ------------------------------------------------------------------
# Real connectivity validation through a locally-spawned sing-box
# process: build a one-shot config exposing a mixed inbound wired to
# the parsed outbound, then request a small plain-HTTP URL through it.
# ------------------------------------------------------------------

_SINGBOX_SEM = asyncio.Semaphore(int(os.getenv("SINGBOX_CONCURRENCY", "4")))
PROBE_URL = os.getenv("PROBE_URL", "http://cp.cloudflare.com/generate_204")


async def _wait_port(port, timeout=2.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            try:
                await w.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            await asyncio.sleep(0.1)
    return False


async def singbox_probe(uri, timeout=8):
    binary = shutil.which("sing-box")
    if not binary:
        return None  # signal: caller should fall back
    outbound = uri_to_outbound(uri)
    if not outbound:
        return None
    port = _free_port()
    cfg = {
        "log": {"level": "error", "disabled": True},
        "inbounds": [{
            "type": "mixed", "tag": "in",
            "listen": "127.0.0.1", "listen_port": port,
            "sniff": False,
        }],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {"rules": [{"inbound": ["in"], "outbound": "proxy"}], "final": "proxy"},
    }
    tmpdir = tempfile.mkdtemp(prefix="sbprobe_")
    cfgpath = os.path.join(tmpdir, "c.json")
    with open(cfgpath, "w") as f:
        json.dump(cfg, f)
    proc = None
    t = time.perf_counter()
    async with _SINGBOX_SEM:
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "run", "-c", cfgpath,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if not await _wait_port(port, timeout=min(3, timeout / 2)):
                return False, None, "singbox:startup"
            proxy = f"http://127.0.0.1:{port}"
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as s:
                async with s.get(PROBE_URL, proxy=proxy) as r:
                    ok = r.status in (200, 204)
                    lat = int((time.perf_counter() - t) * 1000)
                    return ok, lat, "singbox"
        except Exception as e:
            return False, None, f"singbox:{type(e).__name__}"
        finally:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            try:
                os.remove(cfgpath)
                os.rmdir(tmpdir)
            except Exception:
                pass


async def runtime_probe(uri, timeout=12):
    """Real per-protocol validation when sing-box is available; falls
    back to a TCP/UDP reachability baseline otherwise or when a URI
    cannot be parsed into a sing-box outbound (safe-by-default: no
    unknown binaries or third-party payloads are ever executed, only
    the locally installed sing-box client with a config we generate).
    """
    result = await singbox_probe(uri, timeout=min(timeout, 9))
    if result is not None:
        return result
    scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
    if scheme in ("hy2", "hysteria2", "tuic"):
        return await udp_probe(uri, min(timeout, 5))
    return await tcp_probe(uri, min(timeout, 5))


async def check_many(items, concurrency=20):
    sem = asyncio.Semaphore(concurrency)

    async def one(item):
        async with sem:
            ok, lat, method = await runtime_probe(item["uri"])
            return item, ok, lat, method

    return await asyncio.gather(*(one(x) for x in items))

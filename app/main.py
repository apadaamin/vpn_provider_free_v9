import asyncio, threading
import logging
import aiohttp
from flask import Flask, abort
from aiogram import Bot,Dispatcher,F,Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart,Command
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from .config import * 
from .db import *
from .db import (
    source_list,source_add,source_delete,source_toggle,
    EDITABLE_TEXTS,unlocked,daily_batch_for,new_daily_batch,
    batch_by_id,mark_batch_exhausted,
)
from .collector import collect
from .quality import check_many, installed, runtime_probe
from .scoring import source_state
from .antifraud import risk_score,label
from .ui import (
    join,
    main as main_keyboard,
    back,
    feedback,
    admin,
    text_admin_kb,
    purchase_kb,
)

log=logging.getLogger(__name__)


class SourceState(StatesGroup):
    add_name=State()
    add_endpoint=State()
    add_kind=State()
    add_priority=State()

class TextEditState(StatesGroup):
    waiting=State()

def source_admin_kb(rows):
    buttons=[]
    for s in rows:
        status="🟢" if int(s["enabled"]) else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {s['name'][:24]} · {s['kind']}",
            callback_data=f"src_view:{s['id']}")])
    buttons += [
        [InlineKeyboardButton(text="➕ افزودن Source",callback_data="src_add")],
        [InlineKeyboardButton(text="🔄 بروزرسانی",callback_data="a_collector_sources"),
         InlineKeyboardButton(text="⬅️ پنل",callback_data="a_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def source_view_kb(sid,enabled):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن"),callback_data=f"src_toggle:{sid}")],
        [InlineKeyboardButton(text="🗑 حذف Source",callback_data=f"src_delete:{sid}")],
        [InlineKeyboardButton(text="⬅️ بازگشت",callback_data="a_collector_sources")]
    ])
r=Router()
class BroadcastState(StatesGroup):
    waiting=State()
def admin_ok(uid):return uid in ADMIN_IDS
def start_text():
    return f"""🌐 <b>{get('brand')}</b>

<b>{get('welcome_title')}</b>

{get('welcome')}

🔎 <b>ما چه کار می‌کنیم؟</b>
منابع عمومی مختلف را جمع‌آوری می‌کنیم، داده‌ها را Deduplicate می‌کنیم، کانفیگ‌های قابل‌پردازش را جدا می‌کنیم و بازخورد کاربران را ثبت می‌کنیم تا کیفیت منابع بهتر مشخص شود.

🎯 <b>سیستم هدیه</b>
برای هر <b>{get('required')} دعوت موفق</b>، یک بسته شامل <b>۵ سرویس آزمایشی</b> دریافت می‌کنی و کانفیگ رایگان روزانه هم برات باز می‌شه.

{get('join_prompt')}"""
def dashboard(uid):
    u=byid(uid);need=int(get("required")); progress=u["qualified_refs"]%need
    remain=need-progress if progress else need
    is_unlocked=unlocked(uid)
    unlock_line=("✅ کانفیگ رایگان روزانه برات فعاله — از منو بزن." if is_unlocked
                 else f"🔒 با <b>{remain}</b> دعوت موفق دیگه، کانفیگ رایگان روزانه هم باز می‌شه.")
    return f"""💎 <b>{get('brand')} · داشبورد شخصی</b>

{get('dashboard_intro')}

🎁 <b>هدف فعلی</b>
👥 دعوت موفق: <b>{u['qualified_refs']}</b>
🎯 تا بسته بعدی: <b>{remain}</b> دعوت

{unlock_line}

📌 بازخوردهای «متصل شدم / متصل نشدم» در آمار کیفیت پروژه ثبت می‌شوند."""
async def member(bot,uid):
    for c in channels():
        try:
            x=await bot.get_chat_member(c["chat_id"],uid)
            if x.status in ("left","kicked"):return False
        except:return False
    return True
async def process_qualification(bot,uid):
    """Confirms a pending referral and, on a milestone, issues the reward
    package. Must run exactly once per user — whether they were already a
    channel member at /start or just passed the join-check button — so a
    real successful referral is never silently lost behind a redundant
    join screen."""
    inv=qualify(uid)
    if not inv: return
    log_event(uid,'referral_qualified',str(inv))
    iu=byid(inv); need=int(get('required'))
    if iu['qualified_refs']%need==0:
        await bot.send_message(inv,f"🎉 <b>یک بسته جدید برایت فعال شد!</b>\n\nبه {iu['qualified_refs']} دعوت موفق رسیدی. ۵ سرویس آزمایشی در حال ارسال است.")
        try:
            await send_batch(bot,inv)
        except Exception as e:
            log.warning("send_batch failed for %s: %s",inv,e)
async def send_batch(bot,uid):
    """Create exactly one package; refill its same batch until 5 healthy configs or pool exhaustion."""
    candidates=await collect()
    if not candidates: raise RuntimeError("هیچ کانفیگی در منابع عمومی پیدا نشد")
    # Close only the previous active referral package. The daily
    # free-config batch has its own lifecycle and is untouched here.
    close_active_batch(uid)
    selected=[]; seen=set()
    # Rotate starting point, but keep one package and its own config rows.
    start=int(asyncio.get_running_loop().time()*1000)%len(candidates)
    ordered=candidates[start:]+candidates[:start]
    for item in ordered:
        if item[0] in seen: continue
        seen.add(item[0]); selected.append(item)
        if len(selected)>=40: break
    bid,cids=new_batch(uid,selected)
    rows=[{"id":cid,"uri":item[0],"source":item[1]} for cid,item in zip(cids,selected)]
    good=[]
    # Real per-protocol connectivity checks (sing-box when available, TCP/UDP
    # fallback otherwise) — only configs that are actually reachable/pinging
    # right now are ever handed to a user.
    for row,ok,lat,method in await check_many(rows,concurrency=int(get("check_concurrency","6") or 6)):
        save_health(row["id"],ok,lat,method,"" if ok else "pre-delivery health check failed")
        if ok: good.append(row)
        if len(good)>=5: break
    if len(good)<5:
        with cx() as c:
            c.execute("UPDATE batches SET status='failed' WHERE id=?",(bid,))
        await bot.send_message(uid,get("delivery_empty"),reply_markup=purchase_kb())
        return
    good=good[:5]
    tokens=[save_reward(uid,row["id"]) for row in good]
    with cx() as c:c.execute("UPDATE users SET rewards=rewards+1 WHERE uid=?",(uid,))
    await bot.send_message(uid,get("delivery_ready"))
    for i,(row,token) in enumerate(zip(good,tokens),1):
        uri=row["uri"]
        caption=get("config_caption").format(i=i,type=uri.split(':',1)[0].upper(),uri=uri[:180])
        await bot.send_message(uid,caption,reply_markup=feedback(row["id"]))
    await bot.send_message(uid,f"""ℹ️ <b>درباره این سرویس‌ها</b>

{get('disclaimer')}

{get('purchase')}""",reply_markup=purchase_kb())

async def pick_healthy_candidate(exclude_uris,tries=20):
    """Pull candidates from the pool and return the first one that passes
    a real connectivity probe, or None if nothing healthy turns up within
    the attempt budget."""
    candidates=await collect()
    candidates=[x for x in candidates if x[0] not in exclude_uris]
    for item in candidates[:tries]:
        ok,lat,method=await runtime_probe(item[0])
        if ok: return item,lat,method
    return None,None,None

@r.message(CommandStart())
async def start(m:Message):
    u=user(m.from_user.id,m.from_user.username,m.from_user.first_name)
    arg=m.text.split(maxsplit=1)[1] if m.text and len(m.text.split())>1 else ""
    if arg.startswith("ref_"):
        try: inv=int(arg[4:])
        except: inv=None
        if inv and inv!=m.from_user.id and not u["referrer"]:
            if add_ref(m.from_user.id,inv): log_event(m.from_user.id,'referral_started',str(inv))
    # Only show the force-join screen when the user is genuinely NOT a
    # member yet. Someone who already joined the channels earlier should
    # never be asked to click through a redundant join form — they land
    # straight on the dashboard and their referral (if any) is confirmed
    # immediately.
    if channels() and not await member(m.bot,m.from_user.id):
        await m.answer(start_text(),reply_markup=join())
        return
    await process_qualification(m.bot,m.from_user.id)
    await m.answer(dashboard(m.from_user.id),reply_markup=main_keyboard(unlocked(m.from_user.id)))
@r.callback_query(F.data=="join_check")
async def join_check(q:CallbackQuery):
    if not await member(q.bot,q.from_user.id):return await q.answer("هنوز عضویت کامل نشده.",show_alert=True)
    await process_qualification(q.bot,q.from_user.id)
    await q.answer("عضویت تأیید شد ✅");await q.message.edit_text(dashboard(q.from_user.id),reply_markup=main_keyboard(unlocked(q.from_user.id)))
@r.callback_query(F.data=="menu")
async def menu(q):await q.message.edit_text(dashboard(q.from_user.id),reply_markup=main_keyboard(unlocked(q.from_user.id)));await q.answer()
@r.callback_query(F.data=="ref")
async def ref(q):
    u=byid(q.from_user.id);link=f"https://t.me/{BOT_USERNAME}?start=ref_{u['uid']}"
    await q.message.edit_text(f"""🔵 <b>لینک دعوت اختصاصی تو</b>

<code>{link}</code>

🎁 هر <b>{get('required')} دعوت موفق</b> یک بسته ۵‌تایی سرویس آزمایشی فعال می‌کند، و کانفیگ رایگان روزانه هم برات باز می‌شه.

دعوت موفق یعنی کاربر وارد ربات شود و (در صورت نیاز) جویین اجباری را کامل کند.""",reply_markup=back());await q.answer()
@r.callback_query(F.data=="stats")
async def st(q):
    u=byid(q.from_user.id); b=active_batch(q.from_user.id); used=(b['replacements_used'] if b else 0); lim=get('replacement_limit')
    db_=daily_batch_for(q.from_user.id)
    daily_line=(f"🎲 کانفیگ روزانه امروز: <b>{'گرفته‌شده' if db_ else 'هنوز نگرفتی'}</b>" if unlocked(q.from_user.id)
                else "🎲 کانفیگ روزانه: <b>قفل</b>")
    await q.message.edit_text(f"""📊 <b>آمار و کیفیت</b>

👥 دعوت موفق: <b>{u['qualified_refs']}</b>
🎁 بسته‌های دریافت‌شده: <b>{u['rewards']}</b>
🔁 جایگزین‌های بسته فعلی: <b>{used}/{lim}</b>
{daily_line}

💡 با تمام شدن این سهمیه، برای همان بسته جایگزین دیگری صادر نمی‌شود. بسته بعدی فقط پس از رسیدن به سهمیه دعوت بعدی فعال می‌شود.""",reply_markup=back());await q.answer()
@r.callback_query(F.data=="services")
async def svc(q):
    rs=rewards(q.from_user.id)
    if not rs:txt="🎁 <b>سرویس‌های من</b>\n\nهنوز بسته‌ای برایت صادر نشده.";kb=back()
    else:
        txt="🎁 <b>سرویس‌های من</b>\n\nبسته‌های دریافت‌شده تو:"; kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"◈ 🎁 سرویس #{i+1}",url=f"{BASE_URL}/sub/{x['token']}")] for i,x in enumerate(rs[:30])]+[[InlineKeyboardButton(text="↩️ بازگشت",callback_data="menu")]])
    await q.message.edit_text(txt,reply_markup=kb);await q.answer()

@r.callback_query(F.data=="daily_free")
async def daily_free(q:CallbackQuery):
    uid=q.from_user.id
    if not unlocked(uid):
        u=byid(uid); need=int(get('required')); have=min(u['qualified_refs'],need)
        await q.answer()
        await q.message.answer(get("daily_locked").format(need=need,have=have),reply_markup=purchase_kb())
        return
    b=daily_batch_for(uid)
    if b:
        if b["status"]=="exhausted":
            await q.answer()
            await q.message.answer(get("quota_exhausted"),reply_markup=purchase_kb())
            return
        await q.answer()
        await q.message.answer(get("daily_pending"))
        return
    await q.answer("در حال جستجوی یک کانفیگ سالم…")
    used_uris={x["uri"] for x in batch_configs(uid)}
    item,lat,method=await pick_healthy_candidate(used_uris)
    if not item:
        return await q.message.answer(get("daily_empty"),reply_markup=purchase_kb())
    bid,cid=new_daily_batch(uid,item[0],item[1])
    save_health(cid,True,lat,method,"")
    caption=get("daily_caption").format(type=item[0].split(':',1)[0].upper(),uri=item[0][:180])
    await q.message.answer(caption,reply_markup=feedback(cid))

@r.callback_query(F.data.startswith("ok:"))
async def ok(q):
    cid=int(q.data.split(":")[1]);set_feedback(cid,q.from_user.id,True)
    await q.answer("ثبت شد؛ ممنون از بازخوردت 💚");await q.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 ثبت شد · متصل",callback_data="noop")]]))
@r.callback_query(F.data.startswith("bad:"))
async def bad(q:CallbackQuery):
    cid=int(q.data.split(":")[1])
    original=config_for(cid,q.from_user.id)
    if not original or original["status"]!="active":
        return await q.answer("این سرویس قبلاً پردازش شده است.",show_alert=True)
    b=batch_by_id(original["batch_id"])
    is_daily=bool(b and b.get("kind")=="daily")
    if not b or not replacement_available(original["batch_id"]):
        set_feedback(cid,q.from_user.id,False)
        if b: mark_batch_exhausted(b["id"])
        await q.answer("سهمیه‌ی جایگزین تموم شد.")
        await q.message.edit_text("🔴 <b>این کانفیگ ناموفق گزارش شد.</b>\n\nاز بسته فعلی خارج شد.")
        await q.bot.send_message(q.from_user.id,get("quota_exhausted"),reply_markup=purchase_kb())
        return
    used_uris={x["uri"] for x in batch_configs(q.from_user.id)}
    item,lat,method=await pick_healthy_candidate(used_uris,tries=30)
    if not item:
        return await q.answer("فعلاً جایگزین سالمی پیدا نشد؛ سهمیه‌ات مصرف نشد. کمی بعد دوباره امتحان کن.",show_alert=True)
    if not consume_replacement(original["batch_id"]):
        return await q.answer("سهمیه جایگزین این بسته قبلاً مصرف شده.",show_alert=True)
    new_id=add_config_to_batch(original["batch_id"],q.from_user.id,item[0],item[1])
    save_health(new_id,True,lat,method,"")
    set_feedback(cid,q.from_user.id,False)
    await q.answer("کانفیگ جایگزین ارسال شد 🔄")
    await q.message.edit_text("🔴 <b>این کانفیگ ناموفق گزارش شد.</b>\n\nاز بسته فعلی خارج شد و یک جایگزین بررسی‌شده برایت ارسال شد.")
    template_key="daily_replacement_caption" if is_daily else "replacement_caption"
    caption=get(template_key).format(type=item[0].split(':',1)[0].upper(),uri=item[0][:180])
    await q.bot.send_message(q.from_user.id,caption,reply_markup=feedback(new_id))
@r.message(Command("admin"))
async def adm(m):
    if admin_ok(m.from_user.id):await m.answer("🛠 <b>مرکز مدیریت FreeGate</b>",reply_markup=admin())
@r.callback_query(F.data.in_({"admin","a_back"}))
async def admin_back(q:CallbackQuery,state:FSMContext=None):
    if not admin_ok(q.from_user.id): return
    if state is not None: await state.clear()
    await q.message.edit_text("🛠 <b>مرکز مدیریت FreeGate</b>",reply_markup=admin());await q.answer()
@r.callback_query(F.data=="a_analytics")
async def aanalytics(q):
    if not admin_ok(q.from_user.id): return
    from .analytics import overview
    x=overview()
    await q.message.edit_text(f"""🧠 <b>Project Analytics</b>\n\n👤 کاربران فعال ۲۴ساعت: <b>{x['dau']}</b>\n🆕 کاربران جدید ۷روز: <b>{x['new_7d']}</b>\n🎯 دعوت موفق ۷روز: <b>{x['qualified_7d']}</b>\n🧪 Feedback ثبت‌شده ۷روز: <b>{x['feedback_7d']}</b>""",reply_markup=admin())
    await q.answer()
@r.callback_query(F.data=="a_quality")
async def aq(q):
    if not admin_ok(q.from_user.id):return
    srcs,tops=quality_stats()
    lines=["📈 <b>مرکز کیفیت منابع و کانفیگ‌ها</b>",""]
    engines=installed()
    lines.append(f"🧪 Health engine: <b>{'sing-box (real probe)' if 'sing-box' in engines else ('TCP/UDP baseline — ' + ', '.join(engines) if engines else 'TCP/UDP baseline')}</b>")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("<b>بهترین منابع</b>")
    for x in srcs[:10]:
        total=x["total"] or 0; healthy=x["healthy"] or 0; conf=x["confirmed"] or 0; bad=x["bad"] or 0
        hr=(healthy/total*100) if total else 0
        fr=(conf/(conf+bad)*100) if conf+bad else 0
        lat=f"{x['latency']:.0f}ms" if x["latency"] is not None else "—"
        score=(hr*0.55+fr*0.35+(max(0,100-min(float(x['latency'] or 9999)/10,100))*0.10))
        lines.append(f"• <b>{x['source']}</b> · score {score:.0f} · health {hr:.0f}% · feedback {fr:.0f}% · {lat}")
    lines.append("\n<b>Top Configs</b>")
    for x in tops[:10]:
        total=x["connected"]+x["reported_bad"]
        rate=(x["connected"]/total*100) if total else 0
        lines.append(f"• #{x['id']} · {x['health']} · {x['latency_ms'] or '—'}ms · feedback {rate:.0f}%")
    await q.message.edit_text("\n".join(lines),reply_markup=admin());await q.answer()
@r.callback_query(F.data=="a_broadcast")
async def abroadcast(q:CallbackQuery,state:FSMContext):
    if not admin_ok(q.from_user.id): return
    await state.set_state(BroadcastState.waiting)
    await q.message.edit_text("📣 <b>پیام همگانی</b>\n\nپیام بعدی را بفرست تا پیش‌نمایش شود.\n\nبعد از پیش‌نمایش باید ارسال را تأیید کنی.")
    await q.answer()
@r.message(BroadcastState.waiting)
async def broadcast_preview(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id): await state.clear(); return
    text=m.text or m.caption or ""
    if not text: return await m.answer("❌ فقط پیام متنی در این نسخه پشتیبانی می‌شود.")
    await state.update_data(text=text); await state.set_state()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 تأیید و ارسال",callback_data="broadcast_send"),InlineKeyboardButton(text="🔴 لغو",callback_data="broadcast_cancel")]])
    await m.answer(f"📣 <b>پیش‌نمایش</b>\n\n{text}\n\n👥 کاربران: <b>{len(users(100000,0))}</b>",reply_markup=kb)
@r.callback_query(F.data=="broadcast_cancel")
async def broadcast_cancel(q:CallbackQuery,state:FSMContext):
    if not admin_ok(q.from_user.id): return
    await state.clear(); await q.message.edit_text("❌ ارسال لغو شد.",reply_markup=admin()); await q.answer()
@r.callback_query(F.data=="broadcast_send")
async def broadcast_send(q:CallbackQuery,state:FSMContext):
    if not admin_ok(q.from_user.id): return
    data=await state.get_data(); text=data.get("text",""); await state.clear()
    rows=users(100000,0); ok=bad=0
    await q.message.edit_text("⏳ ارسال پیام همگانی شروع شد...")
    for u in rows:
        try: await q.bot.send_message(u["uid"],text); ok+=1
        except Exception: bad+=1
        await asyncio.sleep(0.05)
    log_event(q.from_user.id,"broadcast",f"ok={ok},bad={bad}")
    await q.message.edit_text(f"📣 <b>ارسال تمام شد</b>\n\n🟢 موفق: <b>{ok}</b>\n🔴 ناموفق: <b>{bad}</b>",reply_markup=admin()); await q.answer()

@r.callback_query(F.data=="a_fraud")
async def a_fraud(q):
    if not admin_ok(q.from_user.id): return
    flagged=[]
    for u in users(100000,0):
        try:
            ev=events_for(u["uid"],100)
            score=risk_score(ev,int(u.get("qualified",0)))
            if score>=40: flagged.append((u["uid"],score,label(score)))
        except Exception: pass
    lines=["🛡️ <b>Referral Anti-Fraud</b>","━━━━━━━━━━━━━━━━"]
    lines += [f"• <code>{uid}</code> · {lab.upper()} · {score}/100" for uid,score,lab in sorted(flagged,key=lambda x:x[1],reverse=True)[:20]]
    if not flagged: lines.append("✅ مورد مشکوکی دیده نشد.")
    lines.append("\nℹ️ این بخش فقط برای بررسی ادمین است و بر اساس یک سیگنال منفرد مسدود نمی‌کند.")
    await q.message.edit_text("\n".join(lines),reply_markup=admin()); await q.answer()

@r.callback_query(F.data=="a_source_monitor")
async def a_source_monitor(q):
    if not admin_ok(q.from_user.id): return
    try:
        srcs,_=quality_stats()
        lines=["🚨 <b>Source Monitor</b>","━━━━━━━━━━━━━━━━"]
        for x in srcs[:15]:
            total=x["total"] or 0; healthy=x["healthy"] or 0
            hr=healthy/total*100 if total else 0
            conf=x["confirmed"] or 0; bad=x["bad"] or 0
            sr=conf/(conf+bad)*100 if conf+bad else 0
            state=source_state(hr,sr)
            lines.append(f"• <b>{x['source']}</b> · {state} · health {hr:.0f}% · success {sr:.0f}%")
        if len(srcs)<=0: lines.append("هنوز داده‌ای ثبت نشده.")
        await q.message.edit_text("\n".join(lines),reply_markup=admin())
    except Exception:
        await q.message.edit_text("⚠️ داده کافی برای Source Monitor وجود ندارد.",reply_markup=admin())
    await q.answer()


@r.callback_query(F.data=="a_collector_sources")
async def admin_sources(q:CallbackQuery,state:FSMContext=None):
    if not admin_ok(q.from_user.id): return
    if state is not None: await state.clear()
    rows=source_list(True)
    if not rows:
        text="🔌 <b>منابع Collector</b>\n\nهنوز Sourceای اضافه نشده."
    else:
        text="🔌 <b>منابع Collector</b>\n\n🟢 فعال · 🔴 غیرفعال\nبرای افزودن یا حذف Source از دکمه‌های زیر استفاده کن."
    await q.message.edit_text(text,reply_markup=source_admin_kb(rows)); await q.answer()

@r.callback_query(F.data.startswith("src_view:"))
async def source_view(q:CallbackQuery):
    if not admin_ok(q.from_user.id): return
    sid=int(q.data.split(":")[1])
    rows=source_list(True); s=next((x for x in rows if int(x["id"])==sid),None)
    if not s:return await q.answer("Source پیدا نشد",show_alert=True)
    text=(f"🧩 <b>{s['name']}</b>\n"
          f"نوع: <code>{s['kind']}</code>\n"
          f"Endpoint: <code>{s['endpoint']}</code>\n"
          f"اولویت: <b>{s['priority']}</b>\n"
          f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}\n"
          f"Health: <b>{float(s['health_rate'] or 0):.1f}%</b>\n"
          f"Success: <b>{float(s['success_rate'] or 0):.1f}%</b>")
    await q.message.edit_text(text,reply_markup=source_view_kb(sid,bool(s["enabled"]))); await q.answer()

@r.callback_query(F.data.startswith("src_toggle:"))
async def source_toggle_cb(q:CallbackQuery):
    if not admin_ok(q.from_user.id):return
    source_toggle(int(q.data.split(":")[1]))
    await q.answer("وضعیت Source تغییر کرد.")
    rows=source_list(True)
    await q.message.edit_reply_markup(reply_markup=source_admin_kb(rows))

@r.callback_query(F.data.startswith("src_delete:"))
async def source_delete_cb(q:CallbackQuery):
    if not admin_ok(q.from_user.id):return
    sid=int(q.data.split(":")[1])
    source_delete(sid)
    await q.answer("Source حذف شد.")
    rows=source_list(True)
    await q.message.edit_text("🔌 <b>منابع Collector</b>\n\nSource حذف شد.",reply_markup=source_admin_kb(rows))

@r.callback_query(F.data=="src_add")
async def source_add_start(q:CallbackQuery,state:FSMContext):
    if not admin_ok(q.from_user.id):return
    await state.clear()
    await state.set_state(SourceState.add_name)
    await q.message.edit_text("➕ <b>افزودن Source</b>\n\nنام Source را بفرست:")
    await q.answer()

@r.message(SourceState.add_name)
async def source_add_name(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id):return
    name=(m.text or "").strip()
    if not name or len(name)>80:
        return await m.answer("❌ نام نامعتبر است.")
    await state.update_data(name=name); await state.set_state(SourceState.add_kind)
    await m.answer("نوع Source را بفرست:\nمثلاً <code>url</code>، <code>base64</code> یا <code>text</code>")

@r.message(SourceState.add_kind)
async def source_add_kind(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id):return
    kind=(m.text or "").strip().lower()
    if kind not in {"url","api","file","base64","text"}:
        return await m.answer("❌ نوع باید یکی از این‌ها باشد: url / base64 / text")
    await state.update_data(kind=kind); await state.set_state(SourceState.add_endpoint)
    await m.answer("Endpoint یا آدرس Source را بفرست:")

@r.message(SourceState.add_endpoint)
async def source_add_endpoint(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id):return
    endpoint=(m.text or "").strip()
    if not endpoint or len(endpoint)>2000:
        return await m.answer("❌ Endpoint نامعتبر است.")
    await state.update_data(endpoint=endpoint); await state.set_state(SourceState.add_priority)
    await m.answer("اولویت را عددی بفرست. پیش‌فرض: <b>100</b>")

@r.message(SourceState.add_priority)
async def source_add_priority(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id):return
    try: priority=int((m.text or "100").strip())
    except: priority=100
    data=await state.get_data()
    try:
        source_add(data["name"],data["kind"],data["endpoint"],priority)
    except Exception as e:
        await state.clear()
        return await m.answer("❌ افزودن Source انجام نشد؛ احتمالاً نام تکراری است.")
    await state.clear()
    await m.answer("✅ Source با موفقیت اضافه شد.",reply_markup=source_admin_kb(source_list(True)))

@r.callback_query(F.data=="a_stats")
async def ast(q):
    if not admin_ok(q.from_user.id):return
    s=stats();await q.message.edit_text(f"""📊 <b>داشبورد کیفیت پروژه</b>

👤 کاربران: <b>{s['users']}</b>
🤝 دعوت موفق: <b>{s['refs']}</b>
📦 کانفیگ‌های صادرشده: <b>{s['configs']}</b>
🟢 اتصال موفق گزارش‌شده: <b>{s['confirmed']}</b>
🔴 ناموفق گزارش‌شده: <b>{s['bad']}</b>

📈 نرخ موفقیت گزارش‌شده: <b>{(s['confirmed']/(s['confirmed']+s['bad'])*100 if s['confirmed']+s['bad'] else 0):.1f}%</b>""",reply_markup=admin());await q.answer()
@r.callback_query(F.data=="a_users")
async def aus(q):
    if not admin_ok(q.from_user.id):return
    rows=[]
    for u in users():
        name=(u["first_name"] or u["username"] or str(u["uid"]))[:20]
        rows.append([InlineKeyboardButton(text=f"👤 {name} · {u['qualified_refs']} دعوت",url=f"tg://user?id={u['uid']}")])
    rows.append([InlineKeyboardButton(text="↩️ پنل",callback_data="admin")])
    await q.message.edit_text("👥 <b>کاربران اخیر</b>\n\nبا انتخاب هر مورد وارد گفتگوی همان کاربر می‌شوی.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows));await q.answer()
@r.callback_query(F.data=="a_reward")
async def ar(q):
    if not admin_ok(q.from_user.id):return
    await q.message.edit_text(f"""🎁 <b>پاداش و محدودیت</b>

هر <b>{get('required')}</b> دعوت موفق → بسته <b>{get('batch_size')}</b>‌تایی
سهمیه جایگزین هر بسته → <b>{get('replacement_limit')}</b>
سهمیه جایگزین کانفیگ روزانه → <b>{get('daily_replacement_limit')}</b>

تغییر:
<code>/setreward 3</code>
<code>/setreplace 7</code>
<code>/setdailyreplace 2</code>""",reply_markup=admin());await q.answer()
@r.message(Command("setreward"))
async def sr(m):
    if not admin_ok(m.from_user.id): return
    parts=m.text.split(maxsplit=1)
    if len(parts)!=2 or not parts[1].isdigit(): return await m.answer("فرمت: /setreward عدد")
    put("required",max(1,int(parts[1])));await m.answer("✅ تنظیم شد.")
@r.message(Command("setreplace"))
async def srepl(m):
    if not admin_ok(m.from_user.id): return
    parts=m.text.split(maxsplit=1)
    if len(parts)!=2 or not parts[1].isdigit(): return await m.answer("فرمت: /setreplace عدد")
    put("replacement_limit",max(0,int(parts[1])));await m.answer("✅ تنظیم شد.")
@r.message(Command("setdailyreplace"))
async def sdrepl(m):
    if not admin_ok(m.from_user.id): return
    parts=m.text.split(maxsplit=1)
    if len(parts)!=2 or not parts[1].isdigit(): return await m.answer("فرمت: /setdailyreplace عدد")
    put("daily_replacement_limit",max(0,int(parts[1])));await m.answer("✅ تنظیم شد.")
@r.callback_query(F.data=="a_channels")
async def ach(q):
    if not admin_ok(q.from_user.id):return
    cs=channels(True);rows=[[InlineKeyboardButton(text=f"❌ {x['title']}",callback_data=f"dc:{x['id']}")] for x in cs]+[[InlineKeyboardButton(text="➕ راهنمای افزودن",callback_data="addhelp")],[InlineKeyboardButton(text="↩️ پنل",callback_data="admin")]]
    await q.message.edit_text("📢 <b>جویین اجباری</b>\n\nکاربر قبل از ثبت دعوت باید عضویت همه کانال‌های فعال را کامل کند (اگر کاربر از قبل عضو باشد، فرم جویین اصلاً نشان داده نمی‌شود و دعوتش بلافاصله ثبت می‌شود).\n\n<code>/addchannel CHAT_ID | Title | @username | https://t.me/channel</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows));await q.answer()
@r.callback_query(F.data.startswith("dc:"))
async def dc(q):
    if admin_ok(q.from_user.id):del_channel(int(q.data.split(":")[1]));await q.answer("حذف شد.");await ach(q)
@r.callback_query(F.data=="addhelp")
async def ah(q):await q.answer("از دستور /addchannel استفاده کن.",show_alert=True)
@r.message(Command("addchannel"))
async def ac(m):
    if not admin_ok(m.from_user.id):return
    parts=m.text.split(maxsplit=1)
    if len(parts)!=2:return await m.answer("فرمت: /addchannel CHAT_ID | Title | @username | URL")
    p=parts[1].split("|")
    if len(p)!=4:return await m.answer("فرمت: /addchannel CHAT_ID | Title | @username | URL")
    add_channel(*[x.strip() for x in p]);await m.answer("✅ اضافه شد.")
@r.callback_query(F.data=="a_purchase")
async def ap(q):
    if admin_ok(q.from_user.id):await q.message.edit_text(f"🛒 <b>ربات خرید</b>\n\n{get('purchase_url')}\n\n<code>/setpurchase https://t.me/YourBot</code>",reply_markup=admin());await q.answer()
@r.message(Command("setpurchase"))
async def sp(m):
    if not admin_ok(m.from_user.id): return
    parts=m.text.split(maxsplit=1)
    if len(parts)!=2 or not parts[1].startswith(("https://","http://")): return await m.answer("فرمت: /setpurchase https://t.me/YourBot")
    put("purchase_url",parts[1]);await m.answer("✅ ذخیره شد.")

@r.callback_query(F.data=="a_texts")
async def at(q):
    if not admin_ok(q.from_user.id): return
    await q.message.edit_text(
        "📝 <b>متن‌ها و برند</b>\n\n"
        "هر بخش از ربات — از پیام /start و جوین اجباری تا تحویل کانفیگ و پیام‌های اتمام سهمیه — از اینجا قابل ویرایش است.\n"
        "روی هر مورد بزن، متن جدید را بفرست.",
        reply_markup=text_admin_kb())
    await q.answer()

@r.callback_query(F.data.startswith("text_edit:"))
async def text_edit_start(q:CallbackQuery,state:FSMContext):
    if not admin_ok(q.from_user.id): return
    key=q.data.split(":",1)[1]
    if key not in EDITABLE_TEXTS:
        return await q.answer("این مورد پیدا نشد.",show_alert=True)
    label,help_text=EDITABLE_TEXTS[key]
    await state.set_state(TextEditState.waiting)
    await state.update_data(key=key)
    current=get(key)
    await q.message.edit_text(
        f"✏️ <b>{label}</b>\n\n{help_text}\n\n<b>متن فعلی:</b>\n{current}\n\n"
        "متن جدید را بفرست (یا /cancel برای انصراف):")
    await q.answer()

@r.message(Command("cancel"))
async def cancel_edit(m:Message,state:FSMContext):
    cur=await state.get_state()
    if cur:
        await state.clear()
        await m.answer("❌ لغو شد.")

@r.message(TextEditState.waiting)
async def text_edit_save(m:Message,state:FSMContext):
    if not admin_ok(m.from_user.id): await state.clear(); return
    data=await state.get_data(); key=data.get("key")
    text=m.text or m.caption or ""
    if not text or key not in EDITABLE_TEXTS:
        await state.clear(); return await m.answer("❌ متن نامعتبر است.")
    put(key,text)
    await state.clear()
    label,_=EDITABLE_TEXTS[key]
    await m.answer(f"✅ «{label}» ذخیره شد.",reply_markup=text_admin_kb())

@r.message(Command("refresh"))
async def refresh(m):
    if not admin_ok(m.from_user.id):return
    data=await collect(force=True)
    await m.answer(f"🔄 Collector refresh شد.\n\nتعداد آیتم‌های یکتا در استخر: {len(data)}")
@r.message(Command("dbcheck"))
async def dbcheck(m):
    if not admin_ok(m.from_user.id): return
    from .config import USE_TURSO
    await m.answer("🗄 <b>Database</b>\n\nBackend: <b>%s</b>" % ("Turso Cloud (libSQL)" if USE_TURSO else "Local SQLite"))
app=Flask(__name__)

@app.get("/")
def home():
    return {"service":"FreeGate","ok":True}

@app.get("/health")
def health():
    return {"ok":True,"service":"freegate"},200

@app.get("/sub/<token>")
def sub(token):
    x=reward(token)
    if not x:
        abort(404)
    return x["uri"]+"\n",200,{"Content-Type":"text/plain; charset=utf-8"}

def web():
    from waitress import serve
    serve(app, host="0.0.0.0", port=PORT, threads=4)

async def keepalive():
    """Optional outbound watchdog while the process is already awake.

    A sleeping Render Free instance cannot execute this coroutine, so an
    external monitor must request /health to provide inbound traffic.
    """
    if not KEEPALIVE_ENABLED or not KEEPALIVE_URL:
        return
    url=f"{KEEPALIVE_URL}/health"
    timeout=aiohttp.ClientTimeout(total=15)
    await asyncio.sleep(5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(url) as resp:
                    log.info("keepalive %s -> %s", url, resp.status)
            except Exception as exc:
                log.warning("keepalive failed: %s", exc)
            await asyncio.sleep(max(60, KEEPALIVE_INTERVAL))

async def main():
    init()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode="HTML"))
    dp=Dispatcher(storage=MemoryStorage())
    dp.include_router(r)
    threading.Thread(target=web, name="flask-web", daemon=True).start()
    tasks=[dp.start_polling(bot)]
    if KEEPALIVE_ENABLED and KEEPALIVE_URL:
        tasks.append(keepalive())
    await asyncio.gather(*tasks)

if __name__=="__main__":
    asyncio.run(main())

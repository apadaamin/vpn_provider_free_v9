from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
from .db import channels,EDITABLE_TEXTS,get
def join():
    rows=[[InlineKeyboardButton(text=f"📢 {x['title']}",url=x["url"])] for x in channels()]
    rows.append([InlineKeyboardButton(text="🟢 بررسی عضویت و ورود",callback_data="join_check")]);return InlineKeyboardMarkup(inline_keyboard=rows)
def main(unlocked=False):
    # Clean glass/polymer look: one consistent accent glyph instead of
    # three different colored status dots.
    rows=[
      [InlineKeyboardButton(text="◈ 🎁 سرویس‌های من",callback_data="services")],
      [InlineKeyboardButton(text="◈ 🔗 لینک دعوت من",callback_data="ref")],
    ]
    rows.append([InlineKeyboardButton(text=("◈ 🎲 کانفیگ رایگان روزانه" if unlocked else "◈ 🔒 کانفیگ رایگان روزانه"),callback_data="daily_free")])
    rows.append([InlineKeyboardButton(text="◈ 📊 آمار و کیفیت",callback_data="stats")])
    rows.append([InlineKeyboardButton(text="🚀 سرویس اختصاصی و پایدار",url=get("purchase_url"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def back():return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ بازگشت",callback_data="menu")]])
def feedback(cid):
    return InlineKeyboardMarkup(inline_keyboard=[[
      InlineKeyboardButton(text="🟢 متصل شدم",callback_data=f"ok:{cid}"),
      InlineKeyboardButton(text="🔴 متصل نشدم",callback_data=f"bad:{cid}")]])
def purchase_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="🚀 مشاهده سرویس اختصاصی",url=get("purchase_url"))],
      [InlineKeyboardButton(text="↩️ منوی اصلی",callback_data="menu")]])
def services(rows):
    kb=[[InlineKeyboardButton(text=f"◈ 🎁 سرویس #{i+1}",url=f"/sub/{r['token']}")] for i,r in enumerate(rows)]
    kb.append([InlineKeyboardButton(text="↩️ منوی اصلی",callback_data="menu")]);return InlineKeyboardMarkup(inline_keyboard=kb)
def admin():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="📊 داشبورد",callback_data="a_stats"),InlineKeyboardButton(text="👥 کاربران",callback_data="a_users")],
      [InlineKeyboardButton(text="📢 جویین اجباری",callback_data="a_channels")],
      [InlineKeyboardButton(text="📈 کیفیت منابع و کانفیگ‌ها",callback_data="a_quality")],
      [InlineKeyboardButton(text="🛡️ Anti-Fraud",callback_data="a_fraud"), InlineKeyboardButton(text="🚨 Source Monitor",callback_data="a_source_monitor")],
      [InlineKeyboardButton(text="🧠 آنالیز پروژه",callback_data="a_analytics")],
      [InlineKeyboardButton(text="🎁 پاداش و محدودیت",callback_data="a_reward")],
      [InlineKeyboardButton(text="📝 متن‌ها و برند",callback_data="a_texts")],
      [InlineKeyboardButton(text="🔌 منابع Collector",callback_data="a_collector_sources")],
      [InlineKeyboardButton(text="🛒 لینک خرید",callback_data="a_purchase")],
      [InlineKeyboardButton(text="📣 پیام همگانی",callback_data="a_broadcast")]])

def text_admin_kb():
    rows=[[InlineKeyboardButton(text=label,callback_data=f"text_edit:{key}")] for key,(label,_) in EDITABLE_TEXTS.items()]
    rows.append([InlineKeyboardButton(text="⬅️ پنل",callback_data="a_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import (
    TelegramError,
    RetryAfter,
    Forbidden,
    BadRequest,
    NetworkError,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Configuration — all secrets come from Railway environment variables.
# ---------------------------------------------------------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "")
POST_CHANNEL_ID_RAW = os.getenv("POST_CHANNEL_ID", "")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("novapay")

if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN is not set. Set it in Railway Variables.")
    raise SystemExit(1)

try:
    ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else None
except ValueError:
    logger.critical("ADMIN_ID must be an integer Telegram user ID.")
    raise SystemExit(1)

try:
    POST_CHANNEL_ID = int(POST_CHANNEL_ID_RAW) if POST_CHANNEL_ID_RAW else None
except ValueError:
    logger.critical("POST_CHANNEL_ID must be a numeric chat ID (e.g. -1001234567890).")
    raise SystemExit(1)

POST_INTERVAL_SECONDS = 600  # 10 minutes
STATE_FILE = Path("novapay_state.json")
JOB_NAME = "novapay_autopost"

# ---------------------------------------------------------------------------
# Content library — evergreen educational posts. No statistics, news, or
# profit claims. Each entry is a distinct, self-contained lesson.
# ---------------------------------------------------------------------------
POSTS = [
    {
        "title": "🔐 What makes a strong password?",
        "body": (
            "A strong password is long (12+ characters), unique to each account, "
            "and combines unrelated words or characters. Length matters more than "
            "complexity. Use a password manager so you never reuse a password "
            "across sites. If one site is breached, reused passwords let attackers "
            "try the same credentials elsewhere — a practice known as credential "
            "stuffing."
        ),
        "category": "Cybersecurity",
    },
    {
        "title": "🎣 How to spot a phishing message",
        "body": (
            "Phishing messages often create urgency ('Your account will be closed'), "
            "ask you to click a link, or request login codes. Check the sender "
            "address carefully, hover over links before tapping, and never share "
            "one-time codes. Legitimate services rarely ask for passwords by email "
            "or chat. When in doubt, open the service directly instead of using the "
            "link."
        ),
        "category": "Fraud prevention",
    },
    {
        "title": "💳 Debit vs. credit: what is the difference?",
        "body": (
            "A debit card spends money already in your account. A credit card "
            "borrows money up to a limit and must be repaid. Debit limits spending "
            "to your balance, while credit can help build a credit history if you "
            "pay in full and on time. Credit cards may also offer stronger dispute "
            "protections in some jurisdictions. Neither is universally 'better' — "
            "the right choice depends on your habits."
        ),
        "category": "Financial literacy",
    },
    {
        "title": "🧾 Why you should read terms before accepting",
        "body": (
            "Terms of service and privacy policies explain what data a service "
            "collects, how it is used, and what rights you give up. Look for "
            "sections on data sharing, cancellation, refunds, and dispute "
            "resolution. You do not need to read every word, but scanning headings "
            "for these topics takes a minute and can prevent unpleasant surprises."
        ),
        "category": "Digital rights",
    },
    {
        "title": "🌐 Public Wi-Fi safety basics",
        "body": (
            "On public Wi-Fi, avoid logging into sensitive accounts unless you use "
            "a trusted VPN. Prefer HTTPS sites (look for the padlock), turn off "
            "file sharing, and forget the network when you leave. Attackers on the "
            "same network can sometimes intercept unencrypted traffic. Mobile data "
            "or a personal hotspot is often safer for banking and email."
        ),
        "category": "Internet safety",
    },
    {
        "title": "🪙 Crypto basics: wallets and keys",
        "body": (
            "A crypto wallet does not 'store' coins — it stores keys that prove "
            "ownership on a blockchain. A public address receives funds; a private "
            "key or seed phrase controls them. Whoever holds the seed phrase "
            "controls the funds. Never share a seed phrase, and treat any request "
            "for it as a scam. This is general education, not investment advice."
        ),
        "category": "Cryptocurrency education",
    },
    {
        "title": "📱 App permissions: less is more",
        "body": (
            "When an app requests access to your contacts, microphone, location, or "
            "photos, ask whether that access is necessary for the app’s core "
            "function. A flashlight app does not need your contacts. Review "
            "permissions in your phone settings periodically and revoke access "
            "that no longer makes sense."
        ),
        "category": "Online privacy",
    },
    {
        "title": "🧠 Social engineering: the human firewall",
        "body": (
            "Social engineering manipulates people rather than software. Common "
            "tactics include impersonating support staff, offering prizes, or "
            "pretending to be a colleague in a hurry. Slow down when someone "
            "pressures you to act immediately. Verify identity through a separate, "
            "known channel before sharing information or moving money."
        ),
        "category": "Cybersecurity",
    },
    {
        "title": "💸 Understanding interest on savings",
        "body": (
            "Interest is the cost of borrowing money or the reward for saving it. "
            "On savings, compound interest means you earn interest on interest over "
            "time. The frequency of compounding and the annual rate both affect the "
            "final amount. Compare the annual percentage yield (APY) rather than "
            "the nominal rate when comparing savings products."
        ),
        "category": "Financial literacy",
    },
    {
        "title": "🔁 Two-factor authentication (2FA) explained",
        "body": (
            "2FA adds a second proof of identity beyond a password — often a code "
            "from an app or a hardware key. App-based codes and hardware keys are "
            "generally safer than SMS codes, which can be intercepted. Enable 2FA "
            "on email, banking, and social accounts first; email is often the "
            "recovery path for everything else."
        ),
        "category": "Cybersecurity",
    },
    {
        "title": "🧐 How to check a website before entering data",
        "body": (
            "Check the domain name carefully — attackers use lookalike characters "
            "and extra words. Look for HTTPS, but remember that HTTPS alone does "
            "not prove a site is honest. Search for independent reviews, look for a "
            "physical address or contact page, and be cautious of sites that ask "
            "for more information than the service requires."
        ),
        "category": "Online payment safety",
    },
    {
        "title": "📊 Needs vs. wants in budgeting",
        "body": (
            "A simple budget starts by separating needs (housing, food, utilities, "
            "transport) from wants (entertainment, upgrades, non-essential "
            "subscriptions). Cover needs first, then allocate a planned amount to "
            "wants and savings. Tracking spending for one month often reveals "
            "small recurring costs that add up."
        ),
        "category": "Financial literacy",
    },
]

# ---------------------------------------------------------------------------
# Persistent state helpers
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read state file: %s", exc)
    return {"last_hash": None, "last_posted_at": None, "posting_enabled": True}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Could not write state file: %s", exc)


def content_hash(post: dict) -> str:
    raw = f"{post['title']}|{post['body']}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def pick_next_post(state: dict) -> dict:
    """Return a post whose hash differs from the last published hash."""
    last = state.get("last_hash")
    for post in POSTS:
        if content_hash(post) != last:
            return post
    return POSTS[0]  # fallback; all posts were already published


# ---------------------------------------------------------------------------
# Core publishing logic
# ---------------------------------------------------------------------------
async def send_educational_post(
    application: Application, state: dict, manual: bool = False
) -> bool:
    """
    Send one educational post to POST_CHANNEL_ID.
    Returns True if a post was sent, False otherwise.
    """
    if not POST_CHANNEL_ID:
        logger.warning(
            "POST_CHANNEL_ID is not configured. "
            "Set it to a channel or group ID where the bot is an administrator."
        )
        return False

    if not state.get("posting_enabled", True) and not manual:
        logger.info("Automatic posting is disabled. Skipping scheduled post.")
        return False

    post = pick_next_post(state)
    text = (
        f"<b>{post['title']}</b>\n\n"
        f"{post['body']}\n\n"
        f"<i>Category: {post['category']} · Educational content only, not financial advice.</i>"
    )

    try:
        await application.bot.send_message(
            chat_id=POST_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except RetryAfter as exc:
        delay = int(exc.retry_after) + 1
        logger.warning("Rate limited by Telegram. Retrying in %s seconds.", delay)
        await asyncio.sleep(delay)
        try:
            await application.bot.send_message(
                chat_id=POST_CHANNEL_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError as retry_exc:
            logger.error("Retry failed: %s", retry_exc)
            return False
    except Forbidden:
        logger.error(
            "Bot is not allowed to post in chat %s. "
            "Make sure the bot is an administrator with post permissions.",
            POST_CHANNEL_ID,
        )
        return False
    except BadRequest as exc:
        logger.error("Bad request while posting: %s", exc)
        return False
    except NetworkError as exc:
        logger.error("Network error while posting: %s", exc)
        return False
    except TelegramError as exc:
        logger.error("Telegram error while posting: %s", exc)
        return False

    state["last_hash"] = content_hash(post)
    state["last_posted_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    logger.info("Published: %s", post["title"])
    return True


async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback — runs every POST_INTERVAL_SECONDS."""
    application = context.application
    state = load_state()
    await send_educational_post(application, state, manual=False)


# ---------------------------------------------------------------------------
# User-facing handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 Welcome to <b>NovaPay Educational</b>.\n\n"
        "This bot shares free, practical lessons about financial literacy, "
        "digital payment safety, cybersecurity, fraud prevention, and online "
        "privacy.\n\n"
        "It does <b>not</b> process payments, hold balances, offer investments, "
        "or promise earnings. Everything here is general education.\n\n"
        "Use /help to see what you can do."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Available commands</b>\n\n"
        "/start — Welcome and purpose\n"
        "/help — This message\n"
        "/about — About NovaPay\n"
        "/topics — Educational categories\n"
        "/latest — Show the most recent post\n"
        "/subscribe — Opt into occasional private updates\n"
        "/unsubscribe — Stop private updates\n"
        "/admin — Administrator panel (authorized users only)"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>About NovaPay Educational</b>\n\n"
        "NovaPay is an information-sharing bot. It publishes educational content "
        "on personal finance literacy, digital safety, and technology. It is not "
        "a bank, payment processor, wallet, or investment platform.\n\n"
        "Content is general and educational. It is not personalized financial "
        "advice. Always consult a qualified professional for decisions that "
        "affect your money."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    categories = sorted({post["category"] for post in POSTS})
    lines = "\n".join(f"• {cat}" for cat in categories)
    text = f"<b>Topics covered</b>\n\n{lines}\n\nUse /latest to see the most recent post."
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    post = pick_next_post(state)
    text = (
        f"<b>{post['title']}</b>\n\n"
        f"{post['body']}\n\n"
        f"<i>Category: {post['category']} · Educational content only, not financial advice.</i>"
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Private updates are stored in memory only; this bot does not run a
    # broadcast system for ordinary users. Subscription confirms intent.
    user = update.effective_user
    context.bot_data.setdefault("subscribers", set()).add(user.id)
    await update.effective_message.reply_text(
        "✅ You are subscribed to occasional private educational notes from NovaPay. "
        "Use /unsubscribe at any time."
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    context.bot_data.get("subscribers", set()).discard(user.id)
    await update.effective_message.reply_text(
        "You have been unsubscribed from private notes. The bot will not message "
        "you privately unless you contact it first."
    )


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("⛔ Unauthorized.")
        return

    state = load_state()
    status = "enabled" if state.get("posting_enabled", True) else "disabled"
    last_at = state.get("last_posted_at") or "never"
    channel = str(POST_CHANNEL_ID) if POST_CHANNEL_ID else "not configured"

    text = (
        "<b>Administrator panel</b>\n\n"
        f"Automatic posting: <b>{status}</b>\n"
        f"Last posted: {last_at}\n"
        f"Destination: {channel}\n"
        f"Interval: every {POST_INTERVAL_SECONDS // 60} minutes\n\n"
        "Use the buttons below."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "▶️ Post now", callback_data="admin_post_now"
                ),
                InlineKeyboardButton(
                    "⏸ Toggle auto", callback_data="admin_toggle"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📊 Status", callback_data="admin_status"
                ),
            ],
        ]
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    state = load_state()
    action = query.data

    if action == "admin_post_now":
        sent = await send_educational_post(context.application, state, manual=True)
        result = "✅ Posted." if sent else "⚠️ Could not post. Check logs and POST_CHANNEL_ID."
        await query.edit_message_text(result)

    elif action == "admin_toggle":
        state["posting_enabled"] = not state.get("posting_enabled", True)
        save_state(state)
        status = "enabled" if state["posting_enabled"] else "disabled"
        await query.edit_message_text(f"Automatic posting is now <b>{status}</b>.", parse_mode=ParseMode.HTML)

    elif action == "admin_status":
        last_at = state.get("last_posted_at") or "never"
        status = "enabled" if state.get("posting_enabled", True) else "disabled"
        channel = str(POST_CHANNEL_ID) if POST_CHANNEL_ID else "not configured"
        await query.edit_message_text(
            f"Posting: <b>{status}</b>\nLast: {last_at}\nDestination: {channel}",
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Error handler — keeps internal details out of user replies.
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong. Please try again later."
            )
        except TelegramError:
            pass


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------
def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(False)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("topics", topics))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(
        CallbackQueryHandler(admin_callback, pattern=r"^admin_")
    )
    application.add_error_handler(error_handler)

    return application


def main() -> None:
    application = build_application()

    # Register the repeating job only once. PTB's JobQueue is backed by
    # APScheduler's AsyncIOScheduler, so this runs inside the bot's event loop.
    job_queue = application.job_queue
    job_queue.run_repeating(
        scheduled_post_job,
        interval=POST_INTERVAL_SECONDS,
        first=10,  # first post 10 seconds after startup
        name=JOB_NAME,
    )

    logger.info(
        "NovaPay starting | interval=%ss | destination=%s",
        POST_INTERVAL_SECONDS,
        POST_CHANNEL_ID or "not configured",
    )
    # run_polling installs SIGTERM/SIGINT handlers for graceful shutdown.
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()

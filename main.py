import os, logging, asyncio, uuid, re
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserNotParticipant
from pymongo import MongoClient
from urllib.parse import quote_plus
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = os.getenv("API_ID", "16015294")
API_HASH = os.getenv("API_HASH", "e4fc842483c5de0f920ebba329c1a906")
BOT_TOKEN = os.getenv("BOT_TOKEN", "7421206619:AAEzDR7gPRHvwLM8uadNCRI3kyq7DA73YKw")
DB_CHANNEL = int(os.getenv("DB_CHANNEL", "-1002649940692"))
UPDATES_CHANNEL = os.getenv("UPDATES_CHANNEL", "YoursUpdateHere")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7499642616").split()]
DATABASE_URL = os.getenv("DATABASE_URL", "mongodb+srv://karan69:karan69@cluster0.gfw7e.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
SLEEP_THRESHOLD = int(os.getenv("SLEEP_THRESHOLD", 60))
WORKERS = int(os.getenv("WORKERS", 8))

# Initialize MongoDB client
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client["telegram_file_store"]
files_collection = db["files"]
users_collection = db["users"]
trials_collection = db["trials"]

# Initialize Pyrogram client
app = Client(
    name="FileStoreBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=WORKERS
)

# Content filter for inappropriate messages
BAD_WORDS = [
    r'\b(sex|porn|adult|explicit|nude|xxx)\b',
    r'\b(violence|kill|murder|assault)\b',
    r'\b(hack|crack|exploit|malware)\b'
]

def is_inappropriate(text):
    """Check if message contains inappropriate content."""
    if not text:
        return False
    text = text.lower()
    for pattern in BAD_WORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

async def check_subscription(client, user_id):
    """Check if user is subscribed to the updates channel."""
    try:
        if UPDATES_CHANNEL:
            await client.get_chat_member(UPDATES_CHANNEL, user_id)
            return True
        return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

async def check_trial_limit(user_id, is_premium):
    """Check and update user's trial count."""
    if is_premium or user_id in ADMIN_IDS:
        return True
    
    user_trial = trials_collection.find_one({"user_id": user_id})
    if not user_trial:
        trials_collection.insert_one({
            "user_id": user_id,
            "trials": 1,
            "last_used": datetime.utcnow(),
            "payment_status": "pending",
            "payment_amount": 0,
            "activated_by": None,
            "activation_date": None
        })
        return True
    elif user_trial["trials"] < 2:
        trials_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"trials": 1}, "$set": {"last_used": datetime.utcnow()}}
        )
        return True
    elif user_trial["payment_status"] == "completed" and user_trial["trials"] >= 2:
        trials_collection.update_one(
            {"user_id": user_id},
            {"$set": {"trials": 0, "last_used": datetime.utcnow()}}
        )
        return True
    return False

async def send_welcome_message(message):
    """Send customizable welcome message."""
    welcome_text = (
        "Welcome to the File Store Bot! 📁\n"
        "Upload files to get shareable links.\n"
        "Use /help for more information."
    )
    await message.reply_text(welcome_text, disable_web_page_preview=True)

async def generate_unique_link(file_id, batch=False):
    """Generate a unique link for file or batch."""
    unique_id = str(uuid.uuid4())
    files_collection.insert_one({
        "unique_id": unique_id,
        "file_id": file_id,
        "batch": batch,
        "created_at": datetime.utcnow()
    })
    bot_username = (await app.get_me()).username
    return f"https://t.me/{bot_username}?start={unique_id}"

async def is_authorized_user(user_id):
    """Check if user is authorized (admin or subscribed)."""
    if user_id in ADMIN_IDS:
        return True
    return await check_subscription(app, user_id)

async def delete_messages_after_delay(client, chat_id, message_ids):
    """Delete messages after 1 minute."""
    await asyncio.sleep(60)  # 1 minute delay
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except Exception as e:
        logger.error(f"Error deleting messages: {e}")

async def show_subscription_plans(message):
    """Show premium subscription plans."""
    plans_text = (
        "You've exceeded your free trial limit!\n"
        "Please subscribe to continue using the bot:\n\n"
        "🌟 Premium Plans:\n"
        "- Monthly: Unlimited uploads, priority support\n"
        "- Yearly: Unlimited uploads, priority support, exclusive features\n\n"
        "Use /subscribe to pay with Telegram Stars or visit https://x.ai/grok for more details."
    )
    await message.reply_text(plans_text, disable_web_page_preview=True)

# Command handlers
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    """Handle /start command."""
    user_id = message.from_user.id
    if not await is_authorized_user(user_id):
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]]),
            disable_web_page_preview=True
        )
        return
    await send_welcome_message(message)
    
    if len(message.command) > 1:
        unique_id = message.command[1]
        file_data = files_collection.find_one({"unique_id": unique_id})
        if file_data:
            try:
                if file_data["batch"]:
                    batch_files = files_collection.find({"batch_id": file_data["unique_id"]})
                    message_ids = []
                    for file in batch_files:
                        msg = await client.forward_messages(
                            chat_id=message.chat.id,
                            from_chat_id=DB_CHANNEL,
                            message_ids=file["file_id"],
                            disable_notification=True
                        )
                        message_ids.append(msg.id)
                    asyncio.create_task(delete_messages_after_delay(client, message.chat.id, message_ids))
                else:
                    msg = await client.forward_messages(
                        chat_id=message.chat.id,
                        from_chat_id=DB_CHANNEL,
                        message_ids=file_data["file_id"],
                        disable_notification=True
                    )
                    asyncio.create_task(delete_messages_after_delay(client, message.chat.id, [msg.id]))
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await client.forward_messages(
                    chat_id=message.chat.id,
                    from_chat_id=DB_CHANNEL,
                    message_ids=file_data["file_id"],
                    disable_notification=True
                )
            except Exception as e:
                logger.error(f"Error forwarding file: {e}")
                await message.reply_text("Error retrieving file. Please try again.", disable_web_page_preview=True)

@app.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    """Handle /help command."""
    help_text = (
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/batch - Generate a link for multiple files\n"
        "/subscribe - Pay with Telegram Stars to activate your trial\n"
        "/submit_payment <transaction_id> - Submit payment proof for verification\n"
        "Admin commands:\n"
        "/broadcast - Broadcast a message to all users\n"
        "/stats - Show bot statistics\n"
        "/activate_trial <user_id> - Activate trial for a specific user\n\n"
        "Note: Free users get 2 trials. Telegram Premium users can save messages."
    )
    await message.reply_text(help_text, disable_web_page_preview=True)

@app.on_message(filters.command("subscribe") & filters.private)
async def subscribe_command(client, message):
    """Handle /subscribe command to guide users on paying with Telegram Stars."""
    user_id = message.from_user.id
    if await is_authorized_user(user_id):
        payment_text = (
            "To continue using the bot, please purchase a subscription with Telegram Stars:\n"
            "- Send 100 Telegram Stars to @BotOwnerUsername.\n"
            "- After payment, reply with the transaction ID or contact the admin.\n"
            "- Once verified, your trial will be activated for 2 more uploads.\n\n"
            "Note: Payments are manually verified by the admin."
        )
        await message.reply_text(payment_text, disable_web_page_preview=True)
        
        trials_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "payment_status": "pending",
                    "payment_amount": 100,
                    "last_payment_request": datetime.utcnow()
                }
            },
            upsert=True
        )
    else:
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]]),
            disable_web_page_preview=True
        )

@app.on_message(filters.command("submit_payment") & filters.private)
async def submit_payment_command(client, message):
    """Handle /submit_payment <transaction_id> command to submit payment proof."""
    user_id = message.from_user.id
    if len(message.command) != 2:
        await message.reply_text("Usage: /submit_payment <transaction_id>", disable_web_page_preview=True)
        return
    
    transaction_id = message.command[1]
    try:
        trials_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "transaction_id": transaction_id,
                    "payment_status": "pending_verification",
                    "payment_submitted_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await client.send_message(
                    chat_id=admin_id,
                    text=f"New payment submission:\nUser ID: {user_id}\nTransaction ID: {transaction_id}\nPlease verify and use /activate_trial {user_id} to activate.",
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Error notifying admin {admin_id}: {e}")
        
        await message.reply_text(
            "Payment submitted. Please wait for admin verification.",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error submitting payment: {e}")
        await message.reply_text("Error submitting payment. Please try again.", disable_web_page_preview=True)

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    """Handle /batch command for multiple file links."""
    user_id = message.from_user.id
    if not await is_authorized_user(user_id):
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]]),
            disable_web_page_preview=True
        )
        return
    await message.reply_text("Please forward the files you want to include in the batch.", disable_web_page_preview=True)

@app.on_message(filters.command("broadcast") & filters.private & filters.user(ADMIN_IDS))
async def broadcast_command(client, message):
    """Handle /broadcast command for admins."""
    if not message.reply_to_message:
        await message.reply_text("Please reply to a message to broadcast.", disable_web_page_preview=True)
        return
    users = users_collection.find()
    success_count = 0
    for user in users:
        try:
            await message.reply_to_message.forward(user["user_id"], disable_notification=True)
            success_count += 1
            await asyncio.sleep(0.5)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error broadcasting to {user['user_id']}: {e}")
    await message.reply_text(f"Broadcast sent to {success_count} users.", disable_web_page_preview=True)

@app.on_message(filters.command("stats") & filters.private & filters.user(ADMIN_IDS))
async def stats_command(client, message):
    """Handle /stats command for admins."""
    user_count = users_collection.count_documents({})
    file_count = files_collection.count_documents({})
    trial_count = trials_collection.count_documents({"trials": {"$gte": 2}})
    await message.reply_text(
        f"Bot Stats:\nUsers: {user_count}\nFiles: {file_count}\nUsers on max trials: {trial_count}",
        disable_web_page_preview=True
    )

@app.on_message(filters.command("activate_trial") & filters.private & filters.user(ADMIN_IDS))
async def activate_trial_command(client, message):
    """Handle /activate_trial <user_id> command for admins to activate a user's trial."""
    if len(message.command) != 2:
        await message.reply_text("Usage: /activate_trial <user_id>", disable_web_page_preview=True)
        return
    
    try:
        target_user_id = int(message.command[1])
        admin_id = message.from_user.id
        
        user_trial = trials_collection.find_one({"user_id": target_user_id})
        if not user_trial:
            await message.reply_text("User has not initiated any trials.", disable_web_page_preview=True)
            return
        
        trials_collection.update_one(
            {"user_id": target_user_id},
            {
                "$set": {
                    "trials": 0,
                    "payment_status": "completed",
                    "activated_by": admin_id,
                    "activation_date": datetime.utcnow()
                }
            }
        )
        
        try:
            await client.send_message(
                chat_id=target_user_id,
                text="🎉 Your trial has been activated! You can now upload 2 more files.",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error notifying user {target_user_id}: {e}")
        
        await message.reply_text(f"Trial activated for user {target_user_id}.", disable_web_page_preview=True)
    
    except ValueError:
        await message.reply_text("Invalid user ID format.", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error activating trial: {e}")
        await message.reply_text("Error activating trial. Please try again.", disable_web_page_preview=True)

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    """Handle text messages for inappropriate content."""
    user_id = message.from_user.id
    if is_inappropriate(message.text):
        await message.reply_text(
            "⚠️ Warning: Inappropriate content detected. Please refrain from sending such messages.",
            disable_web_page_preview=True
        )
        user = users_collection.find_one({"user_id": user_id})
        warnings = user.get("warnings", 0) + 1 if user else 1
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"warnings": warnings}},
            upsert=True
        )
        if warnings >= 3:
            await client.block_user(user_id)
            await message.reply_text("🚫 You have been blocked for repeated inappropriate content.", disable_web_page_preview=True)
        return
    await message.reply_text("Please send a file to store or use a command.", disable_web_page_preview=True)

@app.on_message(filters.media & filters.private)
async def handle_media(client, message):
    """Handle file uploads and store in DB channel."""
    user_id = message.from_user.id
    is_premium = getattr(message.from_user, "is_premium", False)
    
    if not await is_authorized_user(user_id):
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]]),
            disable_web_page_preview=True
        )
        return

    if not await check_trial_limit(user_id, is_premium):
        await show_subscription_plans(message)
        return

    try:
        if message.caption and is_inappropriate(message.caption):
            await message.reply_text(
                "⚠️ Warning: Inappropriate caption detected. File not stored.",
                disable_web_page_preview=True
            )
            user = users_collection.find_one({"user_id": user_id})
            warnings = user.get("warnings", 0) + 1 if user else 1
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"warnings": warnings}},
                upsert=True
            )
            if warnings >= 3:
                await client.block_user(user_id)
                await message.reply_text("🚫 You have been blocked for repeated inappropriate content.", disable_web_page_preview=True)
            return

        forwarded = await message.forward(DB_CHANNEL, disable_notification=True)
        file_id = forwarded.id
        file_name = message.document.file_name if message.document else message.caption or "Unnamed"
        file_size = message.document.file_size if message.document else 0

        unique_link = await generate_unique_link(file_id)
        files_collection.insert_one({
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "user_id": user_id,
            "unique_id": unique_link.split("=")[-1],
            "created_at": datetime.utcnow()
        })

        if not users_collection.find_one({"user_id": user_id}):
            users_collection.insert_one({
                "user_id": user_id,
                "username": message.from_user.username,
                "joined_at": datetime.utcnow(),
                "is_premium": is_premium
            })

        reply = await message.reply_text(
            f"File stored successfully!\nShareable link: {unique_link}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Share", url=unique_link)
            ]]),
            disable_web_page_preview=True,
            disable_notification=True,
            protect_content=not is_premium
        )
        await send_welcome_message(message)
        
        asyncio.create_task(delete_messages_after_delay(client, message.chat.id, [message.id, reply.id]))

    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.reply_text("Flood wait triggered. Please try again later.", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error handling media: {e}")
        await message.reply_text("Error storing file. Please try again.", disable_web_page_preview=True)

async def main():
    await app.start()
    logger.info("Bot started successfully")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

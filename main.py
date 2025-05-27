import os, logging, asyncio, uuid, re
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserNotParticipant
from pymongo import MongoClient
from urllib.parse import quote_plus
from datetime import datetime

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

async def is_admin(user_id):
    """Check if user is an admin."""
    return user_id in ADMIN_IDS

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

async def send_welcome_message(message):
    """Send customizable welcome message for admins."""
    welcome_text = (
        "Welcome to the File Store Bot! 📁\n"
        "This bot is for admin use only. Upload files to get shareable links.\n"
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

async def delete_messages_after_delay(client, chat_id, message_ids):
    """Delete messages after 1 minute."""
    await asyncio.sleep(60)  # 1 minute delay
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except Exception as e:
        logger.error(f"Error deleting messages: {e}")

# Command handlers
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    """Handle /start command."""
    user_id = message.from_user.id
    if await is_admin(user_id):
        await send_welcome_message(message)
    else:
        if not await check_subscription(client, user_id):
            await message.reply_text(
                f"Please subscribe to {UPDATES_CHANNEL} to view files.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
                ]]),
                disable_web_page_preview=True
            )
            return
    
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
        else:
            if not await is_admin(user_id):
                await message.reply_text(
                    "Invalid or expired file link. Please contact an admin for assistance.",
                    disable_web_page_preview=True
                )
            else:
                await message.reply_text(
                    "Invalid or expired file link.",
                    disable_web_page_preview=True
                )
    elif not await is_admin(user_id):
        await message.reply_text(
            "🚫 Access Denied: Only admins can use this bot. Use a valid file link to view content after joining the channel.",
            disable_web_page_preview=True
        )

@app.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    """Handle /help command."""
    user_id = message.from_user.id
    if not await is_admin(user_id):
        await message.reply_text(
            "🚫 Access Denied: This bot is for admin use only. Non-admins can only view files using links after joining the channel.",
            disable_web_page_preview=True
        )
        return
    help_text = (
        "Available commands (Admin Only):\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/batch - Generate a link for multiple files\n"
        "/broadcast - Broadcast a message to all users\n"
        "/stats - Show bot statistics\n"
    )
    await message.reply_text(help_text, disable_web_page_preview=True)

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    """Handle /batch command for multiple file links."""
    user_id = message.from_user.id
    if not await is_admin(user_id):
        await message.reply_text(
            "🚫 Access Denied: This bot is for admin use only. Non-admins can only view files using links after joining the channel.",
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
    await message.reply_text(
        f"Bot Stats:\nUsers: {user_count}\nFiles: {file_count}",
        disable_web_page_preview=True
    )

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    """Handle text messages for inappropriate content."""
    user_id = message.from_user.id
    if not await is_admin(user_id):
        await message.reply_text(
            "🚫 Access Denied: This bot is for admin use only. Non-admins can only view files using links after joining the channel.",
            disable_web_page_preview=True
        )
        return
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

# File upload handler
@app.on_message(filters.media & filters.private)
async def handle_media(client, message):
    """Handle file uploads and store in DB channel."""
    user_id = message.from_user.id
    if not await is_admin(user_id):
        await message.reply_text(
            "🚫 Access Denied: This bot is for admin use only. Non-admins can only view files using links after joining the channel.",
            disable_web_page_preview=True
        )
        return

    try:
        # Check for inappropriate caption
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

        # Forward file to DB channel with forwarding restricted
        forwarded = await message.forward(DB_CHANNEL, disable_notification=True)
        file_id = forwarded.id
        file_name = message.document.file_name if message.document else message.caption or "Unnamed"
        file_size = message.document.file_size if message.document else 0

        # Store metadata in MongoDB
        unique_link = await generate_unique_link(file_id)
        files_collection.insert_one({
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "user_id": user_id,
            "unique_id": unique_link.split("=")[-1],
            "created_at": datetime.utcnow()
        })

        # Add user to database if not exists
        if not users_collection.find_one({"user_id": user_id}):
            users_collection.insert_one({
                "user_id": user_id,
                "username": message.from_user.username,
                "joined_at": datetime.utcnow()
            })

        # Send shareable link to user
        reply = await message.reply_text(
            f"File stored successfully!\nShareable link: {unique_link}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Share", url=unique_link)
            ]]),
            disable_web_page_preview=True,
            disable_notification=True
        )
        await send_welcome_message(message)
        
        # Schedule deletion of messages
        asyncio.create_task(delete_messages_after_delay(client, message.chat.id, [message.id, reply.id]))

    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.reply_text("Flood wait triggered. Please try again later.", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error handling media: {e}")
        await message.reply_text("Error storing file. Please try again.", disable_web_page_preview=True)

# Main function to start the bot
async def main():
    await app.start()
    logger.info("Bot started successfully")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

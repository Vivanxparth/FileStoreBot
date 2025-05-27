import os, logging, asyncio, uuid
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
API_ID = os.getenv("API_ID", "16015294")  # Get from my.telegram.org
API_HASH = os.getenv("API_HASH", "e4fc842483c5de0f920ebba329c1a906")  # Get from my.telegram.org
BOT_TOKEN = os.getenv("BOT_TOKEN", "7421206619:AAF56TdflWvl-AAIMFw1AVxIvxiEioe6iqA")  # Get from @BotFather
DB_CHANNEL = int(os.getenv("DB_CHANNEL", "-1002649940692"))  # Private channel ID for storing files
UPDATES_CHANNEL = os.getenv("UPDATES_CHANNEL", "YoursUpdateHere")  # Public channel username for force sub
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7499642616").split()]  # List of admin user IDs
DATABASE_URL = os.getenv("DATABASE_URL", "mongodb+srv://karan69:karan69@cluster0.gfw7e.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")  # MongoDB URI
SLEEP_THRESHOLD = int(os.getenv("SLEEP_THRESHOLD", 60))  # Flood wait threshold
WORKERS = int(os.getenv("WORKERS", 8))  # Concurrent workers

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

# Helper functions
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
    """Send customizable welcome message."""
    welcome_text = (
        "Welcome to the File Store Bot! 📁\n"
        "Upload files to get shareable links.\n"
        "Use /help for more information."
    )
    await message.reply_text(welcome_text)

async def generate_unique_link(file_id, batch=False):
    """Generate a unique link for file or batch."""
    unique_id = str(uuid.uuid4())
    files_collection.insert_one({
        "unique_id": unique_id,
        "file_id": file_id,
        "batch": batch,
        "created_at": datetime.utcnow()
    })
    return f"https://t.me/{(await app.get_me()).username}?start={unique_id}"

async def is_authorized_user(user_id):
    """Check if user is authorized (admin or subscribed)."""
    if user_id in ADMIN_IDS:
        return True
    return await check_subscription(app, user_id)

# Command handlers
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    """Handle /start command."""
    user_id = message.from_user.id
    if not await is_authorized_user(user_id):
        if UPDATES_CHANNEL:
            await message.reply_text(
                f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
                ]])
            )
            return
    await send_welcome_message(message)
    
    # Check if start command includes a unique ID
    if len(message.command) > 1:
        unique_id = message.command[1]
        file_data = files_collection.find_one({"unique_id": unique_id})
        if file_data:
            try:
                if file_data["batch"]:
                    # Handle batch file sharing
                    batch_files = files_collection.find({"batch_id": file_data["unique_id"]})
                    for file in batch_files:
                        await client.forward_messages(
                            chat_id=message.chat.id,
                            from_chat_id=DB_CHANNEL,
                            message_ids=file["file_id"]
                        )
                else:
                    # Single file
                    await client.forward_messages(
                        chat_id=message.chat.id,
                        from_chat_id=DB_CHANNEL,
                        message_ids=file_data["file_id"]
                    )
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await client.forward_messages(
                    chat_id=message.chat.id,
                    from_chat_id=DB_CHANNEL,
                    message_ids=file_data["file_id"]
                )
            except Exception as e:
                logger.error(f"Error forwarding file: {e}")
                await message.reply_text("Error retrieving file. Please try again.")

@app.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    """Handle /help command."""
    help_text = (
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/batch - Generate a link for multiple files (select messages to forward)\n"
        "Admin commands:\n"
        "/broadcast - Broadcast a message to all users\n"
        "/stats - Show bot statistics\n"
        "Upload any file to store it and get a shareable link."
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    """Handle /batch command for multiple file links."""
    user_id = message.from_user.id
    if not await is_authorized_user(user_id):
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]])
        )
        return
    await message.reply_text("Please forward the files you want to include in the batch.")

@app.on_message(filters.command("broadcast") & filters.private & filters.user(ADMIN_IDS))
async def broadcast_command(client, message):
    """Handle /broadcast command for admins."""
    if not message.reply_to_message:
        await message.reply_text("Please reply to a message to broadcast.")
        return
    users = users_collection.find()
    success_count = 0
    for user in users:
        try:
            await message.reply_to_message.forward(user["user_id"])
            success_count += 1
            await asyncio.sleep(0.5)  # Avoid flood wait
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Error broadcasting to {user['user_id']}: {e}")
    await message.reply_text(f"Broadcast sent to {success_count} users.")

@app.on_message(filters.command("stats") & filters.private & filters.user(ADMIN_IDS))
async def stats_command(client, message):
    """Handle /stats command for admins."""
    user_count = users_collection.count_documents({})
    file_count = files_collection.count_documents({})
    await message.reply_text(f"Bot Stats:\nUsers: {user_count}\nFiles: {file_count}")

# File upload handler
@app.on_message(filters.media & filters.private)
async def handle_media(client, message):
    """Handle file uploads and store in DB channel."""
    user_id = message.from_user.id
    if not await is_authorized_user(user_id):
        await message.reply_text(
            f"Please subscribe to {UPDATES_CHANNEL} to use this bot.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Join Channel", url=f"https://t.me/{UPDATES_CHANNEL.lstrip('@')}")
            ]])
        )
        return

    try:
        # Forward file to DB channel
        forwarded = await message.forward(DB_CHANNEL)
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
        await message.reply_text(
            f"File stored successfully!\nShareable link: {unique_link}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Share", url=unique_link)
            ]])
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.reply_text("Flood wait triggered. Please try again later.")
    except Exception as e:
        logger.error(f"Error handling media: {e}")
        await message.reply_text("Error storing file. Please try again.")

# Main function to start the bot
async def main():
    await app.start()
    logger.info("Bot started successfully")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

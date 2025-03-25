from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from pymongo import MongoClient
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os

load_dotenv()
# MongoDB connection string
MONGO_URI = 'mongodb+srv://' + os.getenv('MONGO_USER') + ':'+ os.getenv('MONGO_PASSWORD') + '@' + os.getenv('MONGO_CLUSTER') + '/?retryWrites=true&w=majority&appName=Cluster0'

# Initialize MongoDB client
client = MongoClient(MONGO_URI)
db = client.telegram_bot  # Database name
addresses_collection = db.addresses  # Collection for Solana addresses
messages_collection = db.messages  # Collection for messages

# Dictionary to keep track of user states
user_states = {}

# Function to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_states[user_id] = 'awaiting_solana_address'
    await update.message.reply_text('Please send me your Solana address.')

# Function to handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    if user_states.get(user_id) == 'awaiting_solana_address':
        solana_address = update.message.text

        # Save the Solana address to the database
        addresses_collection.insert_one({'user_id': user_id, 'solana_address': solana_address})

        user_states[user_id] = 'awaiting_message_selection'
        await update.message.reply_text('Your Solana address has been registered. You can now use /messages to view your pending messages.')
    else:
        await display_selected_message(update, context)

# Function to display pending messages
async def display_pending_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    # Fetch pending messages from the database
    pending_messages = messages_collection.find({'user_id': user_id, 'read': False})

    if not pending_messages:
        await update.message.reply_text('You have no pending messages.')
        return

    message_list = []
    for i, msg in enumerate(pending_messages, start=1):
        message_list.append(f"{i}. {msg['project']} - {msg['title']}")

    message_text = "Pending Messages:\n" + "\n".join(message_list)
    message_text += "\n\nPlease type the number of the message you want to see."

    await update.message.reply_text(message_text)

# Function to display the selected message
async def display_selected_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    try:
        message_number = int(update.message.text)
        # Fetch pending messages from the database
        pending_messages = list(messages_collection.find({'user_id': user_id, 'read': False}))

        if 1 <= message_number <= len(pending_messages):
            selected_message = pending_messages[message_number - 1]
            message_text = f"Message from {selected_message['project']}:\n{selected_message['content']}"

            # Mark the message as read
            messages_collection.update_one({'_id': selected_message['_id']}, {'$set': {'read': True}})

            await update.message.reply_text(message_text)
        else:
            await update.message.reply_text('Invalid message number. Please try again.')
    except ValueError:
        await update.message.reply_text('Please enter a valid number.')

# Main function to set up the bot
def main() -> None:
    
    application = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("messages", display_pending_messages))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()
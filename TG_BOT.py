import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from telegram.error import TimedOut
from pymongo import MongoClient
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os
import random

load_dotenv()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection string
MONGO_URI = 'mongodb+srv://' + os.getenv('MONGO_USER') + ':'+ os.getenv('MONGO_PASSWORD') + '@' + os.getenv('MONGO_CLUSTER') + '/?retryWrites=true&w=majority&appName=Cluster0'

# Initialize MongoDB client
client = MongoClient(MONGO_URI)
db = client.telegram_bot  # Database name
addresses_collection = db.addresses  # Collection for Solana addresses
messages_collection = db.messages  # Collection for messages

# Dictionary to keep track of user states and attempts
user_states = {}
user_attempts = {}
user_questions = {}
current_question_index = {}
selected_message_id = {}

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
    elif user_states.get(user_id) == 'answering_questions':
        await handle_answer(update, context)
    elif user_states.get(user_id) == 'awaiting_message_selection':
        await display_selected_message(update, context)
    else:
        await update.message.reply_text('Invalid input. Please follow the instructions.')

# Function to display pending messages
async def display_pending_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    # Fetch pending messages from the database
    pending_messages = list(messages_collection.find({'user_id': user_id, 'read': False}))

    if not pending_messages:
        await update.message.reply_text('You have no pending messages.')
        return

    # Create inline keyboard with message buttons
    keyboard = []
    for msg in pending_messages:
        keyboard.append([InlineKeyboardButton(f"{msg['project']} - {msg['title']}", callback_data=f"msg_{msg['_id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a message to read:", reply_markup=reply_markup)

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

            # Store the selected message ID
            selected_message_id[user_id] = selected_message['_id']

            await update.message.reply_text(message_text)

            # Store questions
            user_questions[user_id] = selected_message.get('questions', [])
            user_attempts[user_id] = 0
            current_question_index[user_id] = 0
            user_states[user_id] = 'ready_to_ask_questions'
            await update.message.reply_text("Please answer the following questions to confirm you've read the message.")
            await ask_question(update, context)
        else:
            await update.message.reply_text('Invalid message number. Please try again.')
    except ValueError:
        await update.message.reply_text('Please enter a valid number.')
    except TimedOut:
        logger.error("Timed out while trying to send a message.")
        await update.message.reply_text('There was a network issue. Please try again later.')

# Function to ask a question
async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get user_id from either message or callback query
    if update.callback_query:
        user_id = update.callback_query.from_user.id
        message = update.callback_query.message
    else:
        user_id = update.message.from_user.id
        message = update.message

    question_index = current_question_index[user_id]

    if question_index < len(user_questions[user_id]):
        question_set = user_questions[user_id][question_index]
        # Create a list of all possible answers
        answers = [question_set[1], question_set[2], question_set[3]]
        # Shuffle the answers to randomize their order
        random.shuffle(answers)
        
        # Create inline keyboard with the answers
        keyboard = []
        for answer in answers:
            keyboard.append([InlineKeyboardButton(answer, callback_data=f"answer_{answer}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await message.edit_text(question_set[0], reply_markup=reply_markup)
        else:
            await message.reply_text(question_set[0], reply_markup=reply_markup)
        user_states[user_id] = 'answering_questions'
    else:
        if update.callback_query:
            await message.edit_text('You have answered all the questions. Thank you!')
        else:
            await message.reply_text('You have answered all the questions. Thank you!')
        # Mark the message as read after all questions are answered
        messages_collection.update_one({'_id': selected_message_id[user_id]}, {'$set': {'read': True}})
        user_states[user_id] = 'awaiting_message_selection'

# Function to handle button callbacks
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # Answer the callback query to remove loading state
    
    user_id = query.from_user.id
    selected_answer = query.data.replace("answer_", "")
    question_index = current_question_index[user_id]
    question_set = user_questions[user_id][question_index]

    if selected_answer == question_set[1]:  # Correct answer
        await query.message.edit_text("Correct! Moving to the next question...")
        user_attempts[user_id] = 0
        current_question_index[user_id] += 1
        await ask_question(update, context)
    else:
        user_attempts[user_id] += 1
        attempts_left = 3 - user_attempts[user_id]
        if attempts_left > 0:
            # Create a list of all possible answers
            answers = [question_set[1], question_set[2], question_set[3]]
            # Shuffle the answers to randomize their order
            random.shuffle(answers)
            
            # Create inline keyboard with the answers
            keyboard = []
            for answer in answers:
                keyboard.append([InlineKeyboardButton(answer, callback_data=f"answer_{answer}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                f"{question_set[0]}\n\nIncorrect. You have {attempts_left} attempts left. Please try again.",
                reply_markup=reply_markup
            )
        else:
            await query.message.edit_text("You have used all your attempts. Please read the message again.")
            user_states[user_id] = 'awaiting_message_selection'

# Function to handle message selection
async def handle_message_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # Answer the callback query to remove loading state
    
    user_id = query.from_user.id
    message_id = query.data.replace("msg_", "")
    
    # Fetch the selected message from the database
    # MongoDB ObjectId needs to be converted from string
    from bson.objectid import ObjectId
    selected_message = messages_collection.find_one({'_id': ObjectId(message_id)})
    
    if selected_message:
        message_text = f"Message from {selected_message['project']}:\n{selected_message['content']}"
        
        # Store the selected message ID
        selected_message_id[user_id] = selected_message['_id']

        await query.message.edit_text(message_text)

        # Store questions
        user_questions[user_id] = selected_message.get('questions', [])
        user_attempts[user_id] = 0
        current_question_index[user_id] = 0
        user_states[user_id] = 'ready_to_ask_questions'
        
        # Send instruction text first
        await query.message.reply_text("Please answer the following questions to confirm you've read the message.")
        
        # Then send the first question
        question_set = user_questions[user_id][0]
        answers = [question_set[1], question_set[2], question_set[3]]
        random.shuffle(answers)
        
        keyboard = []
        for answer in answers:
            keyboard.append([InlineKeyboardButton(answer, callback_data=f"answer_{answer}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(question_set[0], reply_markup=reply_markup)
        user_states[user_id] = 'answering_questions'
    else:
        await query.message.edit_text("Message not found. Please try again.")

# Main function to set up the bot
def main() -> None:
    application = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("messages", display_pending_messages))
    application.add_handler(CallbackQueryHandler(handle_message_selection, pattern="^msg_"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^answer_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()
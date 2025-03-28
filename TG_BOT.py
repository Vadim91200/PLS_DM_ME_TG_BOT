import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from telegram.error import TimedOut
from pymongo import MongoClient
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os
import random
import asyncio
from datetime import datetime
from bson.objectid import ObjectId

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

# Dictionary to keep track of user states and data
user_states = {}
user_questions = {}
current_question_index = {}
selected_message_id = {}
correct_answers = {}

# Function to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.message.from_user.id

        # Create verification URL with React app using ngrok URL
        verification_url = f"https://8310-89-30-29-68.ngrok-free.app/?userId={user_id}"
        
        # Create inline keyboard with verification button
        keyboard = [[InlineKeyboardButton("Connect Wallet & Verify", url=verification_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        user_states[user_id] = 'awaiting_message_selection'
        
        await update.message.reply_text(
            'Welcome! Please click the button below to connect your wallet and verify your address:',
            reply_markup=reply_markup
        )
                
    except Exception as e:
        logger.error(f"Error in start function: {str(e)}")
        await update.message.reply_text(
            "Sorry, there was an error. Please try again in a few moments."
        )

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
        # Format the button text to include reward
        button_text = f"{msg['project']} - {msg['title']} | {msg['reward']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"msg_{msg['_id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a message to read:", reply_markup=reply_markup)

# Function to handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.message.from_user.id

        if user_states.get(user_id) == 'answering_questions':
            await check_answer(update, context)
        elif user_states.get(user_id) == 'awaiting_message_selection':
            await display_selected_message(update, context)
        else:
            # If no valid state, show the verification button again
            verification_url = f"https://8310-89-30-29-68.ngrok-free.app/?userId={user_id}"
            keyboard = [[InlineKeyboardButton("Connect Wallet & Verify", url=verification_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                'Please click the button below to connect your wallet and verify your address:',
                reply_markup=reply_markup
            )
                    
    except Exception as e:
        logger.error(f"Error in handle_message function: {str(e)}")
        await update.message.reply_text(
            "Sorry, there was an error. Please try again in a few moments."
        )

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

            # Store questions and initialize correct answers counter
            user_questions[user_id] = selected_message.get('questions', [])
            current_question_index[user_id] = 0
            correct_answers[user_id] = 0
            user_states[user_id] = 'ready_to_ask_questions'
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
        
        # Create message text with instruction and question
        message_text = (
            "Please answer the following questions about the message.\n\n"
            f"Question {question_index + 1} of {len(user_questions[user_id])}:\n\n"
            f"{question_set[0]}"
        )
        
        if update.callback_query:
            await message.edit_text(message_text, reply_markup=reply_markup)
        else:
            await message.reply_text(message_text, reply_markup=reply_markup)
        user_states[user_id] = 'answering_questions'
    else:
        # Save the number of correct answers to the database
        messages_collection.update_one(
            {'_id': selected_message_id[user_id]},
            {
                '$set': {
                    'read': True,
                    'correct_answers': correct_answers[user_id],
                    'total_questions': len(user_questions[user_id]),
                    'completed_at': datetime.utcnow()
                }
            }
        )
        
        # Display completion message without score
        completion_message = "Thank you for completing all the questions!"
        
        if update.callback_query:
            await message.edit_text(completion_message)
        else:
            await message.reply_text(completion_message)
        user_states[user_id] = 'awaiting_message_selection'

# Function to handle button callbacks
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # Answer the callback query to remove loading state
    
    user_id = query.from_user.id
    selected_answer = query.data.replace("answer_", "")
    question_index = current_question_index[user_id]
    question_set = user_questions[user_id][question_index]

    # Silently track correct answers without showing feedback
    if selected_answer == question_set[1]:
        correct_answers[user_id] += 1
    
    # Move to next question immediately
    current_question_index[user_id] += 1
    await ask_question(update, context)

# Function to handle message selection
async def handle_message_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = query.from_user.id
        message_id = query.data.replace("msg_", "")
        
        # Fetch the selected message
        selected_message = messages_collection.find_one({'_id': ObjectId(message_id)})
        if selected_message:
            message_text = f"Message from {selected_message['project']}:\n{selected_message['content']}"
            
            # Store the selected message ID
            selected_message_id[user_id] = selected_message['_id']
            
            # Show the message content first
            await query.message.edit_text(message_text)
            
            # Store questions and initialize correct answers counter
            user_questions[user_id] = selected_message.get('questions', [])
            current_question_index[user_id] = 0
            correct_answers[user_id] = 0
            user_states[user_id] = 'ready_to_ask_questions'
            
            # Send a separate message for questions after showing the content
            waiting_message = await query.message.reply_text("Please read the message above carefully. The questions will start in 5 seconds...")
            await asyncio.sleep(5)  # Give user 5 seconds to read
            await waiting_message.delete()  # Delete the waiting message
            await ask_question(update, context)
        else:
            await query.message.edit_text("Sorry, this message is no longer available.")
            
    except Exception as e:
        logger.error(f"Error in handle_message_selection: {str(e)}")
        await query.message.edit_text("Sorry, there was an error processing your selection.")

def main() -> None:
    # Create the Application and pass it your bot's token
    application = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("messages", display_pending_messages))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_message_selection, pattern="^msg_"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^answer_"))

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
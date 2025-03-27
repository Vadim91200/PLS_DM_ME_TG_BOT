from flask import Flask, render_template, request, jsonify, send_from_directory
from pymongo import MongoClient
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os
import base64
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from solders.pubkey import Pubkey
from base58 import b58decode
import requests
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__, static_folder='solana-verification/build/static', static_url_path='/static')

# MongoDB connection string
MONGO_URI = 'mongodb+srv://' + os.getenv('MONGO_USER') + ':'+ os.getenv('MONGO_PASSWORD') + '@' + os.getenv('MONGO_CLUSTER') + '/?retryWrites=true&w=majority&appName=Cluster0'

# Initialize MongoDB client
client = MongoClient(MONGO_URI)
db = client.telegram_bot  # Database name
addresses_collection = db.addresses  # Collection for Solana addresses
messages_collection = db.messages  # Collection for messages

# Telegram bot token - use the same token as in TG_BOT.py
TELEGRAM_BOT_TOKEN = os.getenv('BOT_TOKEN')  # Changed from TELEGRAM_BOT_TOKEN to BOT_TOKEN

# API URL for the React app
API_URL = 'https://05d4-89-30-29-68.ngrok-free.app'

def send_telegram_message(chat_id, message):
    try:
        if not TELEGRAM_BOT_TOKEN:
            logger.error("Telegram bot token is not set!")
            return None

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        logger.info(f"Sending Telegram message to chat_id {chat_id}")
        response = requests.post(url, json=data)
        response.raise_for_status()  # Raise an exception for bad status codes
        logger.info("Telegram message sent successfully")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response text: {e.response.text}")
        return None

@app.route('/')
def serve():
    return send_from_directory('solana-verification/build', 'index.html')

@app.route('/<path:path>')
def static_file(path):
    return send_from_directory('solana-verification/build', path)

@app.route('/api/verify', methods=['POST'])
def verify_signature():
    try:
        data = request.get_json()
        logger.info(f"Received verification request: {data}")
        
        # Validate required fields
        if not all(key in data for key in ['user_id', 'message', 'signature', 'publicKey']):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        # Convert base58 public key to bytes
        try:
            public_key_bytes = b58decode(data['publicKey'])
            # Create a Pubkey object directly from bytes
            public_key = Pubkey(public_key_bytes)
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Invalid public key format: {str(e)}'
            }), 400

        # Decode base64 signature
        try:
            signature_bytes = base64.b64decode(data['signature'])
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Invalid signature format: {str(e)}'
            }), 400

        # Verify the signature
        try:
            message_bytes = data['message'].encode('utf-8')
            verify_key = VerifyKey(bytes(public_key))
            verify_key.verify(message_bytes, signature_bytes)
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Signature verification failed: {str(e)}'
            }), 400

        # Update the database and save the verified address
        try:
            addresses_collection.update_one(
                {'user_id': data['user_id']},
                {
                    '$set': {
                        'verified': True,
                        'solana_address': data['publicKey'],
                        'verification_date': datetime.utcnow()
                    }
                },
                upsert=True
            )
            logger.info(f"Database updated for user {data['user_id']}")

            # Send Telegram notification
            success_message = (
                f"✅ <b>Address Verified Successfully!</b>\n\n"
                f"Your Solana address has been verified and saved:\n"
                f"<code>{data['publicKey']}</code>\n\n"
                f"You can now use the bot's features."
            )
            telegram_response = send_telegram_message(data['user_id'], success_message)
            
            if not telegram_response:
                logger.error(f"Failed to send Telegram message to user {data['user_id']}")
                # Continue with success response even if Telegram message fails
                # The user can still see the success in the web interface

        except Exception as e:
            logger.error(f"Database update error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to update database'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Signature verified successfully'
        })

    except Exception as e:
        logger.error(f"Verification error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=True) 
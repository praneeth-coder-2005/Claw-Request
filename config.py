TELEGRAM_BOT_TOKEN = "7929866615:AAGv3uzJjchHhc1ws2KoGwXHyySpegHCH-4"  # Replace with your bot token
MONGODB_URI = "mongodb+srv://claw-earning:5213680099@cluster0.je3b1k7.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"  # Replace with your MongoDB URI
ADMIN_USER_IDS = [1894915577]  # Replace with Telegram User IDs that are admins
# Replace with the actual name of your database.
MONGODB_DATABASE_NAME = "Claw_Files" # Add this in the config.py or environment variables

client = pymongo.MongoClient(config.MONGODB_URI)
db = client[MONGODB_DATABASE_NAME] # Use this for database selection
import telebot
from telebot import types
import pymongo
import datetime
import logging
import config  # Import credentials from config.py

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MongoDB Setup ---
client = pymongo.MongoClient(config.MONGODB_URI)
db = client[config.MONGODB_DATABASE_NAME]  # Changed to use db name directly

# --- Utility Functions ---
def is_admin(user_id):
    return user_id in config.ADMIN_USER_IDS

# --- Database Functions ---
def get_requests():
    return db.requests.find().sort("request_timestamp", pymongo.DESCENDING)

def get_request(user_id, movie_title):
    return db.requests.find_one({"telegram_user_id": user_id, "movie_title": movie_title})

def create_request(user_id, movie_title, timestamp):
    return db.requests.insert_one({
        "telegram_user_id": user_id,
        "movie_title": movie_title,
        "request_timestamp": timestamp,
        "status": "pending",
        "link": None
    })

def update_request_link(movie_title, link):
    return db.requests.update_one({"movie_title": movie_title}, {"$set": {"link": link, "status": "completed"}})

def filter_requests(filter):
    return db.requests.find(filter).sort("request_timestamp", pymongo.DESCENDING)


# --- Telebot Setup ---
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

# --- Command Handlers ---
@bot.message_handler(commands=['start', 'help'])
def help_handler(message):
    help_text = """
    Available commands:

    /request <movie_title> - Request a movie to be added.
    /status <movie_title> - Check the status of a requested movie.
    /help - Show available commands.
    """
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['request'])
def request_handler(message):
    user_id = message.from_user.id
    try:
        movie_title = " ".join(message.text.split()[1:])
    except:
      bot.reply_to(message,"Please provide a movie title")
      return

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Confirm Request", callback_data=f'confirm_request_{movie_title}'))
    bot.reply_to(message,f"Request '{movie_title}'. Are you sure?", reply_markup=keyboard)


@bot.message_handler(commands=['status'])
def status_handler(message):
    user_id = message.from_user.id
    try:
      movie_title = " ".join(message.text.split()[1:])
    except:
      bot.reply_to(message,"Please provide a movie title")
      return

    request_data = get_request(user_id, movie_title)

    if not request_data:
        bot.reply_to(message, f"We couldn't find a request for '{movie_title}' under your account.")
    elif request_data.get("status") == "pending":
        bot.reply_to(message, f"Your request for '{movie_title}' is still pending.")
    else:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("View Link", url=request_data.get("link")))
        bot.reply_to(message, f"Great news! '{movie_title}' is available here: {request_data.get('link')}", reply_markup=keyboard)


@bot.message_handler(commands=['admin'])
def admin_handler(message):
  user_id = message.from_user.id
  if not is_admin(user_id):
      bot.reply_to(message, "Unauthorized access")
      return

  keyboard = types.InlineKeyboardMarkup()
  keyboard.add(types.InlineKeyboardButton("List Pending Requests", callback_data="list_pending"))
  keyboard.add(types.InlineKeyboardButton("Filter Requests", callback_data="filter_requests"))
  bot.reply_to(message, "Admin Menu", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
  data = call.data

  if data == "list_pending":
      requests = get_requests()
      if not requests:
         bot.answer_callback_query(call.id, text="No pending requests")
      else:
          for req in requests:
              keyboard = types.InlineKeyboardMarkup()
              keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
              bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",
                                   chat_id=call.message.chat.id,
                                   message_id=call.message.message_id,
                                   reply_markup=keyboard)
      bot.answer_callback_query(call.id)
  elif data.startswith("mark_complete"):
    movie_title = data.split("_")[2]
    bot.send_message(chat_id=call.message.chat.id, text=f"Provide the link for {movie_title}", reply_to_message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, lambda message: handle_link(message, movie_title))

  elif data.startswith("filter_requests"):
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Movie Title", callback_data="filter_title"))
        keyboard.add(types.InlineKeyboardButton("User ID", callback_data="filter_id"))
        keyboard.add(types.InlineKeyboardButton("Pending", callback_data="filter_pending"))
        keyboard.add(types.InlineKeyboardButton("Completed", callback_data="filter_completed"))
        bot.edit_message_text(text=f"Filter Option",
                             chat_id=call.message.chat.id,
                             message_id=call.message.message_id,
                            reply_markup=keyboard)
        bot.answer_callback_query(call.id)

  elif data.startswith("filter_title"):
    bot.send_message(chat_id=call.message.chat.id, text="Please provide a movie title to search for.", reply_to_message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, lambda message: handle_filter(message, "title"))
    bot.answer_callback_query(call.id)

  elif data.startswith("filter_id"):
      bot.send_message(chat_id=call.message.chat.id, text="Please provide a User ID to search for.", reply_to_message_id=call.message.message_id)
      bot.register_next_step_handler(call.message, lambda message: handle_filter(message, "id"))
      bot.answer_callback_query(call.id)

  elif data.startswith("filter_pending"):
      reqs = filter_requests({"status":"pending"})
      if not reqs:
        bot.answer_callback_query(call.id, text="No pending requests")
      else:
        for req in reqs:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
            bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",
                                   chat_id=call.message.chat.id,
                                   message_id=call.message.message_id,
                                   reply_markup=keyboard)
      bot.answer_callback_query(call.id)
  elif data.startswith("filter_completed"):
    reqs = filter_requests({"status":"completed"})
    if not reqs:
        bot.answer_callback_query(call.id, text="No completed requests")
    else:
        for req in reqs:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
            bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",
                                   chat_id=call.message.chat.id,
                                   message_id=call.message.message_id,
                                   reply_markup=keyboard)
    bot.answer_callback_query(call.id)

  elif data.startswith("confirm_request"):
    movie_title = data.split("_")[2]
    user_id = call.from_user.id
    now = datetime.datetime.now()
    create_request(user_id, movie_title, now)
    bot.edit_message_text(f"Got it! We've added '{movie_title}' to the request list.",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


def handle_link(message, movie_title):
    update_request_link(movie_title, message.text)
    bot.reply_to(message, f"Link added for '{movie_title}'.")

def handle_filter(message, filter_type):
      if filter_type == "title":
          filter = {"movie_title": message.text}
      elif filter_type == "id":
          filter = {"telegram_user_id": message.text}
      reqs = filter_requests(filter)
      if not reqs:
        bot.reply_to(message,f"No requests found")
      else:
         for req in reqs:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
            bot.send_message(chat_id=message.chat.id, text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",reply_markup=keyboard)


# --- Main ---
if __name__ == '__main__':
    bot.polling(non_stop=True)

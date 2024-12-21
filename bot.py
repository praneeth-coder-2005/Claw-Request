from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
import pymongo
import datetime
import logging
import config  # Import credentials from config.py

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MongoDB Setup ---
client = pymongo.MongoClient(config.MONGODB_URI)
db = client[config.MONGODB_DATABASE_NAME] # Changed to use db name directly

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


# --- Command Handlers ---
def request_handler(update, context: CallbackContext):
    user_id = update.message.from_user.id
    movie_title = " ".join(context.args)
    if not movie_title:
      update.message.reply_text("Please provide a movie title.")
      return

    keyboard = [[InlineKeyboardButton("Confirm Request", callback_data=f'confirm_request_{movie_title}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text(f"Request '{movie_title}'. Are you sure?", reply_markup=reply_markup)


def status_handler(update, context: CallbackContext):
    user_id = update.message.from_user.id
    movie_title = " ".join(context.args)
    if not movie_title:
      update.message.reply_text("Please provide a movie title.")
      return

    request_data = get_request(user_id, movie_title)

    if not request_data:
        update.message.reply_text(f"We couldn't find a request for '{movie_title}' under your account.")
    elif request_data.get("status") == "pending":
        update.message.reply_text(f"Your request for '{movie_title}' is still pending.")
    else:
      keyboard = [[InlineKeyboardButton("View Link", url=request_data.get("link"))]]
      reply_markup = InlineKeyboardMarkup(keyboard)

      update.message.reply_text(f"Great news! '{movie_title}' is available here: {request_data.get('link')}", reply_markup=reply_markup)


def admin_handler(update, context: CallbackContext):
  user_id = update.message.from_user.id
  if not is_admin(user_id):
      update.message.reply_text("Unauthorized access")
      return

  keyboard = [
      [InlineKeyboardButton("List Pending Requests", callback_data="list_pending")],
      [InlineKeyboardButton("Filter Requests", callback_data="filter_requests")]
      ]
  reply_markup = InlineKeyboardMarkup(keyboard)
  update.message.reply_text("Admin Menu", reply_markup=reply_markup)


def admin_button_handler(update, context: CallbackContext):
   query = update.callback_query
   query.answer()
   data = query.data

   if data == "list_pending":
      # Get Data from DB
      requests = get_requests()
      if not requests:
        query.edit_message_text(text="No pending request")
      else:
        for req in requests:
            keyboard = [[InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",reply_markup=reply_markup)

   elif data.startswith("mark_complete"):
    movie_title = data.split("_")[2]
    context.user_data["mark_complete"] = movie_title
    query.edit_message_text(text=f"Provide the link for {movie_title}")
    return
   elif data.startswith("filter_requests"):
     keyboard = [
         [InlineKeyboardButton("Movie Title", callback_data="filter_title")],
         [InlineKeyboardButton("User ID", callback_data="filter_id")],
         [InlineKeyboardButton("Pending", callback_data="filter_pending")],
         [InlineKeyboardButton("Completed", callback_data="filter_completed")]
         ]
     reply_markup = InlineKeyboardMarkup(keyboard)
     query.edit_message_text(text=f"Filter Option", reply_markup=reply_markup)
     return
   elif data.startswith("filter_title"):
    query.edit_message_text(text=f"Please provide a movie title to search for.")
    context.user_data["filter_type"] = "title"
    return
   elif data.startswith("filter_id"):
    query.edit_message_text(text=f"Please provide a User ID to search for.")
    context.user_data["filter_type"] = "id"
    return
   elif data.startswith("filter_pending"):
      reqs = filter_requests({"status":"pending"})
      if not reqs:
          query.edit_message_text(text="No pending requests")
      else:
          for req in reqs:
              keyboard = [[InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}')]]
              reply_markup = InlineKeyboardMarkup(keyboard)
              query.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",reply_markup=reply_markup)
      return
   elif data.startswith("filter_completed"):
    reqs = filter_requests({"status":"completed"})
    if not reqs:
        query.edit_message_text(text="No completed requests")
    else:
        for req in reqs:
              keyboard = [[InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}')]]
              reply_markup = InlineKeyboardMarkup(keyboard)
              query.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",reply_markup=reply_markup)
    return


def help_handler(update, context: CallbackContext):
    help_text = """
    Available commands:

    /request <movie_title> - Request a movie to be added.
    /status <movie_title> - Check the status of a requested movie.
    /help - Show available commands.
    """

    update.message.reply_text(help_text)


def handle_text(update, context: CallbackContext):
    message = update.message.text
    query = update.callback_query

    if context.user_data.get("mark_complete"):
        movie_title = context.user_data["mark_complete"]
        update_request_link(movie_title, message)
        update.message.reply_text(f"Link added for '{movie_title}'.")
        context.user_data.pop("mark_complete")
        return
    if context.user_data.get("filter_type"):
      filter_type = context.user_data["filter_type"]
      if filter_type == "title":
          filter = {"movie_title": message}
      elif filter_type == "id":
          filter = {"telegram_user_id": message}
      context.user_data.pop("filter_type")
      reqs = filter_requests(filter)
      if not reqs:
        update.message.reply_text(f"No requests found")
      else:
         for req in reqs:
            keyboard = [[InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}",reply_markup=reply_markup)
      return

def confirm_request_handler(update, context: CallbackContext):
   query = update.callback_query
   query.answer()
   movie_title = query.data.split("_")[2]
   user_id = query.from_user.id
   now = datetime.datetime.now()
   create_request(user_id, movie_title, now)
   query.edit_message_text(f"Got it! We've added '{movie_title}' to the request list.")
   return

# --- Main ---
def main():
    updater = Updater(config.TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("request", request_handler))
    dp.add_handler(CommandHandler("status", status_handler))
    dp.add_handler(CommandHandler("admin", admin_handler))
    dp.add_handler(CallbackQueryHandler(admin_button_handler))
    dp.add_handler(CommandHandler("help", help_handler))
    dp.add_handler(CallbackQueryHandler(confirm_request_handler, pattern="^confirm_request_"))
    dp.add_handler(MessageHandler(filters=Filters.text, callback=handle_text))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

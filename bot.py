import telebot
from telebot import types
import pymongo
import datetime
import logging
import config
from flask import Flask, Response, request
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MongoDB Setup ---
client = pymongo.MongoClient(config.MONGODB_URI)
db = client[config.MONGODB_DATABASE_NAME]

# --- Utility Functions ---
def is_admin(user_id):
 return user_id in config.ADMIN_USER_IDS

# --- Database Functions ---
def get_requests(user_id = None):
 query = {} if user_id is None else {"telegram_user_id": user_id}
 return db.requests.find(query).sort("request_timestamp", pymongo.DESCENDING)

def get_request(user_id, movie_title):
 return db.requests.find_one({"telegram_user_id": user_id, "movie_title": movie_title})

def create_request(user_id, movie_title, timestamp, tmdb_id):
 return db.requests.insert_one({
     "telegram_user_id": user_id,
     "movie_title": movie_title,
     "request_timestamp": timestamp,
     "status": "pending",
     "tmdb_id": tmdb_id,
     "link": None,
     "available": False,
 })

def update_request_link(movie_title, link):
 return db.requests.update_one({"movie_title": movie_title}, {"$set": {"link": link, "status": "completed", "available": True}})

def reject_request(movie_title):
 return db.requests.update_one({"movie_title": movie_title}, {"$set": {"status": "rejected", "available": False}})


def filter_requests(filter):
 return db.requests.find(filter).sort("request_timestamp", pymongo.DESCENDING)

# --- Telebot Setup ---
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
bot.remove_webhook()
# --- Flask Setup ---
app = Flask(__name__)

@app.route('/health')
def health_check():
 return Response(status=200)
@app.route(f"/{config.TELEGRAM_BOT_TOKEN}",methods=["POST"])
def webhook():
 json_str = request.get_data().decode("utf-8")
 update = telebot.types.Update.de_json(json_str)
 bot.process_new_updates([update])
 return "",200

# --- TMDB API ---
def create_retry_session():
 retry_strategy = Retry(
         total=3, # Number of retries
         status_forcelist=[429, 500, 502, 503, 504], # Response statuses for which a retry should occur
         allowed_methods=["GET"], # Method for which retry should occur
         backoff_factor = 1 # Factor to determine wait time
 )
 adapter = HTTPAdapter(max_retries=retry_strategy)
 session = requests.Session()
 session.mount("https://", adapter)
 return session

session = create_retry_session()

def fetch_tmdb_data(movie_title):
 """Fetches movie data from TMDB by title."""
 base_url = "https://api.themoviedb.org/3/search/movie"
 params = {
     "api_key": config.TMDB_API_KEY,
     "query": movie_title,
     "language": "en-US",
 }
 try:
     response = session.get(base_url, params=params)
     response.raise_for_status()
     data = response.json()
     if data.get("results"):
         return data["results"]
     else:
         return None
 except requests.exceptions.RequestException as e:
     logging.error(f"Error fetching from TMDB: {e}")
     return None

def fetch_tmdb_data_by_id(movie_id):
     """Fetches movie data from TMDB by id"""
     base_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
     params = {
         "api_key": config.TMDB_API_KEY,
         "language": "en-US",
     }
     try:
         response = session.get(base_url, params=params)
         response.raise_for_status()
         return response.json()
     except requests.exceptions.RequestException as e:
       logging.error(f"Error fetching from TMDB: {e}")
       return None


# --- Command Handlers ---
@bot.message_handler(commands=['start', 'help'])
def help_handler(message):
 help_text = """
 Available commands:

 /request <movie_title> - Request a movie to be added.
 /mylist - View your movie request list with status.
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

 existing_request = get_request(user_id, movie_title)
 if existing_request:
   if existing_request.get("available"):
     bot.reply_to(message, f"You have already requested this movie, you can view it here: {existing_request.get('link')}")
   elif existing_request.get("status") == "pending":
      bot.reply_to(message, "You have already requested this movie, it is currently pending.")
   elif existing_request.get("status") == "rejected":
       bot.reply_to(message, "You have already requested this movie, but it was rejected.")
   return

 tmdb_results = fetch_tmdb_data(movie_title)
 if tmdb_results:
   keyboard = types.InlineKeyboardMarkup()
   for movie in tmdb_results:
     keyboard.add(types.InlineKeyboardButton(f"{movie['title']} ({movie['release_date'][:4]})", callback_data=f"select_movie_{movie['id']}_{movie_title}"))
   bot.reply_to(message, f"Multiple movies found for '{movie_title}'. Please select one:", reply_markup=keyboard)
 else:
   keyboard = types.InlineKeyboardMarkup()
   keyboard.add(types.InlineKeyboardButton("Confirm Request", callback_data=f'confirm_request_{movie_title}_None'))
   bot.reply_to(message,f"No movies found with name '{movie_title}'\nRequest '{movie_title}'. Are you sure? If you provide wrong spelling I can't search", reply_markup=keyboard)
 for admin_id in config.ADMIN_USER_IDS:
     bot.send_message(chat_id=admin_id, text=f"New movie request '{movie_title}' by user {message.from_user.first_name} with ID: {user_id}")

@bot.message_handler(commands=['mylist'])
def mylist_handler(message):
 user_id = message.from_user.id
 requests = get_requests(user_id)
 if not requests:
   bot.reply_to(message, "You haven't requested any movies yet.")
   return

 for req in requests:
   status_text = "Pending" if req.get("status") == "pending" else ("Available: " + req.get("link") if req.get("status") == "completed" else "Rejected")
   bot.send_message(chat_id=message.chat.id, text=f"Movie: {req.get('movie_title')}\nStatus: {status_text}")

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
 elif request_data.get("status") == "rejected":
     bot.reply_to(message, f"Your request for '{movie_title}' was rejected.")
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
keyboard.add(types.InlineKeyboardButton("List  Requests", callback_data="list_pending"))
keyboard.add(types.InlineKeyboardButton("Filter Requests", callback_data="filter_requests"))
bot.reply_to(message, "Admin Menu", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
data = call.data

if data == "list_pending":
 show_pending_list(call)
elif data.startswith("mark_complete"):
   movie_title = data.split("_")[2]
   bot.send_message(chat_id=call.message.chat.id, text=f"Provide the link for {movie_title}", reply_to_message_id=call.message.message_id)
   bot.register_next_step_handler(call.message, lambda message: handle_link(message, movie_title,call.message.chat.id))
elif data.startswith("mark_reject"):
   movie_title = data.split("_")[2]
   reject_request(movie_title)
   bot.answer_callback_query(call.id, text=f"Request for '{movie_title}' rejected")
   show_pending_list(call)
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
 bot.register_next_step_handler(call.message, lambda message: handle_filter(message, "title",call))
 bot.answer_callback_query(call.id)

elif data.startswith("filter_id"):
   bot.send_message(chat_id=call.message.chat.id, text="Please provide a User ID to search for.", reply_to_message_id=call.message.message_id)
   bot.register_next_step_handler(call.message, lambda message: handle_filter(message, "id",call))
   bot.answer_callback_query(call.id)

elif data.startswith("filter_pending"):
   reqs = filter_requests({"status":"pending"})
   if not reqs:
     bot.answer_callback_query(call.id, text="No pending requests")
   else:
       show_filtered_list(call,reqs)

elif data.startswith("filter_completed"):
 reqs = filter_requests({"status":"completed"})
 if not reqs:
     bot.answer_callback_query(call.id, text="No completed requests")
 else:
   show_filtered_list(call,reqs)
elif data.startswith("select_movie"):
 movie_id = data.split("_")[2]
 movie_title = data.split("_")[3]
 user_id = call.from_user.id
 now = datetime.datetime.now()
 create_request(user_id, movie_title, now, movie_id)
 bot.edit_message_text(f"Got it! We've added '{movie_title}' to the request list.",
                         chat_id=call.message.chat.id,
                         message_id=call.message.message_id)
 bot.answer_callback_query(call.id)
elif data.startswith("confirm_request"):
 movie_title = data.split("_")[2]
 tmdb_id = data.split("_")[3]
 user_id = call.from_user.id
 now = datetime.datetime.now()
 create_request(user_id, movie_title, now, tmdb_id)
 bot.edit_message_text(f"Got it! We've added '{movie_title}' to the request list.",
                         chat_id=call.message.chat.id,
                         message_id=call.message.message_id)
 bot.answer_callback_query(call.id)
elif data.startswith("view_details"):
 movie_title = data.split("_")[2]
 show_request_details(call, movie_title)
elif data.startswith("back_to_pending"):
 show_pending_list(call)


def handle_link(message, movie_title,chat_id):
 update_request_link(movie_title, message.text)
 bot.reply_to(message, f"Link added for '{movie_title}'.")
 request = get_request(user_id=None,movie_title=movie_title)
 if request:
     bot.send_message(chat_id = request.get("telegram_user_id"), text = f"Your movie request for '{movie_title}' has been completed view here {request.get('link')}")
 show_pending_list(message)

def handle_filter(message, filter_type,call):
   if filter_type == "title":
       filter = {"movie_title": message.text}
   elif filter_type == "id":
       filter = {"telegram_user_id": message.text}
   reqs = filter_requests(filter)
   if not reqs:
     bot.reply_to(message,f"No requests found")
   else:
       show_filtered_list(call,reqs)

def show_filtered_list(call,reqs):
 for req in reqs:
     keyboard = types.InlineKeyboardMarkup()
     keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
     keyboard.add(types.InlineKeyboardButton("Mark Reject", callback_data=f'mark_reject_{req["movie_title"]}'))
     bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}\nStatus:{req.get('status')}",
                                 chat_id=call.message.chat.id,
                                 message_id=call.message.message_id,
                                 reply_markup=keyboard)
 bot.answer_callback_query(call.id)

def show_pending_list(call):
 requests = get_requests()
 if not requests:
     bot.answer_callback_query(call.id, text="No requests yet")
 else:
     for req in requests:
         keyboard = types.InlineKeyboardMarkup()
         keyboard.add(types.InlineKeyboardButton("View Details", callback_data=f'view_details_{req["movie_title"]}'))
         bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}\nStatus: {'Available' if req.get('available') else 'Pending' if req.get('status') == 'pending' else 'Rejected'}",
                             chat_id=call.message.chat.id,
                             message_id=call.message.message_id,
                             reply_markup=keyboard)
 bot.answer_callback_query(call.id)


def show_request_details(call, movie_title):
 req = db.requests.find_one({"movie_title": movie_title})
 if req:
     keyboard = types.InlineKeyboardMarkup()
     keyboard.add(types.InlineKeyboardButton("Mark Complete", callback_data=f'mark_complete_{req["movie_title"]}'))
     keyboard.add(types.InlineKeyboardButton("Mark Reject", callback_data=f'mark_reject_{req["movie_title"]}'))
     keyboard.add(types.InlineKeyboardButton("Back to  List", callback_data="back_to_pending"))
     tmdb_details_text = ""
     if req.get("tmdb_id") != "None" and req.get("tmdb_id") != None:
         tmdb_details = fetch_tmdb_data_by_id(req.get("tmdb_id"))
         if tmdb_details:
              poster_url = f'https://image.tmdb.org/t/p/w500{tmdb_details["poster_path"]}' if tmdb_details.get("poster_path") else 'No Poster'
              tmdb_details_text = f"\n\nTitle: {tmdb_details['title']}\nRelease Date:{tmdb_details['release_date']}\nPoster: {poster_url}"

     bot.edit_message_text(text=f"Movie:{req['movie_title']}\nUser: {req['telegram_user_id']}\nDate: {req['request_timestamp']}\nStatus: {'Available' if req.get('available') else 'Pending' if req.get('status') == 'pending' else 'Rejected'}{tmdb_details_text}",
                                 chat_id=call.message.chat.id,
                                 message_id=call.message.message_id,
                                 reply_markup=keyboard)
 bot.answer_callback_query(call.id)

# --- Main ---
if __name__ == '__main__':
 def start_flask_app():
     bot.set_webhook(f"https://{config.KOYEB_APP_URL}/{config.TELEGRAM_BOT_TOKEN}")
     app.run(host='0.0.0.0', port=8080)

 flask_thread = threading.Thread(target=start_flask_app)
 flask_thread.start()

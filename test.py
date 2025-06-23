# video_tool.py

import os
import requests
import ffmpeg
from tqdm import tqdm
from pyrogram import Client
import asyncio
from urllib.parse import urlparse, unquote

# --------------------------- SETTINGS ---------------------------
API_ID = 22250562
API_HASH = "07754d3bdc27193318ae5f6e6c8016af"
BOT_TOKEN = "7728162826:AAFdjHDjmFl47Oa9ViURU2atR4-jsyXhsXc"
CHANNEL_USERNAME = "@dumprjddisb"
# ----------------------------------------------------------------

os.makedirs("downloads", exist_ok=True)
os.makedirs("screenshots", exist_ok=True)

def download_file(url, path):
    response = requests.get(url, stream=True)
    total = int(response.headers.get("content-length", 0))
    with open(path, "wb") as f, tqdm(
        desc="📥 Downloading",
        total=total,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for chunk in response.iter_content(1024 * 1024):
            f.write(chunk)
            bar.update(len(chunk))

def extract_filename(url):
    path = urlparse(unquote(url)).path
    filename = os.path.basename(path)
    if not any(filename.endswith(ext) for ext in ['.mp4', '.mkv']):
        filename += ".mp4"
    return filename

def generate_screenshots(input_path):
    probe = ffmpeg.probe(input_path)
    duration = float(probe["format"]["duration"])
    interval = duration / 6
    output_files = []
    for i in range(1, 6):
        timestamp = int(i * interval)
        out_path = f"screenshots/ss_{i}.jpg"
        ffmpeg.input(input_path, ss=timestamp).output(out_path, vframes=1).run(overwrite_output=True, quiet=True)
        output_files.append(out_path)
    return output_files

def generate_sample(input_path, output_path="sample.mp4"):
    ffmpeg.input(input_path, ss=10, t=30).output(output_path).run(overwrite_output=True, quiet=True)
    return output_path

def trim_video(input_path, start, end, output_path="trimmed.mp4"):
    ffmpeg.input(input_path, ss=start, to=end).output(output_path).run(overwrite_output=True, quiet=True)
    return output_path

async def upload_to_telegram(paths):
    app = Client("upload_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await app.start()
    for file in paths:
        print(f"📤 Uploading {file} to Telegram...")
        await app.send_document(CHANNEL_USERNAME, document=file)
    await app.stop()

async def main():
    url = input("📥 Enter video download URL: ").strip()
    filename = extract_filename(url)
    local_path = os.path.join("downloads", filename)

    print(f"🔗 Downloading: {filename}")
    download_file(url, local_path)

    print("\n🔧 Select an option:")
    print("1️⃣ Generate 5 screenshots")
    print("2️⃣ Generate 30-second sample video")
    print("3️⃣ Trim video")
    choice = input("Enter 1, 2 or 3: ").strip()

    if choice == "1":
        print("🖼 Generating screenshots...")
        files = generate_screenshots(local_path)
        await upload_to_telegram(files)

    elif choice == "2":
        print("🎞 Generating sample video...")
        out = generate_sample(local_path)
        await upload_to_telegram([out])

    elif choice == "3":
        probe = ffmpeg.probe(local_path)
        duration = float(probe["format"]["duration"])
        print(f"🎬 Video duration: {int(duration)} seconds")
        start = input("⏱ Enter start time (in seconds): ").strip()
        end = input("⏱ Enter end time (in seconds): ").strip()
        out = trim_video(local_path, start, end)
        await upload_to_telegram([out])
    else:
        print("❌ Invalid option.")

if __name__ == "__main__":
    asyncio.run(main())

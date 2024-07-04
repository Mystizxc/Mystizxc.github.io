import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, redirect, session, url_for, render_template
import sqlite3
import threading
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Spotify API credentials
SPOTIPY_CLIENT_ID = 'e006c97c09374ab1b5a8c136b015660e'
SPOTIPY_CLIENT_SECRET = 'e4ec7a482e674436bd5202af2f8bdf45'
SPOTIPY_REDIRECT_URI = 'https://mystizxc-github-io.onrender.com'

# Spotify authorization scope
SCOPE = 'user-read-recently-played'

# Initialize Spotipy OAuth
sp_oauth = SpotifyOAuth(
    SPOTIPY_CLIENT_ID,
    SPOTIPY_CLIENT_SECRET,
    SPOTIPY_REDIRECT_URI,
    scope=SCOPE
)

# SQLite Database Initialization
DB_NAME = 'spotify_tracks.db'
TOKEN_FILE = 'token_info.json'

def create_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tracks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  track_id TEXT,
                  track_name TEXT,
                  artist_name TEXT,
                  album_cover TEXT,
                  played_at TEXT,
                  UNIQUE(track_id, played_at))''')
    conn.commit()
    conn.close()

# Create the database on startup
create_database()

def save_token_info(token_info):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_info, f)

def load_token_info():
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)

@app.route('/')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    save_token_info(token_info)
    return redirect(url_for('top_tracks'))

@app.route('/top_tracks')
def top_tracks():
    token_info = get_token()
    sp = spotipy.Spotify(auth=token_info['access_token'])

    # Fetch recently played tracks with a larger limit to cover more tracks
    results = sp.current_user_recently_played(limit=50)

    # Update SQLite database with recently played tracks
    update_database(results)

    # Retrieve top tracks from database (top 10 by play count in the past month)
    top_tracks = get_top_tracks()

    return render_template('top_tracks.html', tracks=top_tracks)

def update_database(results):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    for item in results['items']:
        track_id = item['track']['id']
        track_name = item['track']['name']
        artist_name = item['track']['artists'][0]['name']
        album_cover = item['track']['album']['images'][0]['url']
        played_at = item['played_at']

        # Insert a new entry in the database if it doesn't exist
        c.execute('''INSERT OR IGNORE INTO tracks (track_id, track_name, artist_name, album_cover, played_at) 
                     VALUES (?, ?, ?, ?, ?)''', (track_id, track_name, artist_name, album_cover, played_at))
    
    conn.commit()
    conn.close()

def get_top_tracks():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Retrieve top tracks ordered by play count in the past month, limit to 10
    one_month_ago = time.time() - 30*24*60*60
    c.execute('''SELECT track_id, track_name, artist_name, album_cover, COUNT(*) AS play_count 
                 FROM tracks 
                 WHERE played_at >= datetime(?, 'unixepoch')
                 GROUP BY track_id 
                 ORDER BY play_count DESC 
                 LIMIT 10''', (one_month_ago,))
    top_tracks = c.fetchall()
    
    conn.close()
    return top_tracks

def get_token():
    token_info = load_token_info()
    now = int(time.time())
    is_token_expired = token_info['expires_at'] - now < 60

    if is_token_expired:
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        save_token_info(token_info)

    return token_info

def track_completion_listener():
    while True:
        try:
            # Poll or listen for song completion events (e.g., via Spotify API or webhooks)
            token_info = get_token()
            sp = spotipy.Spotify(auth=token_info['access_token'])
            results = sp.current_user_recently_played(limit=1)  # Only fetch the most recently played track

            if results['items']:
                latest_track_id = results['items'][0]['track']['id']
                latest_played_at = results['items'][0]['played_at']

                # Check if the latest track is already in the database
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("SELECT * FROM tracks WHERE track_id=? AND played_at=?", (latest_track_id, latest_played_at))
                existing_track = c.fetchone()
                conn.close()

                if not existing_track:
                    update_database({'items': [results['items'][0]]})
                    
            time.sleep(10)  # Poll every 30 seconds
        except Exception as e:
            print(f"Error in track_completion_listener: {e}")
            time.sleep(10)  # Wait before retrying in case of error

# Start background task for track completion listener
completion_listener_thread = threading.Thread(target=track_completion_listener)
completion_listener_thread.daemon = True
completion_listener_thread.start()

if __name__ == '__main__':
    app.run(debug=True)

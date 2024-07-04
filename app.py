import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, redirect, session, url_for, render_template
import sqlite3
import threading
import json
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Spotify API credentials
SPOTIPY_CLIENT_ID = 'e006c97c09374ab1b5a8c136b015660e'
SPOTIPY_CLIENT_SECRET = 'e4ec7a482e674436bd5202af2f8bdf45'
SPOTIPY_REDIRECT_URI = 'https://mystizxc-github-io.onrender.com/callback'

# Spotify authorization scope
SCOPE = 'user-read-recently-played'

# Initialize Spotipy OAuth
sp_oauth = SpotifyOAuth(
    SPOTIPY_CLIENT_ID,
    SPOTIPY_CLIENT_SECRET,
    SPOTIPY_REDIRECT_URI,
    scope=SCOPE
)

# Initialize Firebase
cred = credentials.Certificate("credentials/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

TOKEN_FILE = 'token_info.json'

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

    # Update Firebase Firestore with recently played tracks
    update_database(results)

    # Retrieve top tracks from Firestore (top 10 by play count in the past month)
    top_tracks = get_top_tracks()

    return render_template('top_tracks.html', tracks=top_tracks)

def update_database(results):
    for item in results['items']:
        track_id = item['track']['id']
        track_name = item['track']['name']
        artist_name = item['track']['artists'][0]['name']
        album_cover = item['track']['album']['images'][0]['url']
        played_at = item['played_at']

        # Create a document ID based on track_id and played_at
        doc_id = f"{track_id}_{played_at}"

        # Check if the document already exists
        doc_ref = db.collection('tracks').document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            # Insert a new entry in the database if it doesn't exist
            doc_ref.set({
                'track_id': track_id,
                'track_name': track_name,
                'artist_name': artist_name,
                'album_cover': album_cover,
                'played_at': firestore.SERVER_TIMESTAMP,
                'played_at_timestamp': time.time()  # Store the actual timestamp
            })

def get_top_tracks():
    one_month_ago = time.time() - 30*24*60*60
    query = db.collection('tracks').where('played_at_timestamp', '>=', one_month_ago)
    docs = query.stream()

    track_dict = {}
    for doc in docs:
        track = doc.to_dict()
        track_id = track['track_id']
        if track_id in track_dict:
            track_dict[track_id]['play_count'] += 1
        else:
            track_dict[track_id] = {
                'track_name': track['track_name'],
                'artist_name': track['artist_name'],
                'album_cover': track['album_cover'],
                'play_count': 1
            }

    sorted_tracks = sorted(track_dict.items(), key=lambda x: x[1]['play_count'], reverse=True)
    return [(k, v['track_name'], v['artist_name'], v['album_cover'], v['play_count']) for k, v in sorted_tracks[:10]]

@app.route('/recently_played')
def recently_played():
    token_info = get_token()
    sp = spotipy.Spotify(auth=token_info['access_token'])

    # Fetch recently played tracks with a larger limit to cover more tracks
    results = sp.current_user_recently_played(limit=50)

    # Process the results for rendering
    tracks = []
    for item in results['items']:
        track = {
            'track_name': item['track']['name'],
            'artist_name': item['track']['artists'][0]['name'],
            'album_cover': item['track']['album']['images'][0]['url'],
            'played_at': item['played_at']
        }
        tracks.append(track)

    return render_template('recently_played.html', tracks=tracks)


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
                doc_ref = db.collection('tracks').document(f"{latest_track_id}_{latest_played_at}")
                if not doc_ref.get().exists:
                    update_database({'items': [results['items'][0]]})
                    
            time.sleep(10)  # Poll every 10 seconds
        except Exception as e:
            print(f"Error in track_completion_listener: {e}")
            time.sleep(10)  # Wait before retrying in case of error

# Start background task for track completion listener
completion_listener_thread = threading.Thread(target=track_completion_listener)
completion_listener_thread.daemon = True
completion_listener_thread.start()

if __name__ == '__main__':
    app.run(debug=True)
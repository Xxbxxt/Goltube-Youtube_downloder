from flask import Flask, render_template, request, send_file, jsonify, Response
from yt_dlp import YoutubeDL
from urllib.parse import urlparse, parse_qs
import os
import logging
import threading
import uuid
import time
import json
import subprocess
import sqlite3
import datetime
import shutil

# ===== Config file persistence =====
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

def load_config():
    """Load configuration from config.json, returning defaults on failure."""
    default = {
        'download_folder': os.path.expanduser('~/Downloads'),
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            default.update(cfg)
    except (json.JSONDecodeError, OSError) as e:
        logging.warning(f"Could not load config file: {e}")
    return default

def save_config(cfg):
    """Save configuration dictionary to config.json."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        logging.warning(f"Could not save config file: {e}")

# Configure logging to display debug messages
logging.getLogger('werkzeug').setLevel(logging.INFO)
logging.basicConfig(level=logging.DEBUG)

# Create a Flask application instance
app = Flask(__name__)

# Define the folder where downloads will be stored (from config or default)
config = load_config()
DOWNLOAD_FOLDER = config.get('download_folder', os.path.expanduser('~/Downloads'))

# Global dictionary to store download progress, keyed by task_id
download_progress = {}
# Cancel events for terminating downloads
_cancel_events = {}

# Create the download folder if it doesn't exist
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)


def check_ffmpeg():
    """Check if FFmpeg is available and warn if not."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        logging.info("FFmpeg detected — audio extraction and format conversion available.")
    except (FileNotFoundError, subprocess.SubprocessError):
        logging.warning("FFmpeg not found! Audio-only downloads and some format conversions will FAIL.")
        logging.warning("Install FFmpeg: https://ffmpeg.org/download.html")

def detect_node():
    """Detect Node.js path for yt-dlp JS runtime support.
    Returns a dict suitable for ydl_opts['js_runtimes'], or None."""
    try:
        # 'where' on Windows, 'which' on Unix
        cmd = ['where', 'node'] if os.name == 'nt' else ['which', 'node']
        node_path = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if node_path.returncode == 0:
            exe = node_path.stdout.strip().split('\n')[0]
            if exe:
                return {'node': {'exe': exe}}
    except Exception:
        pass
    return None

# Run checks at startup
check_ffmpeg()
js_runtimes = detect_node()
if js_runtimes:
    logging.info("Node.js detected — yt-dlp JS runtime available.")
else:
    logging.warning("Node.js not detected. yt-dlp may fail on some YouTube videos.")

# ===== Database (SQLite) =====
DB_PATH = os.path.join(CONFIG_DIR, 'history.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            thumbnail TEXT,
            format TEXT,
            quality TEXT,
            audio_only INTEGER DEFAULT 0,
            filesize INTEGER DEFAULT 0,
            filename TEXT,
            filepath TEXT,
            status TEXT DEFAULT 'completed',
            is_playlist INTEGER DEFAULT 0,
            playlist_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_to_history(data):
    """Insert a completed download into history."""
    try:
        conn = get_db()
        conn.execute('''
            INSERT INTO downloads (url, title, thumbnail, format, quality, audio_only,
                                   filesize, filename, filepath, status, is_playlist, playlist_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('url', ''),
            data.get('title', 'Unknown'),
            data.get('thumbnail', ''),
            data.get('format', 'mp4'),
            data.get('quality', 'best'),
            1 if data.get('audio_only') else 0,
            data.get('filesize', 0),
            data.get('filename', ''),
            data.get('filepath', ''),
            data.get('status', 'completed'),
            1 if data.get('is_playlist') else 0,
            data.get('playlist_count', 0),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Failed to save to history: {e}")

def get_history(search=None, limit=50, offset=0):
    """Fetch download history with optional search."""
    conn = get_db()
    if search:
        rows = conn.execute(
            '''SELECT * FROM downloads
               WHERE title LIKE ? OR url LIKE ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?''',
            (f'%{search}%', f'%{search}%', limit, offset)
        ).fetchall()
        total = conn.execute(
            '''SELECT COUNT(*) FROM downloads WHERE title LIKE ? OR url LIKE ?''',
            (f'%{search}%', f'%{search}%')
        ).fetchone()[0]
    else:
        rows = conn.execute(
            'SELECT * FROM downloads ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall()
        total = conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total

def format_filesize(bytes_val):
    """Convert bytes to human-readable size."""
    if not bytes_val:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

def format_duration(seconds):
    if not seconds:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def check_playlist(url):
    """
    Checks if the provided URL is a YouTube playlist..
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    return 'list' in query_params

###################### Endpoints ######################
@app.route('/')
def index():
    """
    Renders the main page of the application.
    """
    return render_template('index.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/preview', methods=['POST'])
def preview():
    """
    Generates a preview of a YouTube video.

    Accepts a POST request with a 'url' field and returns a JSON object
    containing the video's title, thumbnail, and duration.
    """
    # Handle form data and JSON requests
    url = request.form.get('url')
    if not url and request.json:
        url = request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if check_playlist(url):
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'extract_flat': True,
            'noplaylist': False,
        }
        if js_runtimes:
            ydl_opts['js_runtimes'] = js_runtimes
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    return jsonify({'error': 'Could not retrieve playlist information. The URL might be invalid or unsupported.'}), 400
                if not isinstance(info, dict):
                    return jsonify({'error': 'Unexpected response format from yt-dlp'}), 400
                return jsonify({
                    'title': info.get('title', 'No title available'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'playlist': True,
                    'entries': info.get('entries', [])
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    else: 
        # Set yt-dlp options to quiet mode with format info for size preview
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        
        if js_runtimes:
            ydl_opts['js_runtimes'] = js_runtimes
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    return jsonify({'error': 'Could not retrieve video information. The URL might be invalid or unsupported.'}), 400
                
                if not isinstance(info, dict):
                    return jsonify({'error': 'Unexpected response format from yt-dlp'}), 400

                # Extract best available file size info from formats
                filesize = 0
                # Use filesize from requested_formats if available (bestvideo+bestaudio)
                if info.get('requested_formats'):
                    for f in info['requested_formats']:
                        filesize += f.get('filesize', 0) or f.get('filesize_approx', 0) or 0
                # Fall back to the best format's filesize
                if not filesize and info.get('format_id'):
                    for f in info.get('formats', []):
                        if f.get('format_id') == info['format_id']:
                            filesize = f.get('filesize', 0) or f.get('filesize_approx', 0) or 0
                            break
                # Last resort: estimate from any available format
                if not filesize and info.get('formats'):
                    # Pick middle-ish format for size estimate
                    mid = len(info['formats']) // 2
                    filesize = info['formats'][mid].get('filesize', 0) or info['formats'][mid].get('filesize_approx', 0) or 0
                    
                return jsonify({
                    'title': info.get('title', 'No title available'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'filesize': filesize,
                    'filesize_formatted': format_filesize(filesize) if filesize else None,
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 400

def run_download(task_id, url, ydl_opts, audio_only, format_choice, quality_choice, is_playlist=False):
    # Check for cancellation before starting
    cancel_event = _cancel_events.get(task_id)
    if cancel_event and cancel_event.is_set():
        download_progress[task_id]['status'] = 'cancelled'
        return

    def progress_hook(d):
        # Check cancellation on every progress update
        cancel_event = _cancel_events.get(task_id)
        if cancel_event and cancel_event.is_set():
            raise Exception('Download cancelled by user')
        
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0.0%').strip('%')
            try:
                progress = float(percent_str)
                download_progress[task_id].update({
                    'progress': progress,
                    'status': 'downloading',
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0),
                    'downloaded_bytes': d.get('downloaded_bytes', 0),
                    'total_bytes': d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0),
                })
                if is_playlist and 'info_dict' in d:
                    video_title = d['info_dict'].get('title', '')
                    if video_title:
                        download_progress[task_id]['current_title'] = video_title
            except (ValueError, TypeError):
                pass
        elif d['status'] == 'finished':
            download_progress[task_id]['status'] = 'processing'

    # Let yt-dlp handle playlist natively - it will download all videos in the playlist
    ydl_opts['progress_hooks'] = [progress_hook]

    try:
        logging.info(f"Starting download - is_playlist: {is_playlist}")
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if is_playlist and isinstance(info, dict) and info.get('entries'):
                # Playlist downloaded as a collection
                entries = info['entries']
                filenames = []
                total_size = 0
                for entry in entries:
                    fname = ydl.prepare_filename(entry) if entry else ''
                    if fname:
                        filenames.append(os.path.basename(fname))
                        fpath = os.path.join(DOWNLOAD_FOLDER, fname)
                        if os.path.exists(fpath):
                            total_size += os.path.getsize(fpath)

                display_name = ', '.join(filenames[:3])
                if len(filenames) > 3:
                    display_name += f' (+{len(filenames)-3} more)'

                download_progress[task_id].update({
                    'status': 'finished',
                    'filename': display_name,
                    'progress': 100,
                    'playlist_count': len(filenames),
                    'filesize': total_size,
                })
                logging.info(f"Playlist downloaded: {len(filenames)} videos")

                save_to_history({
                    'url': url,
                    'title': info.get('title', 'Playlist'),
                    'thumbnail': info.get('thumbnail', ''),
                    'format': format_choice,
                    'quality': 'best',
                    'audio_only': audio_only,
                    'filesize': total_size,
                    'filename': display_name,
                    'filepath': DOWNLOAD_FOLDER,
                    'status': 'completed',
                    'is_playlist': True,
                    'playlist_count': len(filenames),
                })
            else:
                # Single video — info is the video dict itself
                video_info = info if isinstance(info, dict) else {}
                filename = ydl.prepare_filename(video_info)
                if audio_only:
                    ext = format_choice if format_choice in ['mp3', 'wav'] else 'mp3'
                    filename = os.path.splitext(filename)[0] + '.' + ext

                # Get file size from the actual file or from info
                filepath = os.path.join(DOWNLOAD_FOLDER, filename)
                filesize = 0
                if os.path.exists(filepath):
                    filesize = os.path.getsize(filepath)
                else:
                    # Try to find the file with a different extension
                    base = os.path.splitext(filepath)[0]
                    for ext in ['.mp4', '.webm', '.mkv', '.mp3', '.wav']:
                        candidate = base + ext
                        if os.path.exists(candidate):
                            filepath = candidate
                            filename = os.path.basename(candidate)
                            filesize = os.path.getsize(candidate)
                            break

                download_progress[task_id].update({
                    'status': 'finished',
                    'filename': filename,
                    'progress': 100,
                    'filesize': filesize,
                })
                logging.info(f"Downloaded: {filename} ({format_filesize(filesize)})")

                save_to_history({
                    'url': url,
                    'title': video_info.get('title', 'Unknown'),
                    'thumbnail': video_info.get('thumbnail', ''),
                    'format': format_choice,
                    'quality': quality_choice,
                    'audio_only': audio_only,
                    'filesize': filesize,
                    'filename': filename,
                    'filepath': filepath,
                    'status': 'completed',
                    'is_playlist': False,
                    'playlist_count': 0,
                })
    except Exception as e:
        err_msg = str(e)
        # Distinguish cancellation from real errors
        cancel_event = _cancel_events.get(task_id)
        is_cancelled = cancel_event and cancel_event.is_set()
        
        if is_cancelled:
            logging.info(f"Download cancelled by user for task {task_id}")
            download_progress[task_id].update({'status': 'cancelled', 'progress': 0})
        else:
            logging.error(f"Error in download thread for task {task_id}: {e}")
            download_progress[task_id].update({'status': 'error', 'error': err_msg})
            save_to_history({
                'url': url,
                'title': 'Download failed',
                'thumbnail': '',
                'format': format_choice,
                'quality': quality_choice,
                'audio_only': audio_only,
                'filesize': 0,
                'filename': '',
                'filepath': '',
                'status': f'error: {err_msg[:100]}',
                'is_playlist': is_playlist,
                'playlist_count': 0,
            })
    finally:
        # Clean up cancel event
        if task_id in _cancel_events:
            del _cancel_events[task_id]

@app.route('/download', methods=['POST'])
def download_video():
    """
    Initiates a YouTube video download in a background thread and returns a task ID.
    """
    url = request.form.get('url', '').strip()
    logging.info(f"Download request started for URL: {url}")
    format_choice = request.form.get('format', 'mp4')
    quality_choice = request.form.get('quality', 'best')
    audio_only = request.form.get('audio_only') == 'yes'

    if not url:
        logging.error("No URL provided for download")
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    # Check if URL is a playlist
    is_playlist = check_playlist(url)
    logging.info(f"Is playlist: {is_playlist}")
    
    # Set yt-dlp options for the download
    # For playlists, create a subfolder with the playlist name
    if is_playlist:
        # Get playlist title first (we'll use a placeholder for now)
        playlist_folder = os.path.join(DOWNLOAD_FOLDER, '%(playlist)s')
        ydl_opts = {
            'outtmpl': os.path.join(playlist_folder, '%(title)s.%(ext)s'),
            'noplaylist': False,
            'quiet': True,
            'no_warnings': True,
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            # Use alternative client
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                }
            },
        }
    else:
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            # Add headers to bypass 403 errors
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            # Use alternative client
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                }
            },
        }
    
    if js_runtimes:
        ydl_opts['js_runtimes'] = js_runtimes

    if audio_only:
        # Configure options for audio-only downloads
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_choice if format_choice in ['mp3', 'wav'] else 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        # Configure options for video downloads
        format_string = f'bestvideo[ext={format_choice}][height<={quality_choice[:-1]}]+bestaudio/best[ext={format_choice}]/best'
        if quality_choice == 'best':
            format_string = f'bestvideo[ext={format_choice}]+bestaudio/best[ext={format_choice}]/best'
        elif quality_choice == 'worst':
            format_string = f'worstvideo[ext={format_choice}]+worstaudio/best[ext={format_choice}]/worst'
        
        ydl_opts['format'] = format_string

    # Generate a unique task ID
    task_id = str(uuid.uuid4())
    _cancel_events[task_id] = threading.Event()
    
    if is_playlist:
        download_progress[task_id] = {
            'progress': 0, 
            'status': 'starting',
            'playlist': True,
            'title': 'Playlist'
        }
        logging.info("Will download playlist using yt-dlp natively")
    else:
        download_progress[task_id] = {'progress': 0, 'status': 'starting'}

    # Start the download in a background thread
    thread = threading.Thread(
        target=run_download,
        args=(task_id, url, ydl_opts, audio_only, format_choice, quality_choice, is_playlist)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'task_id': task_id})

@app.route('/progress/<task_id>')
def progress(task_id):
    """
    Server-Sent Events endpoint to stream download progress.
    """
    def generate():
        while True:
            progress_data = download_progress.get(task_id, {})
            # SSE format: "data: <json_string>\n\n"
            yield f"data: {json.dumps(progress_data)}\n\n"

            if progress_data.get('status') in ['finished', 'error', 'cancelled']:
                # Clean up the task entry after sending the final status
                if task_id in download_progress:
                    del download_progress[task_id]
                break
            
            time.sleep(0.5) # Send updates every 500ms

    return Response(generate(), mimetype='text/event-stream')

@app.route('/downloads/<filename>')
def download_file(filename):
    """
    Serves a downloaded file to the user.
    """
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

@app.route('/set_download_dir', methods=['POST'])
def set_download_dir():
    """
    Sets the download directory.
    """
    global DOWNLOAD_FOLDER, config
    dir_path = request.form.get('dir', '').strip()
    if not dir_path:
        DOWNLOAD_FOLDER = os.path.expanduser('~/Downloads')
    else:
        DOWNLOAD_FOLDER = dir_path
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)
    # Persist to config file
    config['download_folder'] = DOWNLOAD_FOLDER
    save_config(config)
    return jsonify({'success': True})

@app.route('/cancel/<task_id>', methods=['POST'])
def cancel_download(task_id):
    """Cancel an active download."""
    cancel_event = _cancel_events.get(task_id)
    if cancel_event:
        cancel_event.set()
        return jsonify({'success': True, 'message': 'Cancellation requested'})
    # If task_id is not in cancel_events but still in progress, it might have already finished
    progress_data = download_progress.get(task_id, {})
    if progress_data.get('status') in ['finished', 'error', 'cancelled']:
        return jsonify({'success': False, 'error': 'Download already completed or finished'}), 400
    return jsonify({'success': False, 'error': 'Task not found'}), 404

# ===== History API =====

@app.route('/api/history')
def api_history():
    """Get download history with optional search and pagination."""
    search = request.args.get('search', '')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))
    rows, total = get_history(search=search, limit=limit, offset=offset)
    return jsonify({'data': rows, 'total': total})

@app.route('/api/history/stats')
def api_history_stats():
    """Get download statistics."""
    conn = get_db()
    total_downloads = conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
    total_size = conn.execute('SELECT COALESCE(SUM(filesize), 0) FROM downloads').fetchone()[0]
    recent = conn.execute(
        'SELECT * FROM downloads ORDER BY created_at DESC LIMIT 5'
    ).fetchall()
    conn.close()
    return jsonify({
        'total_downloads': total_downloads,
        'total_size': total_size,
        'total_size_formatted': format_filesize(total_size),
        'recent': [dict(r) for r in recent],
    })

@app.route('/api/history/<int:entry_id>', methods=['DELETE'])
def api_delete_history(entry_id):
    """Delete a history entry."""
    conn = get_db()
    conn.execute('DELETE FROM downloads WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/history/clear', methods=['POST'])
def api_clear_history():
    """Clear all history."""
    conn = get_db()
    conn.execute('DELETE FROM downloads')
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# Run the Flask application in debug mode
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
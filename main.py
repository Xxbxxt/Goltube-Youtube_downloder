from flask import Flask, render_template, request, send_file, jsonify, Response
from yt_dlp import YoutubeDL
from urllib.parse import urlparse, parse_qs
import os
import logging
import threading
import uuid
import time
import json

# Configure logging to display debug messages
logging.getLogger('werkzeug').setLevel(logging.INFO)
logging.basicConfig(level=logging.DEBUG)

# Create a Flask application instance
app = Flask(__name__)

# Define the folder where downloads will be stored
DOWNLOAD_FOLDER = os.path.expanduser('~/Downloads')

# Global dictionary to store download progress, keyed by task_id
download_progress = {}

# Create the download folder if it doesn't exist
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)


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
        # Add Node.js config
        try:
            import subprocess
            node_path = subprocess.run(['where', 'node'], capture_output=True, text=True).stdout.strip().split('\n')[0]
            ydl_opts['js_runtimes'] = {'node': {'exe': node_path}}
        except Exception:
            pass
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
        # Set yt-dlp options to quiet mode
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        
        # Try to configure Node.js for yt-dlp
        try:
            import subprocess
            node_path = subprocess.run(['where', 'node'], capture_output=True, text=True).stdout.strip().split('\n')[0]
            ydl_opts['js_runtimes'] = {'node': {'exe': node_path}}
        except Exception:
            pass  # Keep default if detection fails
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    return jsonify({'error': 'Could not retrieve video information. The URL might be invalid or unsupported.'}), 400
                
                if not isinstance(info, dict):
                    return jsonify({'error': 'Unexpected response format from yt-dlp'}), 400
                    
                return jsonify({
                    'title': info.get('title', 'No title available'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0)
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 400

def run_download(task_id, url, ydl_opts, audio_only, format_choice, is_playlist=False, playlist_entries=None):
    """
    This function runs in a separate thread to handle the download,
    updating the progress via the global `download_progress` dictionary.
    """
    def progress_hook(d):
        if d['status'] == 'downloading':
            # Extract percentage and update progress
            percent_str = d.get('_percent_str', '0.0%').strip('%')
            try:
                progress = float(percent_str)
                download_progress[task_id]['progress'] = progress
                download_progress[task_id]['status'] = 'downloading'
                # For playlists, show which video is downloading
                if is_playlist and 'info_dict' in d:
                    video_title = d['info_dict'].get('title', '')
                    if video_title:
                        download_progress[task_id]['current_title'] = video_title
            except (ValueError, TypeError):
                pass # Ignore if conversion fails
        elif d['status'] == 'finished':
            download_progress[task_id]['status'] = 'processing'

    # Let yt-dlp handle playlist natively - it will download all videos in the playlist
    ydl_opts['progress_hooks'] = [progress_hook]

    try:
        logging.info(f"Starting download - is_playlist: {is_playlist}")
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # For playlists, info might be a list of entries
            if is_playlist and isinstance(info, list):
                # Multiple videos downloaded
                filenames = []
                for entry in info:
                    filename = ydl.prepare_filename(entry)
                    filenames.append(os.path.basename(filename))
                download_progress[task_id].update({
                    'status': 'finished',
                    'filename': ', '.join(filenames),
                    'progress': 100
                })
                logging.info(f"Playlist downloaded: {len(filenames)} videos")
            else:
                # Single video
                filename = ydl.prepare_filename(info)
                if audio_only:
                    filename = os.path.splitext(filename)[0] + '.' + (format_choice if format_choice in ['mp3', 'wav'] else 'mp3')
                
                download_progress[task_id].update({
                    'status': 'finished',
                    'filename': os.path.basename(filename),
                    'progress': 100
                })
                logging.info(f"Downloaded: {filename}")
    except Exception as e:
        logging.error(f"Error in download thread for task {task_id}: {e}")
        download_progress[task_id].update({'status': 'error', 'error': str(e)})
    ydl_opts['progress_hooks'] = [progress_hook]

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if audio_only:
                filename = os.path.splitext(filename)[0] + '.' + (format_choice if format_choice in ['mp3', 'wav'] else 'mp3')
            
            download_progress[task_id].update({
                'status': 'finished',
                'filename': os.path.basename(filename),
                'progress': 100
            })
    except Exception as e:
        logging.error(f"Error in download thread for task {task_id}: {e}")
        download_progress[task_id].update({'status': 'error', 'error': str(e)})

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
    
    # Try to configure Node.js for yt-dlp (requires full path on Windows)
    try:
        import subprocess
        node_path = subprocess.run(['where', 'node'], capture_output=True, text=True).stdout.strip().split('\n')[0]
        ydl_opts['js_runtimes'] = {'node': {'exe': node_path}}
    except Exception:
        pass  # Keep default if detection fails

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
    
    # For playlists, let yt-dlp handle it natively - don't pre-extract entries
    playlist_entries = None
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
        args=(task_id, url, ydl_opts, audio_only, format_choice, is_playlist, playlist_entries)
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

            if progress_data.get('status') in ['finished', 'error']:
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
    global DOWNLOAD_FOLDER
    dir_path = request.form.get('dir', '').strip()
    if not dir_path:
        DOWNLOAD_FOLDER = os.path.expanduser('~/Downloads')
    else:
        DOWNLOAD_FOLDER = dir_path
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)
    return jsonify({'success': True})

# Run the Flask application in debug mode
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
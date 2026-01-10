from flask import Flask, render_template, request, send_file, jsonify, Response
from yt_dlp import YoutubeDL
import os
import logging
import threading
import uuid
import time
import json

# Configure logging to display debug messages
# Suppress werkzeug's default INFO logs for cleaner output
logging.getLogger('werkzeug').setLevel(logging.WARNING)
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
    url = request.form['url']
    logging.debug(f"Preview request for URL: {url}")
    
    # Set yt-dlp options to quiet mode to prevent verbose output
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'remote_components': 'ejs:github'
    }
    try:
        # Use YoutubeDL to extract video information without downloading
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            logging.debug(f"Extracted info: title={info.get('title')}, thumbnail={info.get('thumbnail')}, duration={info.get('duration')}")
            return jsonify({
                'title': info.get('title', 'No title available'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0)
            })
    except Exception as e:
        logging.error(f"Error in preview: {e}")
        return jsonify({'error': str(e)}), 400

def run_download(task_id, url, ydl_opts, audio_only, format_choice):
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
            except (ValueError, TypeError):
                pass # Ignore if conversion fails
        elif d['status'] == 'finished':
            download_progress[task_id]['status'] = 'processing'

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
    logging.debug(f"Download request for URL: {url}")
    format_choice = request.form.get('format', 'mp4')
    quality_choice = request.form.get('quality', 'best')
    audio_only = request.form.get('audio_only') == 'yes'

    if not url:
        logging.error("No URL provided for download")
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    # Set yt-dlp options for the download
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'noplaylist': True,
        'remote_components': 'ejs:github',
        # Suppress yt-dlp's own console output to avoid clutter
        'quiet': True,
        'no_warnings': True,
    }

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
    download_progress[task_id] = {'progress': 0, 'status': 'starting'}

    # Start the download in a background thread
    thread = threading.Thread(target=run_download, args=(task_id, url, ydl_opts, audio_only, format_choice))
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
    app.run(debug=True)
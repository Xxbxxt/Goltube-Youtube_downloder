from flask import Flask, render_template, request, send_file, jsonify
from yt_dlp import YoutubeDL
import os
import logging

# Configure logging to display debug messages
logging.basicConfig(level=logging.DEBUG)

# Create a Flask application instance
app = Flask(__name__)

# Define the folder where downloads will be stored
DOWNLOAD_FOLDER = "downloads"

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
    ydl_opts = {'quiet': True, 'js_runtimes': {'node': {}}}
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

@app.route('/download', methods=['POST'])
def download_video():
    """
    Downloads a YouTube video with the specified options.

    Accepts a POST request with 'url', 'format', 'quality', and 'audio_only' fields.
    Returns a JSON response indicating success or failure.
    """
    url = request.form.get('url', '').strip()
    logging.debug(f"Download request for URL: {url}")
    format_choice = request.form.get('format', 'mp4')
    quality_choice = request.form.get('quality', 'best')
    audio_only = request.form.get('audio_only') == 'yes'

    if not url:
        logging.error("No URL provided for download")
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    try:
        # Set yt-dlp options for the download
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'js_runtimes': {'node': {}},
            'ffmpeg_location': os.path.join(os.path.dirname(__file__), 'ffmpeg', 'ffmpeg-8.0.1-essentials_build', 'bin', 'ffmpeg.exe'),
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
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            })
        else:
            # Configure options for video downloads
            format_string = f'bestvideo[ext={format_choice}][height<={quality_choice[:-1]}]+bestaudio/best[ext={format_choice}]/best'
            if quality_choice == 'best':
                format_string = f'bestvideo[ext={format_choice}]+bestaudio/best[ext={format_choice}]/best'
            elif quality_choice == 'worst':
                format_string = f'worstvideo[ext={format_choice}]+worstaudio/best[ext={format_choice}]/worst'
            
            ydl_opts['format'] = format_string

        # Use YoutubeDL to download the video
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # For audio, the extension is changed by the postprocessor
            if audio_only:
                filename = os.path.splitext(filename)[0] + '.' + (format_choice if format_choice in ['mp3', 'wav'] else 'mp3')
            
            return jsonify({'success': True, 'filename': os.path.basename(filename)})

    except Exception as e:
        logging.error(f"Error in download: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/downloads/<filename>')
def download_file(filename):
    """
    Serves a downloaded file to the user.
    """
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

# Run the Flask application in debug mode
if __name__ == '__main__':
    app.run(debug=True)
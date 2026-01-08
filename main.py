from flask import Flask, render_template, request, send_file
from yt_dlp import YoutubeDL
import os


app = Flask(__name__)


DOWNLOAD_FOLDER = "downloads"


if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)   


@app.route('/')
def index():
    return render_template('index.html')     

@app.route('/download', methods=['POST'])
def download_video():
    url = request.form['url']
    format_choice = request.form['format']
    quality_choice = request.form['quality']
    audio_only = request.form.get('audio_only') == 'yes'

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
    }


    if audio_only:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        if format_choice == 'mp4':
            ydl_opts['format'] = f'bestvideo[ext=mp4][height<={quality_choice}]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality_choice}]'
        elif format_choice == 'webm':
            ydl_opts['format'] = f'bestvideo[ext=webm][height<={quality_choice}]+bestaudio[ext=webm]/best[ext=webm][height<={quality_choice}]'
    
    
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return "Download started!"


if __name__ == '__main__':
    app.run(debug=True)
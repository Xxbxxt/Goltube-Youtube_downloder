# Gol tube

A simple web application to download YouTube videos. It allows previewing videos, choosing formats (MP4, MP3, WEBM), and quality.

## Features

- Download YouTube videos in different formats (MP4, MP3, WEBM) and qualities.
- Audio-only download option.
- Video preview before downloading.
- Real-time download progress bar.
- Settings to change the default download path.

## How to run the application

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd Youtube_downloder
    ```

2.  **Create a virtual environment and install dependencies:**
    It is recommended to use a virtual environment.

    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
    ```

    Install the required packages from `pyproject.toml`:
    ```bash
    pip install -e .
    ```
    You also need to have `ffmpeg` installed and available in your system's PATH.

3.  **Run the Flask application:**
    ```bash
    python main.py
    ```

4.  **Open the application in your browser:**
    Navigate to `http://127.0.0.1:5000/` in your web browser.

## Dependencies

The project uses the following main libraries:

-   `Flask`: For the web framework.
-   `yt-dlp`: For downloading video content.
-   `Flask-SocketIO`: For real-time communication (used for progress updates).
-   `ffmpeg`: For audio extraction and format conversion.

The specific versions are listed in the `pyproject.toml` file.

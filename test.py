from yt_dlp import YoutubeDL

def test_youtube_url(url):
    """
    Tests if yt-dlp can extract information from a YouTube URL.
    This function will be used to verify the fix for the JavaScript challenge.
    """
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
    }
    # Try to configure Node.js for yt-dlp (requires full path on Windows)
    try:
        import subprocess
        # Use 'where' on Windows, 'which' on Linux/macOS
        command = 'where' if os.name == 'nt' else 'which'
        node_path = subprocess.run([command, 'node'], capture_output=True, text=True, check=True).stdout.strip().split('\n')[0]
        ydl_opts['js_runtimes'] = {'node': {'exe': node_path}}
    except (subprocess.CalledProcessError, IndexError, FileNotFoundError):
        print("Node.js executable not found or 'where'/'which' command failed. yt-dlp might not function optimally.")
        # Keep default if detection fails, or proceed without explicit path
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                print(f"Failed to extract info for URL: {url}. yt-dlp returned no data.")
                return False
            if info:
                print(f"Successfully extracted info for URL: {url}")
                print(f"Title: {info.get('title')}")
                return True
            else:
                print(f"Failed to extract info for URL: {url}")
                return False
    except Exception as e:
        print(f"An error occurred while testing URL {url}: {e}")
        return False

if __name__ == '__main__':
    # This is the URL that was causing the error in the logs
    test_url = 'https://youtu.be/9Y1A2nw_Veg'
    if test_youtube_url(test_url):
        print("Test passed: The fix for the yt-dlp JavaScript challenge appears to be working.")
    else:
        print("Test failed: The fix for the yt-dlp JavaScript challenge might not be working correctly.")

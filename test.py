from yt_dlp import YoutubeDL

def test_youtube_url(url):
    """
    Tests if yt-dlp can extract information from a YouTube URL.
    This function will be used to verify the fix for the JavaScript challenge.
    """
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'remote_components': 'ejs:github'
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
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

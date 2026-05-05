import sys
import traceback
import json
import http.cookiejar
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from requests import Session
from config import Config

def test_transcript(video_id):
    try:
        print(f"Testing video ID: {video_id}")
        
        # Setup proxies
        proxy_config = None
        if Config.YOUTUBE_PROXIES:
            try:
                proxies_dict = json.loads(Config.YOUTUBE_PROXIES)
                print(f"Using proxies: {proxies_dict}")
                proxy_config = GenericProxyConfig(
                    http_url=proxies_dict.get("http"),
                    https_url=proxies_dict.get("https")
                )
            except Exception as e:
                print(f"Failed to parse YOUTUBE_PROXIES: {e}")

        # Setup cookies via custom Session
        session = Session()
        if Config.YOUTUBE_COOKIES:
            try:
                cj = http.cookiejar.MozillaCookieJar(Config.YOUTUBE_COOKIES)
                cj.load(ignore_discard=True, ignore_expires=True)
                session.cookies = cj
                print(f"Using cookies from: {Config.YOUTUBE_COOKIES}")
            except Exception as e:
                print(f"Failed to load YOUTUBE_COOKIES: {e}")

        api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
        transcript_list = api.list(video_id)
        print("Transcript list found!")
        
        for t in transcript_list:
            print(f"Attempting to fetch: {t.language} ({t.language_code}) [Generated: {t.is_generated}]")
            try:
                transcript = t.fetch()
                data = transcript.to_raw_data()
                print(f"  SUCCESS! First entry: {data[0]['text'][:50]}...")
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")

    except Exception as e:
        print(f"Error caught: {type(e).__name__}: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_transcript(sys.argv[1])
    else:
        test_transcript("FyMhDj-xBq8")

import sys
import traceback
from youtube_transcript_api import YouTubeTranscriptApi

def test_transcript(video_id):
    try:
        print(f"Testing video ID: {video_id}")
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        print("Transcript list found!")
        
        for t in transcript_list:
            print(f"Attempting to fetch: {t.language} ({t.language_code}) [Generated: {t.is_generated}]")
            try:
                transcript = t.fetch().to_raw_data()
                print(f"  SUCCESS! First entry: {transcript[0]['text'][:50]}...")
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

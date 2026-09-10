import base64
import json
import os
import pickle
import sys

import googleapiclient.discovery
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload

# Set up absolute base path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if BASE_DIR in sys.path:
    sys.path.remove(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# Import the processing function from your Warrior Ethos pipeline module
from warrior_ethos.main import process_script_item

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"  # Required to post comments
]

def get_service(
    pickle_file: str = os.path.join(BASE_DIR, "warrior_pickle.pickle"),
    client_secrets: str = os.path.join(BASE_DIR, "client_secret_warrior_ethos.json"),
):
    creds = None

    # Restore token from GitHub Secret
    if not os.path.exists(pickle_file) and os.environ.get("WARRIOR_TOKEN_PICKLE_BASE64"):
        print("🔑 Restoring Warrior Ethos pickle token from GitHub Secrets...")

        token_data = base64.b64decode(
            os.environ["WARRIOR_TOKEN_PICKLE_BASE64"]
        )

        with open(pickle_file, "wb") as f:
            f.write(token_data)

    # Load existing credentials
    if os.path.exists(pickle_file):
        print("🔐 Loading Warrior Ethos OAuth credentials...")

        with open(pickle_file, "rb") as f:
            creds = pickle.load(f)

    # Refresh existing credentials
    if creds and creds.expired and creds.refresh_token:
        print("🔄 Refreshing YouTube access token...")

        try:
            creds.refresh(Request())

            # Save refreshed credentials
            with open(pickle_file, "wb") as f:
                pickle.dump(creds, f)

            print("✅ Token refreshed successfully.")

        except Exception as e:
            print(f"⚠️ Could not refresh token: {e}")
            creds = None

    # If credentials are still invalid
    if not creds or not creds.valid:

        # NEVER try browser OAuth in GitHub Actions
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError(
                "❌ YouTube OAuth credentials are missing or invalid in GitHub Actions. "
                "Generate warrior_pickle.pickle locally and store it as "
                "WARRIOR_TOKEN_PICKLE_BASE64."
            )

        # Local machine authentication
        if not os.path.exists(client_secrets):
            raise FileNotFoundError(
                f"❌ Missing '{client_secrets}'."
            )

        print("--- AUTHENTICATION REQUIRED (WARRIOR ETHOS) ---")

        flow = InstalledAppFlow.from_client_secrets_file(
            client_secrets,
            SCOPES
        )

        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent"
        )

        with open(pickle_file, "wb") as f:
            pickle.dump(creds, f)

        print("✅ Local YouTube authentication successful.")
        print(f"💾 Saved credentials to: {pickle_file}")

    return googleapiclient.discovery.build(
        "youtube",
        "v3",
        credentials=creds
    )

def build_fallback_pin_comment() -> str:
    return "Discipline over motivation. Are you putting in the work today? Drop a 🔥 below!"


def post_and_pin_comment(youtube, video_id: str, comment_text: str) -> bool:
    """Posts a comment on the uploaded video."""
    if not comment_text or not comment_text.strip():
        print("⚠️ No pin comment text provided. Skipping comment creation.")
        return False

    try:
        comment_request = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": comment_text.strip()
                        }
                    }
                }
            }
        )
        comment_response = comment_request.execute()
        comment_id = comment_response.get("id")
        print(f"💬 Comment posted successfully: '{comment_text.strip()}'")
        print(f"📌 Comment ready at: https://www.youtube.com/watch?v={video_id}")
        return True

    except Exception as e:
        print(f"⚠️ Failed to post comment: {e}")
        return False


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    comment_text: str = None
) -> bool:
    """Uploads video to YouTube and posts pinned comment."""
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        print(f"📤 Uploading '{os.path.basename(video_path)}'...")
        youtube = get_service()

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": "27"  # Category 27 = Education / Motivation
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False
                }
            },
            media_body=MediaFileUpload(
                video_path, chunksize=-1, resumable=True, mimetype="video/mp4"
            )
        )

        response = request.execute()
        video_id = response.get('id')
        print(f"✅ Upload successful! URL: https://www.youtube.com/watch?v={video_id}")

        # Post engaging comment if present
        if comment_text:
            post_and_pin_comment(youtube, video_id, comment_text)

        return True

    except Exception as e:
        print(f"❌ YouTube Upload Error: {e}")
        return False


def build_metadata(
    script_title: str, tag: str = "", custom_caption: str = None
) -> tuple[str, str, list[str]]:
    """Generates YouTube title, description, and tags tailored for Warrior Ethos & Stoicism."""
    base_text = (
        custom_caption
        if (custom_caption and custom_caption.strip())
        else script_title
    )

    tag_lower = tag.lower()

    # Dynamic Tag & Hashtag Mapping Based on Tag Category
    if "ancient_warriors" in tag_lower:
        tags = ["ancientwarriors", "warriormindset", "spartan", "history", "discipline", "shorts"]
        emoji = "⚔️🛡️"
    elif "gym_training" in tag_lower:
        tags = ["gymmotivation", "bodybuilding", "workout", "fitness", "discipline", "shorts"]
        emoji = "🏋️‍♂️🔥"
    elif "rainy_city" in tag_lower:
        tags = ["darkacademia", "lone wolf", "mindset", "focus", "grindinsilence", "shorts"]
        emoji = "🌧️🐺"
    else:  # Default / Statues_Stoicism
        tags = ["stoicism", "marcusaurelius", "stoicmindset", "warriorethos", "discipline", "shorts"]
        emoji = "🏛️🗿"

    title = f"{base_text} {emoji} #shorts"
    if len(title) > 100:
        title = title[:90].strip() + "... #shorts"

    formatted_hashtags = " ".join([f"#{t}" for t in tags])
    description = (
        f"{base_text}\n\n"
        f"{formatted_hashtags}\n\n"
        f"⚔️ Unshakable Discipline & Mindset\n"
        f"🔴 Subscribe to Warrior Ethos for daily motivation."
    )

    return title, description, tags


def run_automation():
    """Main function to scan queue, generate video, upload, and update warrior.json."""
    json_file = os.path.join(BASE_DIR, "warrior_ethos", "warriorethos.json")
    assets_dir = os.path.join(BASE_DIR, "warrior_ethos", "background_assets")
    audio_dir = os.path.join(BASE_DIR, "warrior_ethos", "voiceovers")
    output_dir = os.path.join(BASE_DIR, "warrior_ethos", "output")
    bgm_dir = os.path.join(BASE_DIR, "background_music", "warrior_ethos")

    if not os.path.exists(json_file):
        print(f"❌ JSON file missing: {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_index = None
    target_item = None

    # Locate the first unposted script entry
    for idx, item in enumerate(data):
        is_posted = item.get("posted", False)
        if is_posted is False or str(is_posted).lower() == "false":
            target_index = idx
            target_item = item
            break

    if target_item is None:
        print("✅ All queued Warrior Ethos scripts have been posted!")
        return

    script_title = target_item.get("script_title", "").strip()
    tag = target_item.get("tag", "")
    print(
        f"\n🚀 Processing Warrior Script [{target_index + 1}/{len(data)}]: '{script_title}' (Tag: {tag})"
    )

    try:
        generated_video_path = process_script_item(
            script_data=target_item,
            assets_dir=assets_dir,
            audio_dir=audio_dir,
            bgm_dir=bgm_dir,
            bgm_volume=float(target_item.get("bgm_volume", 0.5)),
            output_dir=output_dir,
            transition_duration=float(target_item.get("transition_duration", 0.6)),
        )
    except Exception as exc:
        print(f"❌ Video Generation Failed: {exc}")
        return

    title, description, tags = build_metadata(
        script_title, tag, target_item.get("caption")
    )

    # Check for pinned_comment or pin_comment from JSON or fall back
    comment_text = (
        target_item.get("pinned_comment")
        or build_fallback_pin_comment()
    )

    if upload_to_youtube(generated_video_path, title, description, tags, comment_text):
        data[target_index]["posted"] = True

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        print(f"💾 Updated JSON: Marked '{script_title}' as posted.")

        if os.path.exists(generated_video_path):
            os.remove(generated_video_path)
            print("🧹 Cleaned up temporary video file.")
    else:
        print("❌ Upload failed. JSON state left unchanged.")


if __name__ == "__main__":
    run_automation()
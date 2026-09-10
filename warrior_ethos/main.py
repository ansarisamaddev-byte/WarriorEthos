import os
import sys
import re
import glob
import math
import random
import json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip, concatenate_audioclips
from moviepy.video.VideoClip import ImageClip, VideoClip
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import moviepy.video.fx as vfx
import moviepy.audio.fx as afx

from caption_generator import CONFIG_STYLE_PUNCHY, generate_caption_overlay
from animations import build_transitioned_timeline, TRANSITION_REGISTRY, DIP_TRANSITIONS


def resolve_project_path(*path_parts: str) -> str:
    path_inside = os.path.abspath(os.path.join(BASE_DIR, *path_parts))
    if os.path.exists(path_inside):
        return path_inside

    path_parent = os.path.abspath(os.path.join(BASE_DIR, "..", *path_parts))
    return path_parent


DEFAULT_SFX_DIR = resolve_project_path("warrior_ethos", "sfx")
DEFAULT_STICKERS_DIR = resolve_project_path("warrior_ethos", "stickers")
DEFAULT_ASSETS_DIR = resolve_project_path("warrior_ethos", "background_assets")
DEFAULT_BGM_DIR = resolve_project_path("background_music", "warrior_ethos")


def sanitize_filename(name: str) -> str:
    clean_name = re.sub(r'[\\/*?:"<>|]', "", name)
    return re.sub(r'\s+', ' ', clean_name).strip()


def find_audio_file(audio_dir: str, target_title: str) -> str:
    clean_target = sanitize_filename(target_title).lower()
    if not os.path.exists(audio_dir):
        os.makedirs(audio_dir, exist_ok=True)

    for file in os.listdir(audio_dir):
        if file.lower().endswith((".mp3", ".wav", ".m4a")):
            file_stem = os.path.splitext(file)[0]
            clean_file_stem = re.sub(r'\s+', ' ', file_stem).strip().lower()
            if clean_file_stem == clean_target:
                return os.path.join(audio_dir, file)

    dummy_audio_path = os.path.join(audio_dir, f"{target_title}.mp3")
    if not os.path.exists(dummy_audio_path):
        from moviepy.audio.AudioClip import AudioArrayClip
        make_silence = AudioArrayClip(np.zeros((44100 * 5, 2)), fps=44100)
        make_silence.write_audiofile(dummy_audio_path, fps=44100)
    return dummy_audio_path


def get_random_bgm_file(bgm_dir: str) -> str:
    if not os.path.exists(bgm_dir):
        return None
    if os.path.isfile(bgm_dir):
        return bgm_dir

    valid_extensions = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg", "*.flac")
    bgm_files = []
    for ext in valid_extensions:
        bgm_files.extend(glob.glob(os.path.join(bgm_dir, ext)))

    if not bgm_files:
        return None
    return random.choice(bgm_files)


def align_timeline_with_audio(audio_path: str, scenes: list) -> list:
    if not scenes or not os.path.exists(audio_path):
        return scenes

    with AudioFileClip(audio_path) as audio:
        total_duration = audio.duration

    num_segments = len(scenes)
    step = total_duration / num_segments

    aligned_timeline = []
    for idx, seg in enumerate(scenes):
        seg_copy = dict(seg)
        seg_copy["start"] = round(idx * step, 2)
        aligned_timeline.append(seg_copy)

    return aligned_timeline


def force_aspect_fill(image_array, target_w=1080, target_h=1920):
    img_h, img_w = image_array.shape[:2]

    if img_w <= 0 or img_h <= 0:
        return np.zeros((target_h, target_w, 3), dtype=np.uint8)

    scale = max(
        target_w / float(img_w),
        target_h / float(img_h)
    )

    new_w = int(math.ceil(img_w * scale))
    new_h = int(math.ceil(img_h * scale))

    resized = cv2.resize(
        image_array,
        (new_w, new_h),
        interpolation=cv2.INTER_LINEAR
    )

    crop_x = max(0, (new_w - target_w) // 2)
    crop_y = max(0, (new_h - target_h) // 2)

    cropped = resized[
        crop_y:crop_y + target_h,
        crop_x:crop_x + target_w
    ]

    if cropped.shape[0] != target_h or cropped.shape[1] != target_w:
        cropped = cv2.resize(
            cropped,
            (target_w, target_h),
            interpolation=cv2.INTER_LINEAR
        )

    return cropped


def apply_background_effect(
    clip,
    effect_type="zoom_in",
    duration=5.0,
    target_w=1080,
    target_h=1920
):
    def transform_frame(get_frame, t):
        raw_frame = get_frame(t)

        if raw_frame is None or raw_frame.size == 0:
            return np.zeros((target_h, target_w, 3), dtype=np.uint8)

        base_frame = force_aspect_fill(raw_frame, target_w, target_h)
        progress = min(max(t / max(duration, 0.001), 0.0), 1.0)

        if effect_type == "zoom_in":
            scale = 1.0 + (0.15 * progress)
        elif effect_type == "zoom_out":
            scale = 1.15 - (0.15 * progress)
        elif effect_type in ("pan_right", "pan_left"):
            scale = 1.10
        else:
            scale = 1.0

        scaled_w = max(target_w, int(math.ceil(target_w * scale)))
        scaled_h = max(target_h, int(math.ceil(target_h * scale)))

        resized = cv2.resize(base_frame, (scaled_w, scaled_h), interpolation=cv2.INTER_LINEAR)

        if effect_type in ("pan_right", "pan_left"):
            max_shift = scaled_w - target_w
            shift_x = int(progress * max_shift) if effect_type == "pan_left" else int((1.0 - progress) * max_shift)
            crop_x = max(0, min(max_shift, shift_x))
            crop_y = (scaled_h - target_h) // 2
        else:
            crop_x = (scaled_w - target_w) // 2
            crop_y = (scaled_h - target_h) // 2

        cropped = resized[crop_y:crop_y + target_h, crop_x:crop_x + target_w]

        if cropped.shape[:2] != (target_h, target_w):
            cropped = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        return cropped

    return clip.transform(transform_frame).with_position((0, 0))

def loop_video_to_duration(
    source_clip,
    target_duration,
    crossfade_duration=0.5
):
    """Loops a source video clip at its standard, native speed to fill target_duration."""
    clip_len = source_clip.duration
    
    # If the clip is already long enough, slice it directly at native speed
    if clip_len >= target_duration:
        return source_clip.subclipped(0, target_duration).with_position((0, 0))

    forward_clip = source_clip
    reversed_clip = source_clip.with_effects([vfx.TimeMirror()])

    composite_layers = []
    current_time = 0.0
    i = 0

    # Chain alternating forward/reverse clips at natural playback speed
    while current_time < target_duration:
        base = forward_clip if i % 2 == 0 else reversed_clip
        if i == 0:
            layer = base.with_start(0)
        else:
            layer = base.with_start(current_time).with_effects([vfx.CrossFadeIn(crossfade_duration)])

        composite_layers.append(layer)
        current_time += max(0.1, (clip_len - crossfade_duration))
        i += 1

    composited = CompositeVideoClip(composite_layers, size=source_clip.size, bg_color=(0, 0, 0))
    return composited.subclipped(0, target_duration).with_position((0, 0))

def build_dynamic_transitioned_timeline(
    clip_list,
    scene_transitions,
    duration=0.6,
    size=(1080, 1920),
    final_duration=None
):
    if not clip_list:
        return None

    if len(clip_list) == 1:
        return clip_list[0].with_duration(
            final_duration if final_duration is not None else clip_list[0].duration
        )

    timeline = []
    current_start = 0.0

    first = clip_list[0].with_start(0)
    timeline.append(first)

    for i in range(1, len(clip_list)):
        previous = clip_list[i - 1]
        incoming = clip_list[i]
        
        transition_type = scene_transitions[i] if i < len(scene_transitions) else "zoom_dissolve"
        if transition_type not in TRANSITION_REGISTRY:
            transition_type = "zoom_dissolve"

        t_duration = min(duration, min(previous.duration, incoming.duration) / 2)
        if transition_type == "cut_smooth":
            t_duration = min(t_duration, 0.15)

        if transition_type in DIP_TRANSITIONS:
            half = t_duration / 2.0
            color = (0, 0, 0) if transition_type == "dip_to_black" else (255, 255, 255)

            timeline[-1] = timeline[-1].with_effects([vfx.CrossFadeOut(half)])
            start = current_start + previous.duration
            incoming_clip = incoming.with_effects([vfx.CrossFadeIn(half)]).with_start(start)

            timeline.append(incoming_clip)
            current_start = start
        else:
            start = current_start + previous.duration - t_duration
            effect_fn = TRANSITION_REGISTRY[transition_type]
            incoming_clip = effect_fn(previous, incoming, t_duration, size=size).with_start(start)

            timeline.append(incoming_clip)
            current_start = start

    if final_duration is None:
        final_duration = current_start + clip_list[-1].duration

    result = CompositeVideoClip(timeline, size=size, bg_color=(0, 0, 0))
    return result.with_duration(final_duration)


def get_unique_clips(folder_path, num_needed):
    valid_extensions = ('.mp4', '.mov', '.mkv', '.webm')
    
    with os.scandir(folder_path) as entries:
        all_clips = [
            entry.path for entry in entries 
            if entry.is_file() and entry.name.lower().endswith(valid_extensions)
        ]

    if len(all_clips) < num_needed:
        raise ValueError(f"Need {num_needed} clips, but only found {len(all_clips)} in {folder_path}")

    return random.sample(all_clips, k=num_needed)


def create_enhanced_bottom_shadow_overlay(width=1080, height=1920, duration=1.0):
    alpha = np.zeros((height, width), dtype=np.float32)
    shadow_h = int(height * 0.50)
    start_y = height - shadow_h

    gradient = np.linspace(0.0, 0.90, shadow_h, dtype=np.float32) ** 1.8
    alpha[start_y:, :] = gradient[:, None]

    black_frame = np.zeros((height, width, 3), dtype=np.uint8)
    shadow_image = ImageClip(black_frame).with_duration(duration)
    shadow_mask = ImageClip(alpha, is_mask=True).with_duration(duration)

    return shadow_image.with_mask(shadow_mask).with_position((0, 0))


def split_words_by_punctuation(words_data: list, max_words_per_batch: int = 3) -> list:
    batches = []
    current_batch = []

    for item in words_data:
        word = item.get("word", "")
        current_batch.append(item)

        has_punctuation = bool(re.search(r'[.?!]', word))
        if has_punctuation or len(current_batch) >= max_words_per_batch:
            batches.append(current_batch)
            current_batch = []

    if current_batch:
        batches.append(current_batch)

    return batches


def create_heading_clip(text: str, duration: float, width: int = 1080, height: int = 1920) -> ImageClip:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arialbd.ttf", 34)
    except IOError:
        font = ImageFont.load_default()

    clean_text = " ".join(list(text.upper().strip()))

    bbox = font.getbbox(clean_text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x = 24
    pad_y = 12

    y_center = int(height * 0.15)
    x_center = width // 2

    box_left = x_center - (text_w // 2) - pad_x
    box_top = y_center - (text_h // 2) - pad_y
    box_right = x_center + (text_w // 2) + pad_x
    box_bottom = y_center + (text_h // 2) + pad_y

    draw.rounded_rectangle(
        [box_left, box_top, box_right, box_bottom],
        radius=10,
        fill=(15, 15, 18, 220),
        outline=(255, 215, 0, 180),
        width=2
    )

    text_x = x_center - (text_w // 2)
    text_y = y_center - (text_h // 2) - bbox[1]
    draw.text((text_x, text_y), clean_text, font=font, fill=(255, 255, 255, 240))

    return ImageClip(np.array(img)).with_duration(duration)


def process_script_item(
    script_data: dict,
    assets_dir: str = DEFAULT_ASSETS_DIR,
    audio_dir: str = None,
    bgm_dir: str = DEFAULT_BGM_DIR,
    bgm_volume: float = 0.5,
    output_dir: str = "output",
    transition_duration: float = 0.6,
    caption_config: dict = CONFIG_STYLE_PUNCHY
) -> str:
    if isinstance(script_data, tuple):
        script_data = script_data[0]

    video_id = script_data.get("id", "001")
    script_title = script_data.get("script_title")
    tag = script_data.get("tag", "")
    bg_music_target = script_data.get("bg_music", "")
    scenes = script_data.get("scenes", [])

    if not script_title or not scenes:
        raise ValueError("Script object must contain 'script_title' and 'scenes'.")

    if audio_dir is None:
        audio_dir = resolve_project_path("voiceover")

    os.makedirs(output_dir, exist_ok=True)

    target_assets_dir = assets_dir
    if tag:
        tagged_dir = os.path.join(assets_dir, tag)
        if os.path.exists(tagged_dir):
            target_assets_dir = tagged_dir
            print(f"[ASSETS] Using tagged subfolder: {target_assets_dir}")
        else:
            print(f"[ASSETS WARNING] Tag folder '{tagged_dir}' not found. Falling back to default: {assets_dir}")

    audio_path = find_audio_file(audio_dir, script_title)
    main_audio = AudioFileClip(audio_path)
    audio_duration = main_audio.duration

    scenes = align_timeline_with_audio(audio_path, scenes)

    media_clips = []
    heading_clips = []
    scene_transitions = []
    sound_effects = [main_audio]
    bgm_clip = None
    final_video = None

    try:
        bgm_file_path = None
        if bg_music_target and os.path.exists(os.path.join(bgm_dir, bg_music_target)):
            bgm_file_path = os.path.join(bgm_dir, bg_music_target)
        else:
            bgm_file_path = get_random_bgm_file(bgm_dir)
        print(f"[BGM] Selected background music: {bgm_file_path}")
        if bgm_file_path and os.path.exists(bgm_file_path):
            try:
                raw_bgm = AudioFileClip(bgm_file_path)
                if raw_bgm.duration < audio_duration:
                    repeats = math.ceil(audio_duration / raw_bgm.duration)
                    bgm_clip = concatenate_audioclips([raw_bgm] * repeats).subclipped(0, audio_duration)
                else:
                    bgm_clip = raw_bgm.subclipped(0, audio_duration)

                bgm_clip = bgm_clip.with_effects([afx.MultiplyVolume(bgm_volume)])
                sound_effects.append(bgm_clip)
            except Exception as e:
                print(f"[WARNING] Could not load BGM file '{bgm_file_path}': {e}")

        num_segments = len(scenes)
        unique_video_files = get_unique_clips(target_assets_dir, num_segments)

        # Build Background Scenes
        for idx, scene in enumerate(scenes):
            start_time = scene.get("start", 0.0)
            transition_name = scene.get("transition", "zoom_dissolve")
            scene_transitions.append(transition_name)

            if idx < num_segments - 1:
                next_start = scenes[idx + 1].get("start", audio_duration)
                seg_duration = next_start - start_time
            else:
                seg_duration = audio_duration - start_time

            seg_duration = max(0.1, seg_duration)
            clip_duration = seg_duration + (transition_duration if idx < num_segments - 1 else 0.0)

            raw_clip = VideoFileClip(unique_video_files[idx])
            effect_type = random.choice(["zoom_in", "zoom_out", "pan_right", "pan_left"])
            
            processed_clip = loop_video_to_duration(raw_clip, clip_duration, crossfade_duration=0.4)
            processed_clip = apply_background_effect(
                processed_clip, 
                effect_type=effect_type, 
                duration=seg_duration
            )
            media_clips.append(processed_clip)

            # Optional Top-third Scene Heading Overlay
            heading_text = scene.get("heading", "")
            if heading_text:
                head_clip = (
                    create_heading_clip(heading_text, seg_duration)
                    .with_start(start_time)
                    .with_position(("center", "top"))
                )
                heading_clips.append(head_clip)

        # Assemble Background Timeline with Transitions
        bg_timeline = build_dynamic_transitioned_timeline(
            media_clips,
            scene_transitions,
            duration=transition_duration,
            final_duration=audio_duration
        )

        # Add Bottom Shadow Gradient for Subtitle Contrast
        shadow_overlay = create_enhanced_bottom_shadow_overlay(duration=audio_duration)

        # Generate Subtitle Overlay Layer
        subtitles_overlay = generate_caption_overlay(
            audio_path=audio_path,
            config=caption_config
        )

        # Composite All Layers
        composite_layers = [bg_timeline, shadow_overlay] + heading_clips
        if subtitles_overlay:
            composite_layers.append(subtitles_overlay)

        final_video = CompositeVideoClip(composite_layers, size=(1080, 1920))
        
        # Attach Mixed Audio
        final_audio = CompositeAudioClip(sound_effects)
        final_video = final_video.with_audio(final_audio)

        # Export Output Video
        clean_title = sanitize_filename(script_title)
        output_filename = f"{video_id}_{clean_title}.mp4"
        output_path = os.path.join(output_dir, output_filename)

        print(f"[EXPORTING] Rendering final clip to: {output_path}")
        final_video.write_videofile(
            output_path,
            fps=30,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4
        )

        return output_path

    finally:
        # Proper Memory Cleanup for MoviePy File Handles
        for clip in media_clips:
            try:
                clip.close()
            except Exception:
                pass
        
        if main_audio:
            main_audio.close()
        
        if bgm_clip:
            bgm_clip.close()

        if final_video:
            final_video.close()

if __name__ == "__main__":
    JSON_DATA =  {
        "id": "002",
        "script_title": "Work In Silence",
        "tag": "Gym_Training",
        "segments": 6,
        "bg_music": "dark_ambient_01.mp3",
        "pinned_comment": "Let your execution speak for you. What goal are you quietly working on right now?",
        "posted": False,
        "scenes": [
            {
                "text": "Work in total silence.",
                "heading_text": "SILENT EXECUTION",
                "transition": "zoom_dissolve"
            },
            {
                "text": "Never announce your moves before you make them.",
                "transition": "cross_dissolve"
            },
            {
                "text": "Let your results shatter the room while your mouth stays closed.",
                "transition": "cut_smooth"
            },
            {
                "text": "Weak men broadcast their plans to get temporary applause.",
                "transition": "zoom_dissolve"
            },
            {
                "text": "Strong men stay quiet until the execution is done.",
                "heading_text": "STAY QUIET",
                "transition": "cross_dissolve"
            },
            {
                "text": "Always remember to... keep your focus sharp and...",
                "transition": "cut_smooth"
            }
        ]
    }

    INPUT_AUDIO_DIR = os.path.join(BASE_DIR, "voiceovers")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

    output_path = process_script_item(
        script_data=JSON_DATA,
        audio_dir=INPUT_AUDIO_DIR,
        output_dir=OUTPUT_DIR,
        caption_config=CONFIG_STYLE_PUNCHY
    )

    print(f"Video rendered successfully: {output_path}")
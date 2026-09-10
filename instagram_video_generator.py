import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip, vfx

# -------------------------------
# 1. PREMIUM OVERLAY GENERATOR
# -------------------------------
def create_premium_overlay(text_content, author_name, logo_path, width, height):
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # DARK GRADIENT (BOTTOM FADE)
    gradient = Image.new('L', (1, height))
    for y in range(height):
        gradient.putpixel((0, y), int(255 * (y / height)))
    alpha = gradient.resize((width, height))
    black = Image.new("RGBA", (width, height), (0, 0, 0, 210))
    overlay = Image.composite(black, overlay, alpha)
    
    draw = ImageDraw.Draw(overlay)

    # FONTS 
    font_path = "fonts/dejavu-sans-bold.ttf"
    try:
        quote_font = ImageFont.truetype(font_path, 80) # Slightly smaller to ensure fit
        author_font = ImageFont.truetype(font_path, 40)
    except:
        quote_font = ImageFont.load_default()
        author_font = ImageFont.load_default()

    # HIGHLIGHT POWER WORDS
    power_words = ["sweat", "bleed", "war", "discipline"]
    def highlight(text):
        return " ".join([f"*{w}*" if re.sub(r'\W', '', w).lower() in power_words else w for w in text.split()])
    
    text_content = highlight(text_content)
    words = re.findall(r'\*\w+\*|\S+', text_content)

    # TEXT WRAP
    max_w = width * 0.80
    lines, current, cur_w = [], [], 0
    for word in words:
        clean = word.replace("*", "")
        w = draw.textlength(clean + " ", font=quote_font)
        if cur_w + w <= max_w:
            current.append(word)
            cur_w += w
        else:
            lines.append(current); current = [word]; cur_w = w
    lines.append(current)

    # CALC POSITIONING (Centered vertically)
    ascent, descent = quote_font.getmetrics()
    line_h = ascent + descent + 25
    author_spacer = 60
    total_h = (len(lines) * line_h) + author_spacer
    y = (height // 2) - (total_h // 2)

    # DRAW QUOTE
    for line in lines:
        line_w = sum(draw.textlength(w.replace("*","") + " ", font=quote_font) for w in line)
        x = (width - line_w) // 2
        for word in line:
            clean = word.replace("*","")
            color = (255,120,60) if "*" in word else (255,255,255)
            draw.text((x+3, y+3), clean, font=quote_font, fill=(0,0,0,180)) # Shadow
            draw.text((x, y), clean, font=quote_font, fill=color)
            x += draw.textlength(clean + " ", font=quote_font)
        y += line_h

    # DRAW AUTHOR (Ensuring it is visible)
    y += 30 
    author_text = f"— {author_name.upper()}"
    bbox = draw.textbbox((0,0), author_text, font=author_font)
    ax = (width - (bbox[2]-bbox[0])) // 2
    draw.text((ax, y), author_text, font=author_font, fill=(200,200,200))

    # LOGO (Top Right)
    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA").resize((110, 110), Image.Resampling.LANCZOS)
        lx, ly = width - 110 - 80, 80
        overlay.paste(logo, (lx, ly), logo)

    temp_name = "temp_premium_overlay.png"
    overlay.save(temp_name)
    return temp_name

# -------------------------------
# 2. VIDEO PROCESSING
# -------------------------------
def create_video_post(video_in, audio_in, quote, author, logo, video_out):
    print("--- Loading Video ---")
    clip = VideoFileClip(video_in)
    
    # Apply Slow Mo
    clip = clip.with_effects([vfx.MultiplySpeed(0.5)])
    
    # AUDIO CHECK: Skip if file is missing or not provided
    if audio_in and os.path.exists(audio_in):
        print(f"--- Applying Audio: {audio_in} ---")
        bg_audio = AudioFileClip(audio_in)
        if bg_audio.duration > clip.duration:
            bg_audio = bg_audio.subclip(0, clip.duration)
        clip = clip.with_audio(bg_audio)
    else:
        print("--- No Audio Provided or File Missing: Skipping Audio Step ---")

    # Instagram Crop (4:5)
    target_ratio = 1080 / 1350
    if (clip.w / clip.h) > target_ratio:
        clip = clip.cropped(x_center=clip.w/2, width=clip.h * target_ratio)
    else:
        clip = clip.cropped(y_center=clip.h/2, height=clip.w / target_ratio)
    
    clip = clip.resized(width=1080)
    W, H = clip.size

    # Generate Overlay
    overlay_path = create_premium_overlay(quote, author, logo, W, H)
    overlay_clip = (ImageClip(overlay_path)
                    .with_duration(clip.duration)
                    .with_position("center")
                    .with_effects([vfx.FadeIn(1.5), vfx.FadeOut(1.0)]))

    # Final Composite
    final = CompositeVideoClip([clip, overlay_clip])
    print(f"--- Rendering: {video_out} ---")
    final.write_videofile(video_out, fps=24, codec="libx264", audio_codec="aac")
    
    if os.path.exists(overlay_path): os.remove(overlay_path)
    print("Success!")

# -------------------------------
# 3. RUN
# -------------------------------
if __name__ == "__main__":
    create_video_post(
        video_in="sample_video.mp4",
        audio_in="music.mp3", # Set to None or "" to skip audio
        quote="The more you sweat in training the less you bleed in war",
        author="Sun Tzu",
        logo="profile.png",
        video_out="instagram_ready.mp4"
    )
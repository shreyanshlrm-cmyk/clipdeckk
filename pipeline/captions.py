"""
captions.py
Builds an .ass subtitle file styled like popular short-form captions (bold
white text, thick black outline, a few words on screen at a time, positioned
in the lower third) from whisper word-level timestamps. Burned in via
ffmpeg's `ass` filter (libass), so the result is a single flat mp4 - no
separate subtitle file needed at upload time.
"""

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,{fontsize},&H00FFFFFF,&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int(round((s - int(s)) * 100))
    return f"{h:d}:{m:02d}:{int(s):02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "").replace("}", "").strip()


def build_ass(words, clip_start: float, clip_end: float, out_path: str,
              video_w: int = 1080, video_h: int = 1920, words_per_group: int = 3):
    """
    words: list of {"start","end","word"} in the SOURCE video's absolute
    timeline. Timestamps are rebased to be relative to clip_start.
    """
    fontsize = max(48, int(video_h * 0.045))
    outline = max(3, int(fontsize * 0.08))
    shadow = 1
    marginv = int(video_h * 0.12)

    header = ASS_HEADER.format(w=video_w, h=video_h, fontsize=fontsize,
                                outline=outline, shadow=shadow, marginv=marginv)

    events = []
    group = []
    for w in words:
        rel_start = w["start"] - clip_start
        rel_end = w["end"] - clip_start
        if rel_end < 0 or rel_start > (clip_end - clip_start):
            continue
        group.append({"start": max(0.0, rel_start), "end": max(0.0, rel_end),
                       "word": w["word"]})
        ends_sentence = w["word"].strip().endswith((".", "!", "?"))
        if len(group) >= words_per_group or ends_sentence:
            events.append(group)
            group = []
    if group:
        events.append(group)

    lines = [header]
    for grp in events:
        if not grp:
            continue
        start = grp[0]["start"]
        end = grp[-1]["end"] + 0.05
        text = _escape(" ".join(g["word"] for g in grp).strip().upper())
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Caption,,0,0,0,,{text}\n"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    return out_path

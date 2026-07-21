"""
crop.py
Works out a 9:16 crop window for a clip. Samples a handful of frames, runs
OpenCV's built-in Haar-cascade face detector (ships with opencv-python, no
extra download/model needed) and centers the crop on the average face
position. Falls back to a plain center crop if no face is found - e.g. for
gameplay, screen-recordings, or slideshow-style content.
"""
import cv2
import numpy as np

_face_cascade = None


def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(path)
    return _face_cascade


def compute_crop_window(video_path: str, start: float, end: float, samples: int = 8):
    """
    Returns (crop_w, crop_h, crop_x, crop_y, src_w, src_h) in source-pixel
    coordinates, describing a 9:16 window to feed to ffmpeg's crop filter.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for crop analysis: {video_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    cascade = _get_cascade()
    face_centers = []  # (x_center, weight)

    duration = max(end - start, 0.1)
    for i in range(samples):
        t = start + duration * (i + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5,
                                          minSize=(int(src_h * 0.08), int(src_h * 0.08)))
        for (x, y, w, h) in faces:
            face_centers.append((x + w / 2.0, w * h))

    cap.release()

    target_ratio = 9.0 / 16.0  # width / height for the crop window
    if src_w / src_h <= target_ratio:
        # source is already narrower than or equal to 9:16 -> use full width
        crop_w = src_w
    else:
        crop_w = int(round(src_h * target_ratio))
    crop_h = src_h

    if face_centers:
        weighted_x = sum(c * w for c, w in face_centers) / sum(w for _, w in face_centers)
    else:
        weighted_x = src_w / 2.0

    crop_x = int(round(weighted_x - crop_w / 2.0))
    crop_x = max(0, min(crop_x, src_w - crop_w))
    crop_y = 0  # full height; horizontal recenter is what matters for talking-head content

    return {
        "crop_w": crop_w, "crop_h": crop_h, "crop_x": crop_x, "crop_y": crop_y,
        "src_w": src_w, "src_h": src_h, "faces_found": len(face_centers) > 0,
    }

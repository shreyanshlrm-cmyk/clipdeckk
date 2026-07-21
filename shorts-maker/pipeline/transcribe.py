"""
transcribe.py
Local, offline speech-to-text using faster-whisper (CTranslate2 build of
OpenAI Whisper). Runs entirely on your machine - no API key, no per-minute
billing. Uses the GPU automatically if available, otherwise CPU.
"""
from faster_whisper import WhisperModel

_MODEL_CACHE = {}


def get_model(model_size: str = "small") -> WhisperModel:
    if model_size in _MODEL_CACHE:
        return _MODEL_CACHE[model_size]

    model = None
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

    _MODEL_CACHE[model_size] = model
    return model


def transcribe(audio_path: str, model_size: str = "small", language: str | None = None):
    """
    Returns a list of segments:
      {"start": float, "end": float, "text": str,
       "words": [{"start": float, "end": float, "word": str}, ...]}
    """
    model = get_model(model_size)
    segments_iter, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        language=language,
    )

    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({"start": w.start, "end": w.end, "word": w.word})
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })
    return segments, info.duration

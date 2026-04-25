"""Gradium speech-to-text transcriber for pre-recorded audio files."""

import base64
import json
import logging
import os
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets.sync.client

logger = logging.getLogger(__name__)

_GRADIUM_WS_URL = "wss://api.gradium.ai/api/speech/asr"
_TARGET_SAMPLE_RATE = 24_000
_CHUNK_SAMPLES = 1920  # 80 ms at 24 kHz, as required by Gradium


def _load_as_pcm(file_path: Path) -> bytes:
    """Read an audio file and return 24 kHz mono 16-bit little-endian PCM bytes."""
    data, samplerate = sf.read(str(file_path), dtype="float32", always_2d=True)

    mono = data.mean(axis=1)

    if samplerate != _TARGET_SAMPLE_RATE:
        from scipy.signal import resample_poly

        g = gcd(_TARGET_SAMPLE_RATE, int(samplerate))
        mono = resample_poly(mono, _TARGET_SAMPLE_RATE // g, int(samplerate) // g)

    samples = np.clip(mono * 32767, -32768, 32767).astype(np.int16)
    return samples.tobytes()


def transcribe(file_path: Path) -> str:
    """Transcribe an audio file via the Gradium STT WebSocket API.

    Converts the file to 24 kHz mono PCM, streams it in 80 ms chunks, and
    returns the concatenated transcript.
    """
    api_key = os.environ.get("GRADIUM_API_KEY", "")
    if not api_key:
        raise ValueError("GRADIUM_API_KEY environment variable is not set")

    logger.info("Loading audio: %s", file_path)
    pcm = _load_as_pcm(file_path)
    logger.info("Audio loaded: %.1f s at %d Hz", len(pcm) / 2 / _TARGET_SAMPLE_RATE, _TARGET_SAMPLE_RATE)

    texts: list[str] = []
    chunk_size = _CHUNK_SAMPLES * 2  # bytes (2 bytes per int16 sample)

    with websockets.sync.client.connect(
        _GRADIUM_WS_URL,
        additional_headers={"x-api-key": api_key},
    ) as ws:
        ws.send(json.dumps({"type": "setup", "model_name": "default", "input_format": "pcm"}))

        ready = json.loads(ws.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(f"Unexpected setup response from Gradium: {ready}")

        for offset in range(0, len(pcm), chunk_size):
            chunk = pcm[offset: offset + chunk_size]
            ws.send(json.dumps({"type": "audio", "audio": base64.b64encode(chunk).decode()}))

        ws.send(json.dumps({"type": "flush", "flush_id": "eos"}))
        ws.send(json.dumps({"type": "end_of_stream"}))

        for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "text":
                texts.append(msg["text"])
            elif t == "error":
                raise RuntimeError(f"Gradium STT error ({msg.get('code')}): {msg.get('message')}")
            elif t == "end_of_stream":
                break
            # "step", "flushed" — ignored

    transcript = " ".join(texts).strip()
    logger.info("Transcription complete: %d chars", len(transcript))
    return transcript

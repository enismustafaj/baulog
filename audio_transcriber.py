"""Gradium speech-to-text transcriber for pre-recorded audio files."""

import base64
import json
import logging
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets.sync.client
from websockets.exceptions import ConnectionClosed

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

    Protocol (per Gradium docs):
      1. Send setup JSON with model_name and input_format
      2. Receive ready confirmation
      3. Stream audio as base64-encoded JSON chunks
      4. Send end_of_stream
      5. Collect text responses until server closes the connection
    """
    from agents.config import GRADIUM_API_KEY
    if not GRADIUM_API_KEY:
        raise ValueError("GRADIUM_API_KEY environment variable is not set")

    logger.info("Loading audio: %s", file_path)
    pcm = _load_as_pcm(file_path)
    logger.info(
        "Audio loaded: %.1f s  (%d bytes PCM)",
        len(pcm) / 2 / _TARGET_SAMPLE_RATE,
        len(pcm),
    )

    texts: list[str] = []
    chunk_size = _CHUNK_SAMPLES * 2  # 2 bytes per int16 sample

    with websockets.sync.client.connect(
        _GRADIUM_WS_URL,
        additional_headers={"x-api-key": GRADIUM_API_KEY},
    ) as ws:

        # 1. Handshake
        ws.send(json.dumps({
            "type": "setup",
            "model_name": "default",
            "input_format": "pcm",
        }))

        ready = json.loads(ws.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(f"Unexpected setup response from Gradium: {ready}")
        logger.info("Gradium ready: %s", ready)

        # 2. Stream audio as base64-encoded JSON chunks
        for offset in range(0, len(pcm), chunk_size):
            chunk = pcm[offset: offset + chunk_size]
            ws.send(json.dumps({
                "type": "audio",
                "audio": base64.b64encode(chunk).decode(),
            }))

        # 3. Signal end of audio
        ws.send(json.dumps({"type": "end_of_stream"}))

        # 4. Collect transcription results.
        # The server closes the connection once it has flushed all results,
        # so ConnectionClosed is the normal exit condition.
        try:
            for raw in ws:
                if isinstance(raw, bytes):
                    continue  # ignore any binary echo frames
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "text":
                    text = msg.get("text", "").strip()
                    if text:
                        texts.append(text)
                elif t == "error":
                    raise RuntimeError(
                        f"Gradium STT error ({msg.get('code')}): {msg.get('message')}"
                    )
                elif t == "end_of_stream":
                    break
                # "vad", "end_text", "flushed", "step" — ignored
        except ConnectionClosed:
            # Server closed the connection after delivering all results — normal.
            pass

    transcript = " ".join(texts).strip()
    logger.info("Transcription complete: %d chars", len(transcript))
    return transcript

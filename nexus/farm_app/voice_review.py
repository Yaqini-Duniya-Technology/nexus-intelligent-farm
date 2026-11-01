import io
import threading
import time
from pathlib import Path
from urllib.parse import urlparse


MODEL = "NCAIR1/Hausa-ASR"
REVISION = "e635b9eda29060c6114c8f4d8b2d903f5c83a44a"

LOCK = threading.Lock()
ENGINE = None
HTML = Path(__file__).with_name("voice_review.html")


def transcribe(raw):
    global ENGINE

    import numpy as np
    import soundfile as sf

    stream = io.BytesIO(raw)
    info = sf.info(stream)

    if info.format != "WAV" or not 0 < info.duration <= 30:
        raise ValueError(
            "Upload a WAV recording between 0 and 30 seconds."
        )

    if info.samplerate != 16000 or info.channels != 1:
        raise ValueError(
            "Use 16 kHz mono WAV for this first pilot."
        )

    stream.seek(0)
    audio, _ = sf.read(stream, dtype="float32")

    if (
        not np.isfinite(audio).all()
        or np.max(np.abs(audio)) < 0.00001
    ):
        raise ValueError(
            "Recording is invalid or effectively silent."
        )

    if not LOCK.acquire(blocking=False):
        raise ValueError(
            "Another transcription is running. "
            "Try again after it finishes."
        )

    try:
        import torch
        from transformers import (
            AutoProcessor,
            AutoModelForSpeechSeq2Seq,
        )

        torch.set_num_threads(2)
        started = time.perf_counter()

        if ENGINE is None:
            print("Loading Hausa ASR on CPU...", flush=True)

            processor = AutoProcessor.from_pretrained(
                MODEL,
                revision=REVISION,
            )

            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                MODEL,
                revision=REVISION,
                dtype=torch.float32,
            ).to("cpu")

            model.eval()
            ENGINE = (processor, model)

        processor, model = ENGINE
        load_seconds = time.perf_counter() - started

        inputs = processor(
            audio,
            sampling_rate=16000,
            return_tensors="pt",
            return_attention_mask=True,
        )

        started = time.perf_counter()

        with torch.inference_mode():
            tokens = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )

        text = processor.batch_decode(
            tokens,
            skip_special_tokens=True,
        )[0].strip()

        return {
            "original_transcript": text,
            "model": MODEL,
            "revision": REVISION,
            "duration_seconds": round(info.duration, 2),
            "load_seconds": round(load_seconds, 2),
            "inference_seconds": round(
                time.perf_counter() - started,
                2,
            ),
            "confidence": None,
        }

    finally:
        LOCK.release()


def make_handler(base):
    class Handler(base):
        def do_GET(self):
            if urlparse(self.path).path == "/voice":
                self.respond(
                    200,
                    HTML.read_bytes(),
                    "text/html; charset=utf-8",
                )
            else:
                super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path != "/api/voice-transcribe":
                return super().do_POST()

            origin = self.headers.get("Origin")
            expected_origin = (
                "http://" + self.headers.get("Host", "")
            )

            if origin and origin != expected_origin:
                return self.respond(
                    403,
                    {"error": "Cross-origin request rejected"},
                )

            try:
                size = int(
                    self.headers.get("Content-Length", "0")
                )

                if not 0 < size <= 2000000:
                    raise ValueError(
                        "Upload a WAV file no larger than 2 MB."
                    )

                raw = self.rfile.read(size)

                if len(raw) != size:
                    raise ValueError("Incomplete upload")

                result = transcribe(raw)

            except ValueError as error:
                return self.respond(
                    400,
                    {"error": str(error)},
                )

            except Exception:
                import traceback

                traceback.print_exc()

                return self.respond(
                    500,
                    {
                        "error": (
                            "Transcription failed. Read the "
                            "server terminal for details."
                        )
                    },
                )

            self.respond(200, result)

    return Handler


def main():
    from nexus.farm_app import server, decision_cycles

    previous = server.make_handler

    server.make_handler = (
        lambda store: make_handler(previous(store))
    )

    print(
        "NEXUS voice review: /voice — "
        "no farm records are saved here.",
        flush=True,
    )

    decision_cycles.main()


if __name__ == "__main__":
    main()
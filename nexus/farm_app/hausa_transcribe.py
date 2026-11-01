import argparse
import time
from pathlib import Path


MODEL = "NCAIR1/Hausa-ASR"
REVISION = "e635b9eda29060c6114c8f4d8b2d903f5c83a44a"


def main():
    parser = argparse.ArgumentParser(
        description="NEXUS synthetic Hausa audio test"
    )
    parser.add_argument("audio", type=Path)
    args = parser.parse_args()

    if not args.audio.is_file():
        parser.error(f"Audio file not found: {args.audio}")

    print("Synthetic test audio — not farm evidence.", flush=True)
    print("Loading dependencies...", flush=True)

    import numpy as np
    import soundfile as sf
    import librosa
    import torch
    from transformers import (
        AutoProcessor,
        AutoModelForSpeechSeq2Seq,
    )

    info = sf.info(str(args.audio))

    if not 0 < info.duration <= 30:
        parser.error(
            "Use a nonempty recording no longer than 30 seconds."
        )

    audio, sample_rate = sf.read(
        str(args.audio),
        dtype="float32",
        always_2d=True,
    )
    audio = audio.mean(axis=1)

    if (
        not np.isfinite(audio).all()
        or np.max(np.abs(audio)) < 0.00001
    ):
        parser.error(
            "Audio contains invalid values or is effectively silent."
        )

    if sample_rate != 16000:
        audio = librosa.resample(
            audio,
            orig_sr=sample_rate,
            target_sr=16000,
        )

    torch.set_num_threads(2)

    print(
        f"Audio duration: {info.duration:.2f} seconds",
        flush=True,
    )
    print(
        "Loading Hausa ASR on CPU. "
        "First run downloads the model...",
        flush=True,
    )

    started = time.perf_counter()

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

    print(
        f"Model loaded in "
        f"{time.perf_counter() - started:.1f} seconds.",
        flush=True,
    )

    inputs = processor(
        audio,
        sampling_rate=16000,
        return_tensors="pt",
        return_attention_mask=True,
    )

    print(
        "Transcribing... CPU inference may take several minutes.",
        flush=True,
    )

    started = time.perf_counter()

    with torch.inference_mode():
        tokens = model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=False,
        )

    transcript = processor.batch_decode(
        tokens,
        skip_special_tokens=True,
    )[0].strip()

    print(
        f"Inference time: "
        f"{time.perf_counter() - started:.1f} seconds",
        flush=True,
    )
    print(
        "\nTRANSCRIPT — review against the recording:",
        flush=True,
    )
    print(transcript or "[No text returned]", flush=True)

    print(
        "\nNo farm record was saved. "
        "No confidence score is calculated."
    )
    print(
        "Awarri Technologies and the Federal Government of "
        "Nigeria, developers of N-ATLaS (Hausa-ASR)."
    )


if __name__ == "__main__":
    main()
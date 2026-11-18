"""Runs INSIDE the separate Parler environment (~/parler), never imported by the main system (Indic Parler-TTS needs
transformers 4.46.1, which would break our other voices).

Usage: python parler_worker.py jobs.json
jobs.json = {"description": "...", "threads": 8, "seed": 7,
             "lines": [{"text": "...", "out": "...wav"}, ...]}
One model load per video; every line uses the same speaker description and seed, so the voice stays the same.
Lines already on disk are skipped (a crashed batch resumes). Prints "DONE <n>"."""
import json
import os
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer

MODEL = "ai4bharat/indic-parler-tts"


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    torch.set_num_threads(int(job.get("threads", 8)))
    token = os.environ.get("HF_TOKEN") or None
    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL, token=token).to("cpu").eval()
    tok = AutoTokenizer.from_pretrained(MODEL, token=token)
    dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path, token=token)
    desc = dtok(job["description"], return_tensors="pt")
    done = 0
    for k, ln in enumerate(job["lines"]):
        out = Path(ln["out"])
        if out.exists() and out.stat().st_size > 1000:
            done += 1
            continue
        t0 = time.time()
        torch.manual_seed(int(job.get("seed", 7)))
        prompt = tok(ln["text"], return_tensors="pt")
        with torch.inference_mode():
            gen = model.generate(input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                                 prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask)
        audio = gen.cpu().numpy().squeeze()
        tmp = out.with_suffix(".part.wav")
        sf.write(str(tmp), audio, model.config.sampling_rate)
        tmp.replace(out)
        done += 1
        print(f"LINE {k + 1}/{len(job['lines'])} {time.time() - t0:.0f}s {len(audio) / model.config.sampling_rate:.1f}s audio",
              flush=True)
    print(f"DONE {done}", flush=True)


if __name__ == "__main__":
    main()

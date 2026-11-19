"""HookHouse GPU batch: runs as a PRIVATE Kaggle notebook (free T4 GPU, owner's account HookHouseMedia).

Input : /kaggle/input/hookhouse-gpu-jobs/gpu_jobs.json  -> {"images": [{"key": "...", "prompt": "...", "w": 768, "h": 1344}]}
Output: /kaggle/working/out/<key>.jpg   (FLUX.1-schnell, Apache-2.0; 4-bit weights so it fits a 16 GB T4)
The cloud downloads the outputs (kaggle kernels output) and the video maker finds each picture by its key.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.32", "transformers", "accelerate",
                "bitsandbytes", "sentencepiece", "protobuf"], check=False)

import torch  # noqa: E402
from diffusers import BitsAndBytesConfig as DiffusersBnb  # noqa: E402
from diffusers import FluxPipeline, FluxTransformer2DModel  # noqa: E402
from transformers import BitsAndBytesConfig as TransformersBnb  # noqa: E402
from transformers import T5EncoderModel  # noqa: E402

try:                                   # FLUX.1-schnell is gated on Hugging Face: the owner's key, kept as a Kaggle
    from kaggle_secrets import UserSecretsClient          # notebook secret (Add-ons > Secrets > HF_TOKEN), never in code
    import os
    os.environ["HF_TOKEN"] = UserSecretsClient().get_secret("HF_TOKEN")
except Exception as e:  # noqa: BLE001
    print("no HF_TOKEN secret attached:", type(e).__name__, flush=True)

JOBS = next(iter(sorted(Path("/kaggle/input").rglob("gpu_jobs.json"))), None)
OUT = Path("/kaggle/working/out")
OUT.mkdir(parents=True, exist_ok=True)
MODEL = "black-forest-labs/FLUX.1-schnell"
DTYPE = torch.float16


def main() -> None:
    jobs = json.loads(JOBS.read_text(encoding="utf-8")) if JOBS else {"images": []}
    todo = [j for j in jobs.get("images", []) if not (OUT / f"{j['key']}.jpg").exists()]
    print(f"{len(todo)} pictures to draw on {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}",
          flush=True)
    if not todo:
        return
    t0 = time.time()
    transformer = FluxTransformer2DModel.from_pretrained(
        MODEL, subfolder="transformer", torch_dtype=DTYPE,
        quantization_config=DiffusersBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=DTYPE))
    text2 = T5EncoderModel.from_pretrained(
        MODEL, subfolder="text_encoder_2", torch_dtype=DTYPE,
        quantization_config=TransformersBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=DTYPE))
    pipe = FluxPipeline.from_pretrained(MODEL, transformer=transformer, text_encoder_2=text2, torch_dtype=DTYPE)
    pipe.enable_model_cpu_offload()
    print(f"model loaded in {time.time() - t0:.0f} s", flush=True)
    for j in todo:
        t1 = time.time()
        img = pipe(j["prompt"], width=int(j.get("w", 768)), height=int(j.get("h", 1344)), num_inference_steps=4,
                   guidance_scale=0.0, max_sequence_length=256,
                   generator=torch.Generator("cpu").manual_seed(int(j.get("seed", 0)))).images[0]
        img.convert("RGB").save(OUT / f"{j['key']}.jpg", quality=92)
        print(f"picture {j['key']} in {time.time() - t1:.0f} s", flush=True)
    (OUT / "done.json").write_text(json.dumps({"count": len(todo), "seconds": round(time.time() - t0)}), encoding="utf-8")


main()

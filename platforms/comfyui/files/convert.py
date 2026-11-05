"""Images between ComfyUI tensors ([batch, height, width, channels], floats 0 to 1) and file bytes."""

from __future__ import annotations

import logging
from io import BytesIO

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("steadyrouter")


def to_tensor(data: bytes) -> torch.Tensor:
    """One image file as a batch of one, in RGB like most ComfyUI nodes expect."""
    with Image.open(BytesIO(data)) as image:
        array = np.array(image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array)[None,]


def to_batch(files: list[bytes]) -> torch.Tensor:
    """Several image files as one batch. A batch needs one size, so images of another size are left out."""
    tensors = [to_tensor(f) for f in files]
    kept = [t for t in tensors if t.shape == tensors[0].shape]
    if len(kept) < len(tensors):
        log.warning("SteadyRouter: the model returned images of different sizes; kept the %d of size %dx%d.",
                    len(kept), tensors[0].shape[2], tensors[0].shape[1])
    return torch.cat(kept)


def to_png(image: torch.Tensor) -> bytes:
    """One image of a batch ([height, width, channels]) as PNG bytes."""
    array = (image.detach().cpu().clamp(0, 1).numpy() * 255).round().astype(np.uint8)
    if array.ndim == 3 and array.shape[-1] == 1:
        array = array[..., 0]
    out = BytesIO()
    Image.fromarray(array).save(out, format="PNG")
    return out.getvalue()


def batch_to_pngs(images: torch.Tensor | None, limit: int) -> list[bytes]:
    if images is None:
        return []
    if len(images) > limit:
        raise ValueError(f"At most {limit} reference images are accepted; this batch has {len(images)}.")
    return [to_png(image) for image in images]

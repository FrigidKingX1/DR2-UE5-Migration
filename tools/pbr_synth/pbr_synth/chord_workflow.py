"""CHORD workflow graph construction (ComfyUI API format).

The graph mirrors the official ``chord_image_to_material`` example:

    LoadImage -> ChordLoadModel -> ChordMaterialEstimation
                                     |-> basecolor (SaveImage)
                                     |-> normal    (SaveImage)
                                     |-> roughness (SaveImage)
                                     |-> metalness (SaveImage)
                                     `-> ChordNormalToHeight -> height (SaveImage)

Node ids are stable constants so the runner can fetch each output by id.
``ChordMaterialEstimation`` resizes its input to 1024x1024 internally and
resizes the predicted maps back to the input resolution, so no tiling is
needed on our side for square (or near-square) texture sets.
"""

from __future__ import annotations

CKPT_NAME = "chord_v1.safetensors"

# Stable node ids used by the runner to locate outputs.
NODE_MODEL = "10"
NODE_ESTIMATE = "20"
NODE_HEIGHT = "30"
NODE_BASECOLOR = "41"
NODE_NORMAL = "42"
NODE_ROUGHNESS = "43"
NODE_METALNESS = "44"
NODE_HEIGHT_SAVE = "45"

OUTPUT_NODES = {
    "basecolor": NODE_BASECOLOR,
    "normal": NODE_NORMAL,
    "roughness": NODE_ROUGHNESS,
    "metalness": NODE_METALNESS,
    "height": NODE_HEIGHT_SAVE,
}


def build_image_to_material(staged_image_name: str,
                            ckpt_name: str = CKPT_NAME,
                            prefix: str = "chord") -> dict:
    """API-format graph: staged input image -> five PBR map outputs."""
    est = "3"  # output slot: 0 basecolor, 1 normal, 2 roughness, 3 metalness
    return {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": staged_image_name, "upload": "image"}},
        "2": {"class_type": "ChordLoadModel",
              "inputs": {"ckpt_name": ckpt_name}},
        "3": {"class_type": "ChordMaterialEstimation",
              "inputs": {"chord_model": ["2", 0], "image": ["1", 0]}},
        NODE_HEIGHT: {"class_type": "ChordNormalToHeight",
                      "inputs": {"normal": ["3", 1]}},
        NODE_BASECOLOR: {"class_type": "SaveImage",
                         "inputs": {"images": ["3", 0],
                                    "filename_prefix": f"{prefix}/basecolor"}},
        NODE_NORMAL: {"class_type": "SaveImage",
                      "inputs": {"images": ["3", 1],
                                 "filename_prefix": f"{prefix}/normal"}},
        NODE_ROUGHNESS: {"class_type": "SaveImage",
                         "inputs": {"images": ["3", 2],
                                    "filename_prefix": f"{prefix}/roughness"}},
        NODE_METALNESS: {"class_type": "SaveImage",
                         "inputs": {"images": ["3", 3],
                                    "filename_prefix": f"{prefix}/metalness"}},
        NODE_HEIGHT_SAVE: {"class_type": "SaveImage",
                           "inputs": {"images": [NODE_HEIGHT, 0],
                                      "filename_prefix": f"{prefix}/height"}},
    }

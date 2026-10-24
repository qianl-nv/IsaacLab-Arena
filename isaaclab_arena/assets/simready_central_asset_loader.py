# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Download Central asset packages and create validated PhysX USD wrappers."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from isaaclab_arena.assets.simready_asset_preparation import PreparedSimReadyAsset, prepare_simready_asset
from isaaclab_arena.assets.simready_constants import SIMREADY_PHYSICS_VARIANTS


def _parse_central_asset_url(url: str) -> tuple[str, str, str, str]:
    """Parse a revision-pinned Central dataset URL and its asset package folder."""
    match = re.fullmatch(
        r"(?:hf|https)://huggingface\.co/datasets/([^/]+/[^/]+)/(?:resolve|blob)/([0-9a-f]{40})/(.+)", url
    )
    assert match, "expected a pinned Hugging Face dataset URL"
    repo_id, revision, filename = match.groups()
    path = PurePosixPath(filename)
    assert not path.is_absolute() and ".." not in path.parts, "invalid asset path"
    assert not any(char in filename for char in "*?[]\\"), "invalid asset path"
    assert path.suffix in (".usd", ".usda", ".usdc", ".usdz"), "expected USD asset"
    # Central packages place the entrypoint in <asset>/simready_usd/. Fetch its
    # siblings too (physics layers, materials, textures), never the entire dataset.
    assert "simready_usd" in path.parts, "unsupported Central package layout"
    folder = PurePosixPath(*path.parts[: path.parts.index("simready_usd")])
    assert str(folder) != ".", "asset must have a package folder"
    return repo_id, revision, filename, str(folder)


def _download_central_asset_package_to_cache(url: str) -> str:
    """Download the pinned asset package and return its cached USD entrypoint."""
    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.hf_api import RepoFile

    repo_id, revision, filename, folder = _parse_central_asset_url(url)
    # List only this package: a dataset-wide snapshot scan is expensive for large libraries.
    files = [
        entry.path
        for entry in HfApi().list_repo_tree(
            repo_id=repo_id, repo_type="dataset", revision=revision, path_in_repo=folder, recursive=True
        )
        if isinstance(entry, RepoFile)
    ]
    assert filename in files, "asset package is missing its USD entrypoint"

    def download_file(path: str) -> str:
        return hf_hub_download(repo_id=repo_id, repo_type="dataset", revision=revision, filename=path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        cached_paths = dict(zip(files, executor.map(download_file, files), strict=True))
    return cached_paths[filename]


def download_and_wrap_central_asset(url: str) -> PreparedSimReadyAsset:
    """Download a Central package and return its validated rigid or articulated wrapper."""
    asset_path = _download_central_asset_package_to_cache(url)
    # TODO(xinjieyao, 20261022): Support Newton.
    variants = {**SIMREADY_PHYSICS_VARIANTS, "PhysX": "Enabled"}
    return prepare_simready_asset(
        asset_path,
        cache_key=url,
        cache_directory_name="simready-central",
        variants=variants,
    )

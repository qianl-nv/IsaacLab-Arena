# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Scene generator orchestrator — ties all pieces together.

Pipeline:
    scene_themes → asset_manager → llm_agent → predicate_translator → adaptive_placer → Arena Scene

Usage:
    # Single scene
    gen = SceneGenerator()
    scene = gen.generate_scene("kitchen counter with fruits", max_objects=8)

    # Batch generation (automatic prompts)
    scenes = gen.generate_batch(num_scenes=100)
"""

from __future__ import annotations

import json
from pathlib import Path

from isaaclab_arena.relations.relations import IsAnchor
from isaaclab_arena.scene.scene import Scene
from isaaclab_arena.scene_gen.adaptive_placer import place_objects_adaptive
from isaaclab_arena.scene_gen.arena_asset_manager import ArenaAssetManager
from isaaclab_arena.scene_gen.feedback_system import FeedbackSystem
from isaaclab_arena.scene_gen.llm_agent import LLMAgent
from isaaclab_arena.scene_gen.predicate_translator import translate_predicates
from isaaclab_arena.scene_gen.scene_themes import generate_scene_prompts
from isaaclab_arena.utils.pose import Pose


class SceneGenerator:
    """Orchestrates LLM-driven scene generation for Arena.

    Combines:
    - ArenaAssetManager: 719 objects with dims
    - LLMAgent: Claude Opus 4.6 for predicate generation
    - RoboLab spatial solver: collision-free placement
    - Arena Scene: native output for env gen
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        output_dir: str | None = None,
        max_retries: int = 3,
        table_top_z: float = 0.0,
    ):
        """Initialize the scene generator.

        All LLM connection parameters (key, model, URL) cascade through
        ``LLMAgent``: explicit arg → env var → built-in default.  See
        :class:`~isaaclab_arena.scene_gen.llm_agent.LLMAgent` for env var names.

        Args:
            api_key: API key for LLM. Reads ``NV_API_KEY`` env var if None.
            model: LLM model identifier.  Reads ``SCENE_GEN_MODEL`` if None.
            base_url: LLM API base URL.  Reads ``SCENE_GEN_BASE_URL`` if None.
            output_dir: Directory to save generated scene metadata.
            max_retries: Max LLM retries per scene on failure.
            table_top_z: Z height of the table surface (meters).
        """
        self.asset_manager = ArenaAssetManager()
        self.llm_agent = LLMAgent(api_key=api_key, model=model, base_url=base_url)
        self.feedback_system = FeedbackSystem()
        self.max_retries = max_retries
        self.table_top_z = table_top_z

        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_scene(
        self,
        prompt: str,
        max_objects: int = 10,
        table_name: str | None = None,
        scene_name: str | None = None,
        has_articulated: bool = False,
    ) -> Scene | None:
        """Generate a single scene from a natural language prompt.

        Args:
            prompt: Natural language scene description.
            max_objects: Maximum number of objects to place.
            table_name: Which table to use. Random if None.
            scene_name: Optional name for metadata saving.
            has_articulated: If True, ensures articulated objects are available.

        Returns:
            Arena Scene object, or None if generation failed.
        """
        from isaaclab_arena.assets.asset_registry import AssetRegistry

        registry = AssetRegistry()

        # 1. Select table
        if table_name is None:
            table_name = self.asset_manager.get_random_table()
        table_info = self.asset_manager.get_table_info(table_name)
        table_bounds = self.asset_manager.get_table_bounds(table_name)

        print(f"[SceneGen] Table: {table_name}")
        print(f"[SceneGen] Prompt: {prompt}")
        print(f"[SceneGen] Max objects: {max_objects}")

        # 2. Create table asset as anchor
        # Match RoboLab's base_empty.usda: table at (0.547, 0, -0.35)
        # The table USD has its top surface ~0.35m above its origin
        # So table at Z=-0.35 puts the surface at Z≈0.0
        table = registry.get_asset_by_name(table_info["registry_name"])()
        table.set_initial_pose(
            Pose(
                position_xyz=(0.547, 0.0, -0.35),
                rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        )
        table.add_relation(IsAnchor())

        # 3. Select candidate objects
        candidates = self.asset_manager.get_objects_for_scene(max_objects)
        llm_catalog = self.asset_manager.get_catalog_for_llm(candidates)

        # 4. Build articulated objects info for LLM
        artic_objects = {}
        for name in candidates:
            if self.asset_manager.needs_fixed_orientation(name):
                artic_objects[name] = self.asset_manager.get_affordances(name)

        # 5. LLM generation with retry loop
        feedback = None
        scene = None

        for attempt in range(self.max_retries):
            if attempt > 0:
                print(f"[SceneGen] Retry {attempt}/{self.max_retries - 1}")

            try:
                # Call LLM
                self.llm_agent.reset_conversation()
                llm_result = self.llm_agent.generate_predicates(
                    prompt=prompt,
                    object_catalog=llm_catalog,
                    max_objects=max_objects,
                    feedback=feedback,
                    preselected_objects=candidates,
                    articulated_objects=artic_objects if artic_objects else None,
                )

                num_objects = len(llm_result.get("objects", []))
                num_predicates = len(llm_result.get("predicates", []))
                print(f"[SceneGen] LLM returned {num_objects} objects, {num_predicates} predicates")

                # Validate minimum objects
                if num_objects < max(2, max_objects * 0.5):
                    feedback = self.feedback_system.generate_solver_feedback(
                        False, f"Too few objects: got {num_objects}, need at least {max(2, int(max_objects * 0.6))}"
                    )
                    continue

                # 6. Translate predicates → Arena Objects with Relations
                objects = translate_predicates(llm_result, table, self.asset_manager)
                print(f"[SceneGen] Translated {len(objects)} objects")

                # 7. Place objects (spatial solver + stacking + containment)
                result = place_objects_adaptive(
                    objects,
                    table,
                    self.asset_manager,
                    table_bounds=table_bounds,
                    table_top_z=self.table_top_z,
                    verbose=True,
                )

                if not result.success:
                    feedback = self.feedback_system.generate_solver_feedback(
                        False, "Collision resolution failed — objects overlap"
                    )
                    continue

                # 8. Build Arena Scene
                scene = Scene()
                scene.add_asset(table)
                for obj in objects:
                    scene.add_asset(obj)

                # Add ground plane and light
                try:
                    ground = registry.get_asset_by_name("ground_plane")()
                    ground.set_initial_pose(Pose(position_xyz=(0.0, 0.0, -0.35)))
                    scene.add_asset(ground)
                except Exception:
                    pass

                try:
                    import isaaclab.sim as sim_utils

                    light_cfg = sim_utils.DomeLightCfg(color=(0.75, 0.75, 0.75), intensity=1500.0)
                    light = registry.get_asset_by_name("light")(spawner_cfg=light_cfg)
                    scene.add_asset(light)
                except Exception:
                    pass

                print(f"[SceneGen] Scene built with {len(scene.assets)} assets")

                # 9. Save metadata
                if self.output_dir and scene_name:
                    self._save_metadata(scene_name, prompt, table_name, llm_result, result.positions)

                return scene

            except Exception as e:
                print(f"[SceneGen] Error: {e}")
                feedback = f"Generation error: {e}. Try again with simpler placement."
                continue

        print(f"[SceneGen] Failed after {self.max_retries} attempts")
        return None

    def generate_batch(
        self,
        num_easy: int = 15,
        num_medium: int = 70,
        num_hard: int = 15,
        appliance_ratio: float = 0.15,
    ) -> list[Scene | None]:
        """Generate a batch of scenes using automated prompts.

        Args:
            num_easy: Number of easy scenes (2-5 objects).
            num_medium: Number of medium scenes (7-10 objects).
            num_hard: Number of hard scenes (12-20 objects).
            appliance_ratio: Fraction of scenes with articulated objects.

        Returns:
            List of Arena Scene objects (None for failed scenes).
        """
        scene_configs = generate_scene_prompts(
            num_easy=num_easy,
            num_medium=num_medium,
            num_hard=num_hard,
            appliance_ratio=appliance_ratio,
        )

        total = len(scene_configs)
        scenes = []
        success_count = 0

        for i, config in enumerate(scene_configs, 1):
            print(f"\n{'=' * 60}")
            print(f"[{i}/{total}] {config['name']} ({config['difficulty']})")
            print(f"{'=' * 60}")

            scene = self.generate_scene(
                prompt=config["prompt"],
                max_objects=config["max_objects"],
                scene_name=config["name"],
                has_articulated=config.get("has_articulated", False),
            )

            scenes.append(scene)
            if scene is not None:
                success_count += 1

            if i % 10 == 0:
                print(f"\n--- Progress: {i}/{total} ({success_count} success, {i - success_count} failed) ---\n")

        print(f"\nBatch complete: {success_count}/{total} scenes generated")
        self.asset_manager.print_coverage_report()

        return scenes

    def load_scene(self, metadata_path: str) -> Scene | None:
        """Rebuild a Scene from a previously saved metadata JSON file.

        This replays the placement pipeline (translate + solve) using the
        stored ``llm_result``, so **no LLM call is made**.

        Args:
            metadata_path: Path to a ``*_metadata.json`` file produced by
                :meth:`generate_scene` with ``output_dir`` set.

        Returns:
            Arena Scene object, or None on failure.
        """
        from isaaclab_arena.assets.asset_registry import AssetRegistry

        path = Path(metadata_path)
        if not path.exists():
            print(f"[SceneGen] Metadata file not found: {path}")
            return None

        with open(path) as f:
            metadata = json.load(f)

        table_name = metadata["table"]
        llm_result = metadata["llm_result"]
        scene_name = metadata.get("scene_name", path.stem)

        registry = AssetRegistry()

        table_info = self.asset_manager.get_table_info(table_name)
        table_bounds = self.asset_manager.get_table_bounds(table_name)

        table = registry.get_asset_by_name(table_info["registry_name"])()
        table.set_initial_pose(Pose(position_xyz=(0.547, 0.0, -0.35), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))
        table.add_relation(IsAnchor())

        try:
            objects = translate_predicates(llm_result, table, self.asset_manager)
            result = place_objects_adaptive(
                objects,
                table,
                self.asset_manager,
                table_bounds=table_bounds,
                table_top_z=self.table_top_z,
                verbose=False,
            )

            if not result.success:
                print(f"[SceneGen] Placement failed when loading {scene_name}")
                return None

            scene = Scene()
            scene.add_asset(table)
            for obj in objects:
                scene.add_asset(obj)

            try:
                ground = registry.get_asset_by_name("ground_plane")()
                ground.set_initial_pose(Pose(position_xyz=(0.0, 0.0, -0.35)))
                scene.add_asset(ground)
            except Exception:
                pass

            try:
                import isaaclab.sim as sim_utils

                light_cfg = sim_utils.DomeLightCfg(color=(0.75, 0.75, 0.75), intensity=1500.0)
                light = registry.get_asset_by_name("light")(spawner_cfg=light_cfg)
                scene.add_asset(light)
            except Exception:
                pass

            print(f"[SceneGen] Loaded scene '{scene_name}' with {len(scene.assets)} assets")
            return scene

        except Exception as e:
            print(f"[SceneGen] Failed to load scene: {e}")
            return None

    def _save_metadata(self, scene_name, prompt, table_name, llm_result, positions):
        """Save scene generation metadata to JSON."""
        metadata = {
            "scene_name": scene_name,
            "prompt": prompt,
            "table": table_name,
            "llm_result": llm_result,
            "positions": {name: list(pos) for name, pos in positions.items()} if positions else {},
        }
        path = self.output_dir / f"{scene_name}_metadata.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"[SceneGen] Metadata saved: {path}")

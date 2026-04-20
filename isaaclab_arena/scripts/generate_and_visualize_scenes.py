# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Generate scenes with the LLM-based scene generator and optionally visualize in Isaac Sim.

Usage (inside the Arena Docker container):

    # Generate and visualize 1 kitchen scene (with Kit GUI):
    python isaaclab_arena/scripts/generate_and_visualize_scenes.py \
        --num_scenes 1 \
        --num_steps 200

    # Headless — generate 10 scenes and save metadata only:
    python isaaclab_arena/scripts/generate_and_visualize_scenes.py \
        --num_scenes 10 \
        --headless \
        --output_dir generated_scenes

    # Custom prompt:
    python isaaclab_arena/scripts/generate_and_visualize_scenes.py \
        --prompt "a messy desk with scattered office supplies" \
        --max_objects 8

    # Replay a previously generated scene (no LLM call):
    python isaaclab_arena/scripts/generate_and_visualize_scenes.py \
        --load generated_scenes/kitchen_scene_000_metadata.json \
        --num_steps 300

Requires ``NV_API_KEY`` environment variable for the LLM inference API
(not needed when using ``--load``).

Note: Isaac Sim supports only one active environment per process, so when
running with visualization (non-headless) only the *first* successfully
generated scene is visualized.
"""

import json
from pathlib import Path

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

KITCHEN_PROMPTS = [
    "A breakfast preparation scene with cereal box, milk carton, banana, and a bowl arranged neatly",
    "A fruit sorting station with apples, oranges, pears, and a large plate in the center",
    "A cooking prep area with a cutting board, spatula, tomato soup can, and assorted fruits",
    "A packed lunch assembly with crackers, a banana, pudding box, and a mug of coffee",
    "A snack arrangement with chips can, gelatin box, apple, and a small plate",
    "A kitchen counter with sugar box, mustard bottle, strawberry, and a mixing bowl",
    "A baking station with foam brick, measuring cups, power drill (misplaced tool), and a lemon",
    "A healthy meal prep with tuna can, peach, plum, and a medium-sized bowl",
    "A pantry restock scene with spam can, potted meat, tomato soup, and crackers on a plate",
    "A smoothie prep station with banana, orange, strawberry, pear, and a large pitcher",
]


def parse_args():
    parser = get_isaaclab_arena_cli_parser()
    parser.add_argument("--num_scenes", type=int, default=10, help="Number of scenes to generate.")
    parser.add_argument("--max_objects", type=int, default=8, help="Max objects per scene.")
    parser.add_argument("--output_dir", type=str, default=None, help="Directory to save scene metadata JSON files.")
    parser.add_argument("--prompt", type=str, default=None, help="Custom prompt (overrides built-in kitchen prompts).")
    parser.add_argument("--num_steps", type=int, default=200, help="Simulation steps per scene for visualization.")
    parser.add_argument("--table", type=str, default=None, help="Table name (random if not set).")
    parser.add_argument(
        "--load",
        type=str,
        default=None,
        nargs="+",
        help="Path(s) to metadata JSON file(s) to replay (skips LLM generation).",
    )
    return parser.parse_args()


def _visualize_scene(scene, scene_name, args):
    """Build an Arena env from *scene* and run a zero-action policy for ``args.num_steps``."""
    import torch

    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

    print(f"[VIZ] Visualizing {scene_name} for {args.num_steps} steps...")
    arena_env = IsaacLabArenaEnvironment(name=scene_name, scene=scene)
    builder = ArenaEnvBuilder(arena_env, args)

    env = builder.make_registered()
    env.reset()

    for _ in range(args.num_steps):
        actions = torch.zeros(env.action_space.shape, device=env.unwrapped.device)
        env.step(actions)

    env.close()


def _run_load(args):
    """Reload and visualize scenes from previously saved metadata files."""
    from isaaclab_arena.scene_gen import SceneGenerator

    generator = SceneGenerator(table_top_z=0.0)
    visualized = False

    for i, metadata_path in enumerate(args.load):
        scene = generator.load_scene(metadata_path)
        if scene is None:
            print(f"[WARN] Could not load scene from {metadata_path}")
            continue

        if not args.headless and not visualized:
            scene_name = Path(metadata_path).stem.replace("_metadata", "") or f"loaded_scene_{i:03d}"
            _visualize_scene(scene, scene_name, args)
            visualized = True


def _run_generate(args):
    """Generate new scenes via the LLM pipeline and optionally visualize."""
    from isaaclab_arena.scene_gen import SceneGenerator

    generator = SceneGenerator(
        output_dir=args.output_dir,
        table_top_z=0.0,
        max_retries=3,
    )

    num_scenes = args.num_scenes
    if args.prompt:
        prompts = [args.prompt] * num_scenes
    else:
        prompts = (KITCHEN_PROMPTS * ((num_scenes // len(KITCHEN_PROMPTS)) + 1))[:num_scenes]

    results = []
    visualized = False

    for i, prompt in enumerate(prompts):
        scene_name = f"kitchen_scene_{i:03d}"
        print(f"\n{'=' * 60}")
        print(f"Generating scene {i + 1}/{num_scenes}: {scene_name}")
        print(f"Prompt: {prompt}")
        print(f"{'=' * 60}\n")

        scene = generator.generate_scene(
            prompt=prompt,
            max_objects=args.max_objects,
            table_name=args.table,
            scene_name=scene_name,
        )

        if scene is None:
            print(f"[WARN] Scene {scene_name} generation failed, skipping.")
            results.append({"name": scene_name, "success": False, "prompt": prompt})
            continue

        num_assets = len(scene.assets)
        results.append({"name": scene_name, "success": True, "prompt": prompt, "num_assets": num_assets})
        print(f"[OK] Scene {scene_name}: {num_assets} assets")

        if not args.headless and not visualized:
            try:
                _visualize_scene(scene, scene_name, args)
                visualized = True
            except Exception as e:
                print(f"[WARN] Visualization failed for {scene_name}: {e}")

    # Print summary
    print(f"\n{'=' * 60}")
    print("GENERATION SUMMARY")
    print(f"{'=' * 60}")
    succeeded = sum(1 for r in results if r["success"])
    print(f"Total: {num_scenes}, Succeeded: {succeeded}, Failed: {num_scenes - succeeded}")
    for r in results:
        status = "OK" if r["success"] else "FAIL"
        assets = r.get("num_assets", "-")
        print(f"  [{status}] {r['name']}: {assets} assets — {r['prompt'][:60]}...")

    if args.output_dir:
        summary_path = f"{args.output_dir}/generation_summary.json"
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSummary saved to {summary_path}")

    generator.asset_manager.print_coverage_report()


def main():
    args = parse_args()

    with SimulationAppContext(args):
        if args.load:
            _run_load(args)
        else:
            _run_generate(args)


if __name__ == "__main__":
    main()

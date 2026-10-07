# Production revision bindings

`.pipeline/revisions.json` is the registry. It binds a production, episode and revision to the exact table, frame folder, clip folder and cut file. Registration never edits those artifacts or marks a gate passed.

## Example

```json
{
  "schema": "production-revisions-v1",
  "production_id": "example-show",
  "active": {"ep01": "v2"},
  "revisions": [{
    "episode_id": "ep01",
    "revision_id": "v2",
    "artifact_token": "ep01-v2",
    "artifacts": {
      "shot_list.json": ".pipeline/shot_list.ep01-v2.json",
      "writer.json": ".pipeline/writer.ep01-v2.json",
      "events.json": ".pipeline/events.ep01-v2.json",
      "event_evidence.json": ".pipeline/event_evidence.ep01-v2.json",
      "sequence_reviews.json": ".pipeline/sequence_reviews.ep01-v2.json"
    },
    "frames_dir": "04-frames/ep01-v2",
    "shots_dir": "05-shots/ep01-v2/official",
    "cut_file": ".pipeline/cut.ep01-v2.json"
  }]
}
```

Mappings can use production-relative paths or absolute paths inside the production. Parent traversal and paths outside the production are rejected. Unmapped artifacts use `stem.<artifact_token>.json`; they never borrow an unsuffixed file. Shared artifacts must be explicitly mapped.

## Commands

```bash
python3 scripts/register_revision.py --prod productions/example-show --episode 1 --revision v2 register \
  --artifact shot_list.json=.pipeline/shot_list.ep01-v2.json \
  --artifact writer.json=.pipeline/writer.ep01-v2.json \
  --frames-dir 04-frames/ep01-v2 --shots-dir 05-shots/ep01-v2/official \
  --cut-file .pipeline/cut.ep01-v2.json

python3 scripts/register_revision.py --prod productions/example-show --episode 1 --revision v2 activate
python3 scripts/check_prod.py --prod productions/example-show --episode 1 --revision v2
```

Without a registry, historical episode layouts remain available and reports explicitly say `binding_mode=legacy`. With a registry, omitting the revision selects that episode's active revision; a missing active revision, invalid registry or unknown revision is an error. A registered table cannot be missing, empty, duplicated or route a frame outside its bound frame folder.

`check_prod` / `check_storyboard` print `CHECK_SOURCE` JSON with the actual episode/revision, source file, SHA-256 and shot count. A technical/table validation result is not an artistic approval.

## Python integration

```python
from director.context import ProductionContext, using_context
from director.shot_repo import list_shots

ctx = ProductionContext.resolve(prod, episode=1, revision_id="v2")
table = ctx.read_artifact("shot_list.json", required=True)
cut_path = ctx.artifact_path("cut.json")
with using_context(ctx):
    shots = list_shots(ctx)
    # Task-local old read_artifact calls route to this revision, not another active revision.
```

Use `ctx.read_artifact`, `artifact_rel/path`, `frame_dir`, `shot_dir`, `cut_rel` and `source_report`. `artifact_name` remains compatible for artifacts inside `.pipeline`; an artifact mapped elsewhere must use `read_artifact` / `artifact_path`.

Registered gate fingerprints include the registry, mapped artifacts and version folder media, including designed tail frames. File-only migration locks are disabled; a previous lock without a fingerprint stays stale rather than acquiring new approval automatically. Take selection uses the revision artifact token and rejects another revision or a missing selected take.

Offline regressions: `python3 -m unittest discover -s scripts/tests -p test_revision_bindings.py`.

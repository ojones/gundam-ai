import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

from telemetry import events, invariants_test, managed_settings, schema

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "initial-specs.md"
HASH_PATH = ROOT / "docs" / "spec.sha256"
DEVIATIONS = {"queue.py": "spool.py"}
TEST_NAME = re.compile(r"^\s+def test_inv(\d\d)_", re.M)


def read(path):
    return Path(path).read_text(encoding="utf-8")


def spec_text():
    return read(SPEC_PATH)


def section(title):
    body = spec_text().split(f"\n## {title}", 1)[1]
    return re.split(r"\n## ", body, maxsplit=1)[0]


def spec_hash():
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def json_blocks():
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", spec_text(), re.S)]


def event_table_names():
    rows = [line for line in section("Hook event coverage").splitlines() if line.startswith("| `")]
    return {name for row in rows for name in re.findall(r"`(\w+)`", row.split("|")[1])}


def spec_modules():
    tree = re.search(r"```text\ntelemetry/\n(.*?)```", spec_text(), re.S).group(1)
    return re.findall(r"[├└]── (\S+)", tree)


def invariant_rows():
    return re.findall(r"^\| (INV-\d\d) \|.*\| (AC-\d\d(?:, AC-\d\d)*|-) \| (implemented|pending) \|$", read(ROOT / "docs" / "invariants.md"), re.M)


def acceptance_count():
    return len(re.findall(r"^- ", section("Acceptance criteria for implementation"), re.M))


def test_methods():
    found = {}
    for name in dir(invariants_test.Invariants):
        match = re.match(r"test_inv(\d\d)_", name)
        if match:
            found[f"INV-{match.group(1)}"] = getattr(invariants_test.Invariants, name)
    return found


class SpecSync(unittest.TestCase):
    def test_the_spec_is_unchanged_since_a_person_last_accepted_it(self):
        self.assertEqual(spec_hash(), read(HASH_PATH).strip(), "initial-specs.md changed: update code and docs, then run python3 -m telemetry.spec_sync_test --accept")

    def test_the_hook_event_table_is_the_registered_events(self):
        self.assertEqual(event_table_names(), set(events.HOOK_EVENTS))

    def test_the_optional_event_is_the_one_the_spec_marks_optional(self):
        self.assertIn("`PostToolBatch` (optional)", section("Hook event coverage"))
        self.assertEqual(events.OPTIONAL_EVENTS, ("PostToolBatch",))

    def test_the_events_the_spec_says_to_avoid_are_not_registered(self):
        avoid = re.search(r"Avoid `(\w+)` and `(\w+)`", section("Hook event coverage")).groups()
        self.assertEqual(set(avoid), set(events.EXCLUDED_EVENTS))
        self.assertEqual(set(avoid) & set(events.HOOK_EVENTS), set())

    def test_the_example_envelope_is_the_schema(self):
        example = next(block for block in json_blocks() if "schema_version" in block)
        self.assertEqual(tuple(example), schema.ENVELOPE_FIELDS)
        self.assertEqual(example["schema_version"], schema.SCHEMA_VERSION)
        self.assertLessEqual(set(example["metadata"]), set(schema.METADATA_FIELDS))

    def test_the_prompt_buckets_are_the_specs(self):
        for label, _ in schema.PROMPT_BUCKETS:
            self.assertIn(f"`{label}`", spec_text())

    def test_every_module_the_spec_lists_exists_or_is_a_declared_deviation(self):
        for name in spec_modules():
            actual = DEVIATIONS.get(name, name)
            if name != "tests/":
                self.assertTrue((ROOT / "telemetry" / actual).exists(), name)

    def test_declared_deviations_are_written_down_in_the_decisions(self):
        decisions = read(ROOT / "docs" / "decisions.md")
        for spec_name, actual in DEVIATIONS.items():
            self.assertIn(spec_name, decisions)
            self.assertIn(actual, decisions)

    def test_the_spec_settings_sample_has_the_shape_the_generator_produces(self):
        sample = next(block for block in json_blocks() if "hooks" in block)
        (event, groups), = sample["hooks"].items()
        generated = managed_settings.managed_settings(include_optional=True)["hooks"][event]
        self.assertEqual([sorted(g) for g in groups], [sorted(g) for g in generated])
        self.assertEqual(sorted(groups[0]["hooks"][0]), sorted(generated[0]["hooks"][0]))
        self.assertIs(groups[0]["hooks"][0]["async"], True)

    def test_the_python_floor_is_the_specs(self):
        floor = re.search(r"Python (\d+\.\d+)\+", spec_text()).group(1)
        self.assertIn(f'requires-python = ">={floor}"', read(ROOT / "pyproject.toml"))

    def test_the_invariants_table_and_the_invariant_tests_list_the_same_ids(self):
        self.assertEqual({row[0] for row in invariant_rows()}, set(test_methods()))

    def test_a_pending_invariant_has_a_skipped_test_and_an_implemented_one_does_not(self):
        methods = test_methods()
        for inv, _, status in invariant_rows():
            skipped = getattr(methods[inv], "__unittest_skip__", False)
            self.assertEqual(skipped, status == "pending", f"{inv} is {status}")

    def test_every_acceptance_criterion_is_covered_by_an_invariant(self):
        covered = {ac for _, acs, _ in invariant_rows() for ac in acs.split(", ")}
        expected = {f"AC-{n:02d}" for n in range(1, acceptance_count() + 1)}
        self.assertEqual(covered - {"-"}, expected)

    def test_the_decisions_and_claude_md_point_at_the_files_that_exist(self):
        for name in ("CLAUDE.md", "docs/decisions.md", "docs/invariants.md", "docs/privacy.md"):
            for target in re.findall(r"\]\(([^)#]+)\)", read(ROOT / name)):
                base = (ROOT / name).parent
                if not target.startswith("http"):
                    self.assertTrue((base / target).exists(), f"{name} links to missing {target}")


if __name__ == "__main__":
    if "--accept" in sys.argv:
        HASH_PATH.write_text(spec_hash() + "\n", encoding="utf-8")
    else:
        unittest.main()

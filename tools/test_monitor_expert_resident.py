"""Offline tests: the Monitor's live expert-residency figure (expert_slots_resident).

The engine's startup INFO line reports `expert_slots` (the arena's capacity) and, since this change,
`expert_slots_resident` (the slots actually holding an expert); each DONE line then carries the live
resident count as a 17th field, because a no-profile cache fills as requests run and the startup figure
is a snapshot.  Older engines send neither - the UI falls back to the capacity, as before.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.server import StrataEngine


def done_line(resident=None):
    # DONE <generated> <prompt> <prompt_ms> <decode_ms> <finish> <d_accepted> <d_offered> <reused>
    #      <hits> <lookups> <ram_blobs> <file_blobs> <file_mb> <prompt_read> <offloaded> [<resident>]
    fields = ["DONE", "8", "12", "30.0", "120.0", "stop", "3", "9", "0", "5", "20", "1", "0", "4.2", "12", "0"]
    if resident is not None:
        fields.append(str(resident))
    return " ".join(fields)


def bare_engine():
    # _parse_done only touches self.last and self.info; skip __init__ (it would spawn an engine process)
    engine = StrataEngine.__new__(StrataEngine)
    engine.info = {}
    return engine


class ParseDoneResident(unittest.TestCase):
    def test_old_engine_line_has_no_resident_field(self):
        engine = bare_engine()
        engine._parse_done(done_line())            # 16 fields: engine < this change
        self.assertNotIn("expert_slots_resident", engine.info)
        self.assertEqual(engine.last["offloaded"], 0)

    def test_resident_field_parsed(self):
        engine = bare_engine()
        engine._parse_done(done_line(resident=37))
        self.assertEqual(engine.info["expert_slots_resident"], 37)

    def test_later_lines_update_the_live_count(self):
        # the startup INFO's figure is a snapshot; a filling cache reports more as requests run
        engine = bare_engine()
        engine.info["expert_slots_resident"] = 0
        engine._parse_done(done_line(resident=37))
        engine._parse_done(done_line(resident=52))
        self.assertEqual(engine.info["expert_slots_resident"], 52)

    def test_full_cache_reports_capacity(self):
        engine = bare_engine()
        engine._parse_done(done_line(resident=1280))
        self.assertEqual(engine.info["expert_slots_resident"], 1280)


if __name__ == "__main__":
    unittest.main()

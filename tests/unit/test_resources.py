"""Release resources must agree with Python metadata and both UI languages."""

import json
import unittest
from pathlib import Path

# isort: off
from tests.support import CORE, ROOT
from shm_core.const import DOMAIN, VERSION
# isort: on


def leaf_keys(value, prefix=""):
    if isinstance(value, dict):
        return {p for k, v in value.items() for p in leaf_keys(v, f"{prefix}.{k}")}
    return {prefix}


class ResourceTests(unittest.TestCase):
    def test_metadata_and_versions(self):
        manifest = json.loads((CORE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], DOMAIN)
        self.assertEqual(manifest["version"], VERSION)
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["requirements"], [])
        self.assertEqual(len(list((ROOT / "custom_components").glob("*/manifest.json"))), 1)

    def test_translations_have_complete_matching_keys(self):
        base = json.loads((CORE / "strings.json").read_text(encoding="utf-8"))
        for lang in ("fr", "en"):
            data = json.loads((CORE / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertEqual(leaf_keys(base), leaf_keys(data))
            for group in ("config", "options"):
                steps = data[group]["step"]
                for menu in ("menu", "rooms"):
                    for step in steps[menu]["menu_options"]:
                        # Add only leads to room; every other target has its own form/menu.
                        self.assertTrue(step in steps or step == "add_room")

    def test_release_builder_is_self_contained(self):
        import importlib.util
        from tempfile import TemporaryDirectory
        from zipfile import ZipFile

        script = ROOT / "tools" / "build_release.py"
        spec = importlib.util.spec_from_file_location("release", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            module.write_zip(path, {"custom_components/smart_heat_manager/manifest.json": b"{}"})
            first = path.read_bytes()
            module.write_zip(path, {"custom_components/smart_heat_manager/manifest.json": b"{}"})
            self.assertEqual(first, path.read_bytes())
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())

    def test_clone_url_generates_browser_links_without_git_suffix(self):
        from tools.build_release import repository_metadata

        expected = {
            "documentation": "https://github.com/Macorou/HA#readme",
            "issue_tracker": "https://github.com/Macorou/HA/issues",
            "codeowners": ["@Macorou"],
        }
        for url in (
            "https://github.com/Macorou/HA",
            "https://github.com/Macorou/HA.git",
            "https://github.com/Macorou/HA.git/",
        ):
            self.assertEqual(repository_metadata(url), expected)

    def test_repository_metadata_rejects_non_repository_urls(self):
        from tools.build_release import repository_metadata

        for url in (
            "https://github.com/Macorou",
            "https://example.com/Macorou/HA",
            "https://github.com/Macorou/HA/tree/main",
            "https://github.com/Macorou/HA?token=x",
            "https://github.com/Macorou/.git",
        ):
            with self.assertRaises(ValueError, msg=url):
                repository_metadata(url)


if __name__ == "__main__":
    unittest.main()

import os
import unittest

from worktree_manager.worktree_lifecycle import path_key


def _expected(value):
    return value.lower() if os.name == "nt" else value


class PathKeyTests(unittest.TestCase):
    def test_windows_and_git_separators_produce_one_identity(self):
        from_filesystem = path_key("E:\\repo\\.worktrees\\wt", "\\")
        from_git = path_key("E:/repo/.worktrees/wt", "/")
        self.assertEqual(from_filesystem, from_git)
        self.assertEqual(from_filesystem, _expected("E:/repo/.worktrees/wt"))

    def test_forward_slashes_survive_backslash_normalization(self):
        self.assertEqual(
            path_key("E:/repo/.worktrees/wt", "\\"),
            _expected("E:/repo/.worktrees/wt"),
        )

    def test_default_separator_normalizes_native_paths(self):
        native = os.path.join("repo", ".worktrees", "wt")
        self.assertEqual(path_key(native), _expected("repo/.worktrees/wt"))

    @unittest.skipUnless(os.name == "nt", "Windows-only case folding")
    def test_windows_keys_are_case_insensitive(self):
        self.assertEqual(
            path_key("E:\\Repo\\Worktrees\\WT"),
            path_key("e:/repo/worktrees/wt"),
        )

    @unittest.skipIf(os.name == "nt", "POSIX preserves case")
    def test_posix_keys_preserve_case(self):
        self.assertEqual(path_key("/Repo/Worktrees/WT"), "/Repo/Worktrees/WT")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


def load(name):
    spec = importlib.util.spec_from_file_location(name, name + '.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

launcher = load('desktop_launcher')
packager = load('package_standalone')


class DesktopTests(unittest.TestCase):
    def test_data_directory_is_persistent_and_platform_specific(self):
        with patch.dict(os.environ, {'HOME':str(Path.home()), 'USERPROFILE':str(Path.home())}, clear=True):
            with patch.object(sys, 'platform', 'win32'):
                self.assertEqual(launcher.data_directory().name, 'LocalRSS')
                self.assertIn('AppData', str(launcher.data_directory()))
            with patch.object(sys, 'platform', 'darwin'):
                self.assertIn('Application Support', str(launcher.data_directory()))
            with patch.object(sys, 'platform', 'linux'):
                self.assertEqual(launcher.data_directory(), Path.home()/'.local/share/localrss')
        with patch.dict(os.environ, {'RSS_DESKTOP_DATA_DIR':str(Path.home()/'custom-rss')}):
            self.assertEqual(launcher.data_directory(),Path.home()/'custom-rss')

    def test_explicit_database_override_is_preserved_and_backend_initialized(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'RSS_DB':'chosen.db'}):
            with patch.object(launcher.importlib,'import_module') as load_backend:
                result = launcher.load_backend(Path(temp)/'profile',disable_scheduler=True)
                self.assertEqual(os.environ['RSS_DB'],'chosen.db')
                self.assertEqual(os.environ['RSS_DISABLE_SCHEDULER'],'1')
                load_backend.assert_called_once_with('app')
                result.init_db.assert_called_once()
                self.assertTrue((Path(temp)/'profile').is_dir())

    def test_archive_contains_only_program_and_instructions(self):
        for platform in packager.PLATFORMS:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); (root/'dist').mkdir()
                name = 'LocalRSS.exe' if platform.startswith('windows') else 'LocalRSS'
                executable = root/'dist'/name
                executable.write_bytes(b'fixture executable')
                executable.chmod(0o755)
                (root/'global.db').write_bytes(b'must never package user data')
                with patch.object(packager,'ROOT',root):
                    archive = packager.package(platform)
                if platform.startswith('windows'):
                    with zipfile.ZipFile(archive) as data:
                        self.assertEqual(set(data.namelist()),{name,'START_HERE.txt'})
                else:
                    with tarfile.open(archive) as data:
                        self.assertEqual(set(data.getnames()),{name,'START_HERE.txt'})
                        if os.name != 'nt':
                            self.assertTrue(data.getmember(name).mode & 0o111)

    def test_unknown_platform_cannot_package_files(self):
        with self.assertRaises(ValueError): packager.package('unknown')


if __name__ == '__main__': unittest.main()

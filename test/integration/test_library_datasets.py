import os
import shutil
import tempfile
from tempfile import mkdtemp
from typing import ClassVar

from galaxy_test.base.api_util import TEST_USER
from galaxy_test.base.populators import LibraryPopulator
from galaxy_test.driver import integration_util


class ConfiguresRemoteFilesIntegrationTestCase(integration_util.IntegrationTestCase):
    library_dir: ClassVar[str]
    root: ClassVar[str]

    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        root = os.path.realpath(mkdtemp())
        cls._test_driver.temp_directories.append(root)
        cls.root = root
        cls.library_dir = os.path.join(root, "library")
        config["library_import_dir"] = cls.library_dir
        config["user_library_import_dir"] = cls.library_dir

    def setUp(self):
        super().setUp()
        self.library_populator = LibraryPopulator(self.galaxy_interactor)

        self.library = self.library_populator.new_private_library("private_dataset")

        if os.path.exists(self.library_dir):
            shutil.rmtree(self.library_dir)
        os.mkdir(self.library_dir)

        self.dir_to_import = "library"
        self.admin_dir_to_import = os.path.join(TEST_USER, self.dir_to_import)
        full_dir = os.path.join(self.library_dir, self.admin_dir_to_import)
        os.makedirs(full_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=full_dir, delete=False) as fh:
            fh.write("hello world!")
        self.file_to_import = os.path.join(self.dir_to_import, os.path.basename(fh.name))
        self.admin_file_to_import = os.path.join(self.admin_dir_to_import, os.path.basename(fh.name))


class TestLibraryDatasetsIntegration(ConfiguresRemoteFilesIntegrationTestCase):
    def test_load_library_dataset(self):
        userdir_folder_load_payload = {
            "encoded_folder_id": self.library["root_folder_id"],
            "source": "userdir_folder",
            "path": self.dir_to_import,
        }
        userdir_folder_response = self._post("libraries/datasets", data=userdir_folder_load_payload)
        self._assert_status_code_is(userdir_folder_response, 200)

        userdir_file_load_payload = {
            "encoded_folder_id": self.library["root_folder_id"],
            "source": "userdir_file",
            "path": self.file_to_import,
        }
        userdir_file_response = self._post("libraries/datasets", data=userdir_file_load_payload)
        self._assert_status_code_is(userdir_file_response, 200)

    def test_admin_load_library_dataset(self):
        importdir_folder_load_payload = {
            "encoded_folder_id": self.library["root_folder_id"],
            "source": "importdir_folder",
            "path": self.admin_dir_to_import,
        }
        importdir_folder_response = self._post("libraries/datasets", data=importdir_folder_load_payload, admin=True)
        self._assert_status_code_is(importdir_folder_response, 200)

        importdir_file_load_payload = {
            "encoded_folder_id": self.library["root_folder_id"],
            "source": "importdir_file",
            "path": self.admin_file_to_import,
        }
        importdir_file_response = self._post("libraries/datasets", data=importdir_file_load_payload, admin=True)
        self._assert_status_code_is(importdir_file_response, 200)

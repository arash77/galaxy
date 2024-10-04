import os
import tempfile

from galaxy.util import galaxy_directory
from galaxy_test.base.api_util import TEST_USER
from galaxy_test.base.decorators import requires_admin
from galaxy_test.base.populators import LibraryPopulator
from ._framework import ApiTestCase


class TestLibraryDatasetsApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.library_populator = LibraryPopulator(self.galaxy_interactor)

        self.library, self.library_dataset = self.library_populator.new_library_dataset_in_private_library()

    def test_show_library_dataset(self):
        dataset_id = self.library_dataset["id"]
        show_response = self._get(f"libraries/datasets/{dataset_id}")
        self._assert_status_code_is(show_response, 200)
        dataset = show_response.json()
        assert dataset["id"] == dataset_id
        assert dataset["ldda_id"] == dataset_id
        assert dataset["parent_library_id"] == self.library["id"]
        assert dataset["folder_id"] == self.library["root_folder_id"]
        assert dataset["model_class"] == "LibraryDataset"

    def test_show_version_library_dataset_not_exist(self):
        # Could not find the dataset in expired_datasets
        dataset_id = self.library_dataset["id"]
        show_response = self._get(f"libraries/datasets/{dataset_id}/versions/{dataset_id}")
        self._assert_status_code_is(show_response, 404)

    def test_show_roles_library_dataset(self):
        dataset_id = self.library_dataset["id"]
        show_response = self._get(f"libraries/datasets/{dataset_id}/permissions")
        self._assert_status_code_is(show_response, 200)
        roles = show_response.json()
        self._assert_has_keys(roles, "access_dataset_roles", "modify_item_roles", "manage_dataset_roles")

        show_response_available = self._get(f"libraries/datasets/{dataset_id}/permissions?scope=available")
        self._assert_status_code_is(show_response_available, 200)
        roles_available = show_response_available.json()
        self._assert_has_keys(roles_available, "roles", "page", "page_limit", "total")

    def test_update_library_dataset(self):
        dataset_id = self.library_dataset["id"]
        update_payload = {
            "name": "new name",
            "misc_info": "new misc info",
            "file_ext": "txt",
            "genome_build": "hg19",
            "tags": ["cool", "neat"],
        }
        update_response = self._patch(f"libraries/datasets/{dataset_id}", data=update_payload)
        self._assert_status_code_is(update_response, 200)
        updated_dataset = update_response.json()
        assert updated_dataset["name"] == update_payload["name"]
        assert updated_dataset["file_ext"] == update_payload["file_ext"]
        assert updated_dataset["genome_build"] == update_payload["genome_build"]
        assert updated_dataset["tags"] == update_payload["tags"]

    def test_update_permissions_library_dataset(self):
        dataset_id = self.library_dataset["id"]
        remove_restrictions_payload = {
            "action": "remove_restrictions",
        }
        remove_restrictions_response = self._post(
            f"libraries/datasets/{dataset_id}/permissions", data=remove_restrictions_payload
        )
        self._assert_status_code_is(remove_restrictions_response, 200)

        make_private_payload = {
            "action": "make_private",
        }
        make_private_response = self._post(f"libraries/datasets/{dataset_id}/permissions", data=make_private_payload)
        self._assert_status_code_is(make_private_response, 200)

        set_permissions_payload = {
            "action": "set_permissions",
            "access_ids[]": [],
            "manage_ids[]": [],
            "modify_ids[]": [],
        }
        set_permissions_response = self._post(
            f"libraries/datasets/{dataset_id}/permissions", data=set_permissions_payload
        )
        self._assert_status_code_is(set_permissions_response, 200)

    @requires_admin
    def test_delete_library_dataset(self):
        dataset_id = self.library_dataset["id"]
        delete_response = self._delete(f"libraries/datasets/{dataset_id}")
        self._assert_status_code_is(delete_response, 200)
        deleted_dataset = delete_response.json()
        assert deleted_dataset["deleted"] is True

        undelete_response = self._delete(f"libraries/datasets/{dataset_id}?undelete=true", admin=True)
        self._assert_status_code_is(undelete_response, 200)
        undeleted_dataset = undelete_response.json()
        assert undeleted_dataset["deleted"] is False

    def test_load_library_dataset(self):
        # Not sure if this should be in api tests
        dir_to_import = "library"
        full_dir_path = os.path.join(galaxy_directory(), "test-data", "users", TEST_USER, dir_to_import)
        os.makedirs(full_dir_path)
        with tempfile.NamedTemporaryFile(mode="w", dir=full_dir_path, delete=False) as fh:
            fh.write("hello world")

        load_payload = {
            "encoded_folder_id": self.library["root_folder_id"],
            "source": "userdir_folder",
            "path": dir_to_import,
        }
        response = self._post("libraries/datasets", data=load_payload)
        self._assert_status_code_is(response, 200)

from datetime import datetime
from typing import (
    List,
    Optional,
    Tuple,
)

from pydantic import Field
from typing_extensions import (
    Annotated,
    Literal,
)

from galaxy.schema.fields import (
    DecodedDatabaseIdField,
    EncodedDatabaseIdField,
    EncodedLibraryFolderDatabaseIdField,
    ModelClassField,
)
from galaxy.schema.schema import Model


class LibraryDatasetsShowResponse(Model):
    model_class: Annotated[Literal["LibraryDataset"], ModelClassField(Literal["LibraryDataset"])]
    id: EncodedDatabaseIdField
    ldda_id: EncodedDatabaseIdField
    parent_library_id: EncodedDatabaseIdField
    folder_id: EncodedLibraryFolderDatabaseIdField
    name: str
    deleted: bool
    full_path: List[Tuple[str, str]]
    file_size: str
    date_uploaded: datetime
    update_time: datetime
    can_user_modify: bool
    is_unrestricted: bool
    tags: List[str]
    can_user_manage: bool
    has_versions: bool
    expired_versions: List[Tuple[str, str]]
    job_stdout: Optional[str]
    job_stderr: Optional[str]
    uuid: Optional[str]

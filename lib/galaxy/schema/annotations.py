from typing import (
    List,
    Optional,
)

from pydantic import (
    Field,
    RootModel,
)

from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.schema import Model


class AnnotationResponse(Model):
    """Response schema for showing an item annotation."""

    model_class: str = Field(
        ...,
        title="model class",
    )
    id: EncodedDatabaseIdField = Field(
        ...,
        title="item annotation ID",
    )
    user_tname: str = Field(
        ...,
        title="name of the item annotation",
    )
    user_value: Optional[str] = Field(
        None,
        title="value of the item annotation",
    )


class AnnotationsListResponse(RootModel):
    """Response schema for listing item annotations."""

    root: List[AnnotationResponse]


class AnnotationCreatePayload(Model):
    """Payload schema for creating an item annotation."""

    text: Optional[str] = Field(
        None,
        title="annotation of the item",
    )

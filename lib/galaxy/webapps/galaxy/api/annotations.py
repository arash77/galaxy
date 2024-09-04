"""
API operations on annotations.
"""

import logging

from fastapi import (
    Body,
    Path,
)
from typing_extensions import Annotated

from galaxy.managers.annotations import AnnotationsManager
from galaxy.managers.context import ProvidesAppContext
from galaxy.schema.annotations import (
    AnnotationCreatePayload,
    AnnotationResponse,
    AnnotationsListResponse,
)
from galaxy.schema.fields import DecodedDatabaseIdField
from galaxy.webapps.galaxy.api import (
    depends,
    DependsOnTrans,
    Router,
)

log = logging.getLogger(__name__)

router = Router()


@router.cbv
class FastAPIAnnotations:
    manager: AnnotationsManager = depends(AnnotationsManager)

    @classmethod
    def create_class(cls, prefix, annotation_id, api_docs_tag, extra_path_params):
        class Temp(cls):
            @router.get(
                f"/api/{prefix}/{{{annotation_id}}}/annotation",
                tags=[api_docs_tag],
                summary=f"Show annotations based on {annotation_id}",
                openapi_extra=extra_path_params,
            )
            def index(
                self,
                trans: ProvidesAppContext = DependsOnTrans,
                item_id: DecodedDatabaseIdField = Path(..., title="Item ID", alias=annotation_id),
            ) -> AnnotationsListResponse:
                return self.manager.index(trans, annotation_id, item_id)

            @router.post(
                f"/api/{prefix}/{{{annotation_id}}}/annotation",
                tags=[api_docs_tag],
                summary=f"Create tag based on {annotation_id}",
                openapi_extra=extra_path_params,
            )
            def create(
                self,
                item_id: Annotated[DecodedDatabaseIdField, Path(..., title="Item ID", alias=annotation_id)],
                trans: ProvidesAppContext = DependsOnTrans,
                payload: AnnotationCreatePayload = Body(None),
            ) -> AnnotationResponse:
                return self.manager.create(trans, annotation_id, item_id, payload)

            @router.delete(
                f"/api/{prefix}/{{{annotation_id}}}/annotation/{{id}}",
                tags=[api_docs_tag],
                summary=f"Delete tag based on {annotation_id}",
                openapi_extra=extra_path_params,
            )
            def delete(
                self,
                item_id: Annotated[DecodedDatabaseIdField, Path(..., title="Item ID", alias=annotation_id)],
                trans: ProvidesAppContext = DependsOnTrans,
                tag_name: str = Path(..., title="Tag Name"),
            ) -> bool:
                return self.manager.delete(trans, annotation_id, item_id, tag_name)

        return Temp


prefixes = {
    "histories": ["history_id", "histories"],
    "histories/{history_id}/contents": ["history_content_id", "histories"],
    "workflows": ["workflow_id", "workflows"],
}
for prefix, annotation in prefixes.items():
    annotation_id, api_docs_tag = annotation
    extra_path_params = None
    if annotation_id == "history_content_id":
        extra_path_params = {
            "parameters": [
                {
                    "in": "path",
                    "name": "history_id",
                    "required": True,
                    "schema": {"title": "History ID", "type": "string"},
                }
            ]
        }

    router.cbv(FastAPIAnnotations.create_class(prefix, annotation_id, api_docs_tag, extra_path_params))

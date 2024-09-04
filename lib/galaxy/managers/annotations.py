from galaxy.managers import base
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.managers.hdas import HDAManager
from galaxy.managers.histories import HistoryManager
from galaxy.model.base import transaction
from galaxy.model.item_attrs import UsesAnnotations
from galaxy.schema.annotations import (
    AnnotationCreatePayload,
    AnnotationResponse,
    AnnotationsListResponse,
)
from galaxy.schema.fields import DecodedDatabaseIdField
from galaxy.structured_app import MinimalManagerApp
from galaxy.util.sanitize_html import sanitize_html
from galaxy.webapps.base.controller import UsesStoredWorkflowMixin


class AnnotationsManager:
    """Interface/service object shared by controllers for interacting with annotations."""

    def __init__(self, app: MinimalManagerApp) -> None:
        self._app = app
        self._annotation_handler = UsesAnnotations

    def index(
        self,
        trans: ProvidesHistoryContext,
        annotation_id: str,
        idnum: DecodedDatabaseIdField,
    ):
        """Displays the annotations associated with an item."""
        if (item := self._get_item_from_id(trans, annotation_id, idnum)) is not None:
            return self._annotation_handler.get_item_annotation_str(trans.sa_session, trans.user, item)

    def create(
        self,
        trans: ProvidesHistoryContext,
        annotation_id: str,
        payload: AnnotationCreatePayload,
        idnum: DecodedDatabaseIdField,
    ):
        if (item := self._get_item_from_id(trans, annotation_id, idnum)) is not None:
            new_annotation = payload.text
            # TODO: sanitize on display not entry
            new_annotation = sanitize_html(new_annotation)

            self._annotation_handler.add_item_annotation(trans.sa_session, trans.user, item, new_annotation)
            with transaction(trans.sa_session):
                trans.sa_session.commit()
            return new_annotation
        return ""

    def delete(
        self,
        trans: ProvidesHistoryContext,
        annotation_id: str,
        idnum: DecodedDatabaseIdField,
    ):
        if (item := self._get_item_from_id(trans, annotation_id, idnum)) is not None:
            return self._annotation_handler.delete_item_annotation(trans.sa_session, trans.user, item)

    def _get_item_from_id(
        self,
        trans: ProvidesHistoryContext,
        annotation_id: str,
        idnum: DecodedDatabaseIdField,
    ):
        if annotation_id == "history_id":
            item = HistoryManager.get_accessible(idnum, trans.user, current_history=trans.history)
        elif annotation_id == "history_content_id":
            item = HDAManager.error_if_uploading(HDAManager.get_accessible(idnum, trans.user))
        elif annotation_id == "workflow_id":
            item = UsesStoredWorkflowMixin.get_stored_workflow(trans, idnum)
        return item

"""
API that asynchronous job running mechanisms can use to fetch or put files related to running and queued jobs.
"""

import logging
import os
import re
import shutil
import tempfile
from typing import (
    Annotated,
    IO,
    Optional,
)
from urllib.parse import (
    parse_qsl,
    unquote,
)

from fastapi import (
    Path,
    Query,
    Request,
)
from python_multipart import MultipartParser
from python_multipart.multipart import (
    MultipartParseError,
    parse_options_header,
)

from galaxy import (
    exceptions,
    util,
)
from galaxy.managers.context import ProvidesAppContext
from galaxy.model import Job
from galaxy.web import expose_api_anonymous_and_sessionless
from galaxy.webapps.base.api import GalaxyFileResponse
from galaxy.webapps.galaxy.api import (
    DependsOnTrans,
    Router,
)
from . import BaseGalaxyAPIController

__all__ = ("FastAPIJobFiles", "JobFilesAPIController", "router")

log = logging.getLogger(__name__)


router = Router(tags=["jobs"])


@router.cbv
class FastAPIJobFiles:
    """
    This job files controller allows remote job running mechanisms to read and modify the current state of files for
    queued and running jobs. It is certainly not meant to represent part of Galaxy's stable, user facing API.

    Furthermore, even if a user key corresponds to the user running the job, it should not be accepted for authorization
    - this API allows access to low-level unfiltered files and such authorization would break Galaxy's security model
    for tool execution.
    """

    # FastAPI answers HEAD requests automatically for GET endpoints returning `FileResponse`. However, because of the
    # way legacy WSGI endpoints are injected into the FastAPI app (using `app.mount("/", wsgi_handler)`), the built-in
    # support for `HEAD` requests breaks, because such requests are passed to the `wsgi_handler` sub-application. This
    # means that the endpoint still needs to include some code to handle this behavior, as tests existing before the
    # migration to FastAPI expect HEAD requests to work.
    @router.get(
        "/api/jobs/{job_id}/files",
        summary="Get a file required to staging a job.",
        responses={
            200: {
                "description": "Contents of file.",
                "content": {"application/json": None, "application/octet-stream": {"example": None}},
            },
            400: {
                "description": (
                    "File not found, path does not refer to a file, or input dataset(s) for job have been purged."
                )
            },
        },
    )
    @router.head("/api/jobs/{job_id}/files", include_in_schema=False)
    # remove `@router.head(...)` when ALL endpoints have been migrated to FastAPI
    def index(
        self,
        job_id: Annotated[str, Path(description="Encoded id string of the job.")],
        path: Annotated[
            str,
            Query(
                description="Path to file.",
            ),
        ],
        job_key: Annotated[
            str,
            Query(
                description=(
                    "A key used to authenticate this request as acting on behalf or a job runner for the specified job."
                ),
            ),
        ],
        trans: ProvidesAppContext = DependsOnTrans,
    ) -> GalaxyFileResponse:
        """
        Get a file required to staging a job (proper datasets, extra inputs, task-split inputs, working directory
        files).

        This API method is intended only for consumption by job runners, not end users.
        """
        path = unquote(path)

        job = self.__authorize_job_access(trans, job_id, path=path, job_key=job_key)

        if not os.path.exists(path):
            # We know that the job is not terminal, but users (or admin scripts) can purge input datasets.
            # Here we discriminate that case from truly unexpected bugs.
            # Not failing the job here, this is or should be handled by pulsar.
            match = re.match(r"(galaxy_)?dataset_(.*)\.dat", os.path.basename(path))
            if match:
                # This looks like a galaxy dataset, check if any job input has been deleted.
                if any(jtid.dataset and jtid.dataset.dataset.purged for jtid in job.input_datasets):
                    raise exceptions.ItemDeletionException("Input dataset(s) for job have been purged.")

        return GalaxyFileResponse(path)

    @router.post(
        "/api/jobs/{job_id}/files",
        summary="Populate an output file.",
        responses={
            200: {"description": "An okay message.", "content": {"application/json": {"example": {"message": "ok"}}}},
        },
    )
    async def create(
        self,
        request: Request,
        job_id: Annotated[str, Path(description="Encoded id string of the job.")],
        path_query: Annotated[Optional[str], Query(alias="path", description="Path to file to create.")] = None,
        job_key_query: Annotated[
            Optional[str],
            Query(
                alias="job_key",
                description=(
                    "A key used to authenticate this request as acting on behalf or a job runner for the specified job."
                ),
            ),
        ] = None,
        trans: ProvidesAppContext = DependsOnTrans,
    ):
        """
        Populate an output file (formal dataset, task split part, working directory file (such as those related to
        metadata). This should be a multipart POST with a 'file' parameter containing the contents of the actual file to
        create.

        This API method is intended only for consumption by job runners, not end users.
        """
        path = unquote(path_query) if path_query else None
        job_key = job_key_query
        job = None
        if path and job_key:
            job = self.__authorize_job_access(trans, job_id, path=path, job_key=job_key)
            self.__check_job_can_write_to_path(trans, job, path)

        input_file_path: Optional[str] = None
        staged_input_file_path: Optional[str] = None
        form_fields: dict[str, str] = {}

        content_type, content_type_options = parse_options_header(request.headers.get("content-type"))
        try:
            if content_type == b"multipart/form-data":
                boundary = content_type_options.get(b"boundary")
                if boundary is None:
                    raise exceptions.RequestParameterInvalidException("Missing multipart boundary.")

                current_part_headers: dict[bytes, bytes] = {}
                current_header_field = bytearray()
                current_header_value = bytearray()
                current_part_field_name: Optional[str] = None
                current_part_data = bytearray()
                current_part_file: Optional[IO[bytes]] = None

                def on_part_begin():
                    nonlocal current_part_field_name, current_part_file
                    current_part_headers.clear()
                    current_part_field_name = None
                    current_part_data.clear()
                    current_part_file = None

                def on_header_begin():
                    current_header_field.clear()
                    current_header_value.clear()

                def on_header_field(data, start, end):
                    current_header_field.extend(data[start:end])

                def on_header_value(data, start, end):
                    current_header_value.extend(data[start:end])

                def on_header_end():
                    current_part_headers[bytes(current_header_field).lower()] = bytes(current_header_value)

                def on_headers_finished():
                    nonlocal current_part_field_name, current_part_file, input_file_path, staged_input_file_path
                    _, options = parse_options_header(current_part_headers.get(b"content-disposition"))
                    part_name = options.get(b"name")
                    current_part_field_name = part_name.decode("utf-8") if part_name else None
                    if b"filename" not in options:
                        return
                    if input_file_path is not None:
                        raise exceptions.RequestParameterInvalidException("Multiple file uploads are not supported.")

                    staging_dir = self.__staging_directory_for_upload(trans, path)
                    util.safe_makedirs(staging_dir)
                    current_part_file = tempfile.NamedTemporaryFile(dir=staging_dir, delete=False)
                    staged_input_file_path = current_part_file.name
                    input_file_path = staged_input_file_path

                def on_part_data(data, start, end):
                    if current_part_file is not None:
                        current_part_file.write(data[start:end])
                    else:
                        current_part_data.extend(data[start:end])

                def on_part_end():
                    if current_part_file is not None:
                        current_part_file.flush()
                        current_part_file.close()
                    if current_part_field_name is not None and current_part_file is None:
                        form_fields[current_part_field_name] = current_part_data.decode("utf-8")

                parser = MultipartParser(
                    boundary,
                    callbacks={
                        "on_part_begin": on_part_begin,
                        "on_header_begin": on_header_begin,
                        "on_header_field": on_header_field,
                        "on_header_value": on_header_value,
                        "on_header_end": on_header_end,
                        "on_headers_finished": on_headers_finished,
                        "on_part_data": on_part_data,
                        "on_part_end": on_part_end,
                    },
                )
                try:
                    async for chunk in request.stream():
                        parser.write(chunk)
                    parser.finalize()
                except MultipartParseError as exc:
                    raise exceptions.RequestParameterInvalidException(f"Invalid multipart request: {exc}") from exc
            elif content_type == b"application/x-www-form-urlencoded":
                body = await request.body()
                form_fields.update(dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True)))
            else:
                raise exceptions.RequestParameterInvalidException(
                    f"Unsupported content type for upload: {content_type.decode('latin-1') or '<missing>'}."
                )

            if not path:
                form_path = form_fields.get("path")
                path = unquote(form_path) if form_path else None
            if not job_key:
                job_key = form_fields.get("job_key")
            if path is None:
                raise exceptions.RequestParameterMissingException("Missing required parameter 'path'.")
            if job_key is None:
                raise exceptions.RequestParameterMissingException("Missing required parameter 'job_key'.")

            if job is None:
                job = self.__authorize_job_access(trans, job_id, path=path, job_key=job_key)
                self.__check_job_can_write_to_path(trans, job, path)

            nginx_upload_module_file_path = form_fields.get("__file_path")
            session_id = form_fields.get("session_id")

            # Is this writing an unneeded file? Should this just copy in Python?
            if nginx_upload_module_file_path:
                input_file_path = nginx_upload_module_file_path
                upload_store = trans.app.config.nginx_upload_job_files_store
                assert upload_store, (
                    "Request appears to have been processed by"
                    " nginx_upload_module but Galaxy is not"
                    " configured to recognize it"
                )
                assert input_file_path.startswith(
                    upload_store
                ), f"Filename provided by nginx ({input_file_path}) is not in correct directory ({upload_store})"
            elif session_id:
                # code stolen from basic.py
                upload_store = (
                    trans.app.config.tus_upload_store_job_files
                    or trans.app.config.tus_upload_store
                    or trans.app.config.new_file_path
                )
                if re.match(r"^[\w-]+$", session_id) is None:
                    raise ValueError("Invalid session id format.")
                local_filename = os.path.abspath(os.path.join(upload_store, session_id))
                input_file_path = local_filename
            elif input_file_path is None:
                raise exceptions.RequestParameterMissingException("No file uploaded.")

            target_dir = os.path.dirname(path)
            util.safe_makedirs(target_dir)
            if os.path.exists(path) and (path.endswith("tool_stdout") or path.endswith("tool_stderr")):
                with open(path, "ab") as destination:
                    with open(input_file_path, "rb") as input_file_handle:
                        shutil.copyfileobj(input_file_handle, destination)
                if staged_input_file_path and os.path.exists(staged_input_file_path):
                    os.remove(staged_input_file_path)
                    staged_input_file_path = None
            else:
                shutil.move(input_file_path, path)
                if staged_input_file_path == input_file_path:
                    staged_input_file_path = None

            return {"message": "ok"}
        finally:
            if staged_input_file_path and os.path.exists(staged_input_file_path):
                os.remove(staged_input_file_path)

    def __authorize_job_access(self, trans, encoded_job_id, path, job_key):
        job_id = trans.security.decode_id(encoded_job_id)
        job_key_from_job_id = trans.security.encode_id(job_id, kind="jobs_files")
        if not util.safe_str_cmp(str(job_key), job_key_from_job_id):
            raise exceptions.ItemAccessibilityException("Invalid job_key supplied.")

        # Verify job is active. Don't update the contents of complete jobs.
        job = trans.sa_session.get(Job, job_id)
        assert job
        if job.state not in Job.non_ready_states:
            error_message = "Attempting to read or modify the files of a job that has already completed."
            raise exceptions.ItemAccessibilityException(error_message)
        return job

    def __check_job_can_write_to_path(self, trans, job, path):
        """
        Verify an idealized job runner should actually be able to write to the specified path - it must be a dataset
        output, a dataset "extra file", or a some place in the working directory of this job.

        Would like similar checks for reading the unstructured nature of loc
        files make this very difficult. (See abandoned work here
        https://gist.github.com/jmchilton/9103619.)
        """
        in_work_dir = self.__in_working_directory(job, path, trans.app)
        if not in_work_dir and not self.__is_output_dataset_path(job, path):
            raise exceptions.ItemAccessibilityException("Job is not authorized to write to supplied path.")

    def __staging_directory_for_upload(self, trans, path: Optional[str]) -> str:
        if path:
            return os.path.dirname(path)
        return (
            trans.app.config.tus_upload_store_job_files
            or trans.app.config.tus_upload_store
            or trans.app.config.new_file_path
        )

    def __is_output_dataset_path(self, job, path):
        """
        Check if is an output path for this job or a file in the output's extra files path.
        """
        da_lists = [job.output_datasets, job.output_library_datasets]
        for da_list in da_lists:
            for job_dataset_association in da_list:
                dataset = job_dataset_association.dataset
                if not dataset:
                    continue
                if os.path.abspath(dataset.get_file_name()) == os.path.abspath(path):
                    return True
                elif util.in_directory(path, dataset.extra_files_path):
                    return True
        return False

    def __in_working_directory(self, job, path, app):
        working_directory = app.object_store.get_filename(
            job, base_dir="job_work", dir_only=True, extra_dir=str(job.id)
        )
        return util.in_directory(path, working_directory)


class JobFilesAPIController(BaseGalaxyAPIController):
    """
    Legacy WSGI endpoints dedicated to TUS uploads.

    TUS upload endpoints work in tandem with the WSGI middleware `TusMiddleware` from the `tuswsgi` package. Both
    WSGI middlewares and endpoints are injected into the FastAPI app after FastAPI routes as a single sub-application
    `wsgi_handler` using `app.mount("/", wsgi_handler)`, meaning that requests are passed to the `wsgi_handler`
    sub-application (and thus to `TusMiddleware`) only if there was no FastAPI endpoint defined to handle them.

    Therefore, these legacy WSGI endpoints cannot be migrated to FastAPI unless `TusMiddleware` is migrated to ASGI.
    """

    @expose_api_anonymous_and_sessionless
    def tus_patch(self, trans, **kwds):
        """
        Exposed as PATCH /api/job_files/resumable_upload.

        I think based on the docs, a separate tusd server is needed for job files if
        also hosting one for use facing uploads.

        Setting up tusd for job files should just look like (I think):

        `tusd -host localhost -port 1080 -upload-dir=<galaxy_root>/database/tmp`

        See more discussion of checking upload access, but we shouldn't need the
        API key and session stuff the user upload tusd server should be configured with.

        Also shouldn't need a hooks endpoint for this reason but if you want to add one
        the target CLI entry would be `-hooks-http=<galaxy_url>/api/job_files/tus_hooks`
        and the action is featured below.

        I would love to check the job state with `__authorize_job_access` on the first
        POST but it seems like `TusMiddleware` doesn't default to coming in here for that
        initial POST the way it does for the subsequent PATCHes. Ultimately, the upload
        is still authorized before the write done with POST `/api/jobs/<job_id>/files`
        so I think there is no route here to mess with user data - the worst of the security
        issues that can be caused is filling up the sever with needless files that aren't
        acted on. Since this endpoint is not meant for public consumption - all the job
        files stuff and the TUS server should be blocked to public IPs anyway and restricted
        to your Pulsar servers and similar targeting could be accomplished with a user account
        and the user facing upload endpoints.
        """
        ...
        return None

    @expose_api_anonymous_and_sessionless
    def tus_hooks(self, trans, **kwds):
        """
        No-op but if hook specified the way we do for user upload it would hit this action.

        Exposed as PATCH /api/job_files/tus_hooks and documented in the docstring for tus_patch.
        """
        ...
        return None

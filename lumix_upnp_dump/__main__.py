import dataclasses
import enum
import functools
import itertools
import logging
import pathlib
import re
import shutil
import string
import subprocess
import tempfile
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Iterator,
    List,
    NamedTuple,
    NoReturn,
    Optional,
    Union,
)

import configargparse
import integv
import rawpy
import requests
import upnpclient as upnp
from didl_lite import didl_lite
from PIL import Image

from lumix_upnp_dump.more_argparse import PreserveWhiteSpaceWrapRawTextHelpFormatter

logging.basicConfig(
    level=logging.INFO,
    format=("%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s"),
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


config_parser = configargparse.ArgParser(
    formatter_class=PreserveWhiteSpaceWrapRawTextHelpFormatter,
    config_file_parser_class=configargparse.TomlConfigParser(["lumix-upnp-dump"]),
)
config_parser.add_argument("-c", "--config-file", is_config_file=True, help="Config file path")
config_parser.add_argument(
    "-o",
    "--output-dir",
    required=True,
    help="Directory where the photos should be saved",
    type=pathlib.Path,
)
config_parser.add_argument(
    (arg_flag := "--command-after-finish"),
    required=False,
    help=(
        "A shell command to run when downloading media from a camera is finished. "
        "Also run if downloading was interrupted. "
        "The command can include the following special tags which will be replaced by appropriate values when run:"
        "\n  - ${camera}: the camera name"
        "\n  - ${n}: number of media files fetched (a picture is only counted once even if both JPEG and RAW were saved)"  # noqa
        "\n  - ${total}: total number of media files on the device prior to download or '-' if unknown"  # noqa
        "\nFor example:"
        "\n"
        "\n  %(prog)s [...] "
        + arg_flag
        + " 'echo Downloaded ${n}/${total} media files from ${camera} >> /tmp/lumix-dump.log'"
    ),
    type=str,
)


class Config(NamedTuple):
    config_file: str | None
    output_dir: pathlib.Path
    command_after_finish: str | None  # this is the unescaped raw command, as passed in command line


class ExecutionContext:
    def __init__(self, config: Config) -> None:
        self.config = config

    def run_command_after_finish(self, n: int, total_items: int | None, camera_name: str) -> None:
        if self._command_after_finish_template is None:
            return
        command_string = self._command_after_finish_template.safe_substitute(
            dict(
                n=n,
                camera=camera_name,
                total=total_items if total_items is not None else "-",
            )
        )
        log.info("Running a command after a finished download: %s", command_string)
        cmd = ["sh", "-c", command_string]
        subprocess.run(cmd)

    @functools.cached_property
    def _command_after_finish_template(self) -> string.Template | None:
        if self.config.command_after_finish is None:
            return None
        return string.Template(self.config.command_after_finish)


def run(config: Config) -> NoReturn:
    context = ExecutionContext(config)
    target_directory = config.output_dir
    target_directory.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading media to {target_directory}")
    log.info("Started cameras discovery")
    previously_discovered_cameras = CameraList.empty()
    while True:
        cameras = discover_cameras()
        for camera in cameras:
            if camera in previously_discovered_cameras:
                # we don't want to keep downloading photos from the same camera over
                # and over again, so we only do this once, after a camera connects to
                # the network
                continue
            log.info(f"Detected a camera: {camera.friendly_name}. Downloading media.")
            download_media_from_camera(context, camera, target_directory)

        previously_discovered_cameras = cameras


class CameraList:
    def __init__(self, cameras: List[upnp.Device]) -> None:
        self._cameras = cameras

    def __iter__(self) -> Iterator[upnp.Device]:
        return iter(self._cameras)

    def __contains__(self, other: upnp.Device) -> bool:
        return any(
            other.location == c.location and other.friendly_name == c.friendly_name
            for c in self._cameras
        )

    @classmethod
    def empty(cls) -> "CameraList":
        return cls([])


def is_lumix_camera(device: upnp.Device) -> bool:
    return (
        device.manufacturer == "Panasonic"
        and "MediaServer" in device.device_type
        and "lumix" in device.model_name.lower()
    )


def discover_cameras() -> CameraList:
    devices: List[upnp.Device] = upnp.discover(timeout=1)
    return CameraList([d for d in devices if is_lumix_camera(d)])


@dataclasses.dataclass
class Photo:
    """
    Sometimes there's a RAW available, which is not listed.
    e.g. the following was returned
        http://192.168.0.215:50001/DO1050344.JPG
        http://192.168.0.215:50001/DT1050344.JPG
        http://192.168.0.215:50001/DS1050344.JPG
    but also available was
        http://192.168.0.215:50001/DO1050344.RW2
    """

    _didl_image: didl_lite.ImageItem

    _BEST_JPEG_RE = re.compile(r"/do\w+\.jpe?g$", re.IGNORECASE)  # /DO1050344.JPG
    _JPEG_SUFFIX_RE = re.compile(r"\.jpe?g$", re.IGNORECASE)

    @property
    def name(self) -> str:
        return base_filename_from_url(self.best_jpeg_url)

    @property
    def object_id(self) -> str:
        # TODO: verify if should be str or int
        return self._didl_image.id

    @property
    def raw_url(self) -> str:
        return Photo._JPEG_SUFFIX_RE.sub(".RW2", self.best_jpeg_url)

    @property
    def best_jpeg_url(self) -> str:
        maybe_best_image = [
            res
            for res in self._didl_image.res
            if res.uri is not None and Photo._BEST_JPEG_RE.search(res.uri)
        ]
        sorted_by_size = sorted(
            self._didl_image.res,
            key=lambda res: float(res.size or "0"),
            reverse=True,
        )
        for image in itertools.chain(maybe_best_image, sorted_by_size):
            if image.uri is not None:
                return image.uri
        raise RuntimeError("Couldn't find any image's paths")

    def __str__(self) -> str:
        return f"<Photo: {self.name}>"


@dataclasses.dataclass
class Movie:
    _didl_movie: didl_lite.Movie
    _MP4_RE = re.compile(r"/do\w+\.mp4$", re.IGNORECASE)  # /DO1050345.MP4

    @property
    def name(self) -> str:
        return base_filename_from_url(self.mp4_url)

    @property
    def object_id(self) -> str:
        return self._didl_movie.id

    @property
    def mp4_url(self) -> str:
        uris = (res.uri for res in self._didl_movie.res if res.uri is not None)
        movies_uris = [uri for uri in uris if Movie._MP4_RE.search(uri)]
        return movies_uris[0]

    def __str__(self) -> str:
        return f"<Movie: {self.name}>"


def base_filename_from_url(url: str) -> str:
    return url.split("/")[-1].rsplit(".", maxsplit=1)[0]


class DownloadTargetLocations:
    def __init__(self, base_dir: pathlib.Path) -> None:
        self._base_dir = base_dir
        self._paths: Dict[str, bool] = dict()

    def register(self, path: str) -> pathlib.Path:
        self._paths[path] = False
        return self._base_dir / path

    def mark_completed(self, path: str) -> None:
        self._paths[path] = True

    def delete_not_completed(self) -> None:
        for p, v in self._paths.items():
            if not v:
                file_path = self._base_dir / p
                if file_path.exists():
                    file_path.unlink()


class FileVerificationError(Exception):
    pass


def verify_image(file_path: pathlib.Path) -> None:
    try:
        with Image.open(file_path) as img:
            img.verify()
        # verify() closes the file, so we need to reopen to check if we can actually load it
        with Image.open(file_path) as img:
            img.load()
    except Exception as e:
        raise FileVerificationError(f"Image verification failed for {file_path.name}: {e}") from e


def verify_raw(file_path: pathlib.Path) -> None:
    try:
        with rawpy.imread(str(file_path)) as raw:
            # Attempt to postprocess the image to verify it's readable
            raw.postprocess()
    except Exception as e:
        raise FileVerificationError(f"RAW verification failed for {file_path.name}: {e}") from e


def verify_video(file_path: pathlib.Path) -> None:
    try:
        is_valid = integv.verify(str(file_path))
        if not is_valid:
            raise FileVerificationError(f"Video verification failed for {file_path.name}")
    except FileVerificationError:
        raise
    except Exception as e:
        raise FileVerificationError(f"Video verification failed for {file_path.name}: {e}") from e


def download_media_from_camera(
    context: ExecutionContext,
    camera: upnp.Device,
    target_directory: pathlib.Path,
) -> None:
    content_directory = camera["ContentDirectory"]
    media_iterator = UpnpMediaIterator(content_directory)
    target_locations = None
    nb_downloaded = 0
    try:
        for media_item in media_iterator:
            # We create a DownloadTargetLotions object per media_item, to only delete the locations associated with
            # that media item if for some reason the download fails.
            target_locations = DownloadTargetLocations(target_directory)
            log.info(f"Started downloading {media_item}")
            if isinstance(media_item, Photo):
                downloaded = download_photo(media_item, target_locations, WhatToDownload.BOTH)
                if downloaded is not WhatWasDownloaded.NONE:
                    content_directory.DestroyObject(ObjectID=media_item.object_id)
                    media_iterator.notify_produced_item_was_deleted()
                    log.info(f"Deleted {media_item} from camera")
                    nb_downloaded += 1
                else:
                    log.info(f"Could not download {media_item}")
            elif isinstance(media_item, Movie):
                download_movie(media_item, target_locations)
                content_directory.DestroyObject(ObjectID=media_item.object_id)
                media_iterator.notify_produced_item_was_deleted()
                log.info(f"Downloaded and deleted {media_item} from camera")
                nb_downloaded += 1
        log.info(f"Download from {camera.friendly_name} finished")
    except FileVerificationError as e:
        log.exception("Error validating file upon download")
        if target_locations is not None:
            target_locations.delete_not_completed()
    except requests.exceptions.ChunkedEncodingError:
        log.info("Media download was interrupted")
        # download was interrupted (e.g. camera button pressed)
        # delete incomplete files from disk
        if target_locations is not None:
            target_locations.delete_not_completed()
    except requests.exceptions.RequestException as e:
        log.warning(f"Connection to camera lost: {e}")
        log.info("Camera may have powered off or gone to sleep. Files downloaded so far have been saved.")
        # Don't delete files on connection errors - this might have happened during DestroyObject operation, once
        # the camera has already destroyed items.
    finally:
        context.run_command_after_finish(
            n=nb_downloaded,
            total_items=media_iterator.total_items,
            camera_name=camera.friendly_name,
        )


def download_movie(movie: Movie, target_locations: DownloadTargetLocations) -> bool:
    download_file(movie.mp4_url, target_locations, verify_fn=verify_video)


class WhatWasDownloaded(enum.Enum):
    NONE = enum.auto()
    JUST_JPEG = enum.auto()
    JUST_RAW = enum.auto()
    BOTH = enum.auto()

    def __or__(self, other: Any) -> "WhatWasDownloaded":
        if not isinstance(other, WhatWasDownloaded):
            raise TypeError(f"Expected {WhatWasDownloaded}, got {type(other)}")
        if self is WhatWasDownloaded.NONE:
            return other
        if other is WhatWasDownloaded.NONE:
            return self
        if self == other:
            return self
        return WhatWasDownloaded.BOTH


class WhatToDownload(enum.Enum):
    JUST_JPEG = enum.auto()
    JUST_RAW = enum.auto()
    BOTH = enum.auto()


def download_photo(
    photo: Photo,
    target_locations: DownloadTargetLocations,
    what_to_download: WhatToDownload,
) -> WhatWasDownloaded:
    downloaded = WhatWasDownloaded.NONE
    if what_to_download in {WhatToDownload.JUST_RAW, WhatToDownload.BOTH}:
        try:
            download_file(photo.raw_url, target_locations, verify_fn=verify_raw)
            downloaded |= WhatWasDownloaded.JUST_RAW
            log.info(f"Downloaded RAW: {photo.name}")
        except requests.HTTPError:
            # it's fine, raw is not always there
            pass

    if what_to_download in {WhatToDownload.JUST_JPEG, WhatToDownload.BOTH}:
        try:
            download_file(photo.best_jpeg_url, target_locations, verify_fn=verify_image)
            downloaded |= WhatWasDownloaded.JUST_JPEG
            log.info(f"Downloaded JPEG: {photo.name}")
        except requests.HTTPError:
            # it's fine, jpeg is also not always there
            pass
    return downloaded


def download_file(
    url: str,
    target_locations: DownloadTargetLocations,
    verify_fn: Optional[Callable[[pathlib.Path], None]] = None,
) -> None:
    output_file = url.rsplit("/", maxsplit=1)[1]
    target_path = target_locations.register(output_file)

    temp_path = pathlib.Path(tempfile.gettempdir()) / f"lumix_temp_{output_file}"

    try:
        # Download to temp location
        with requests.get(url, stream=True) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        if verify_fn is not None:
            log.info("Fetched file, verifying")
            verify_fn(temp_path)

        # Move to final location if verification passed (or no verification needed)
        # Use copyfile + unlink to handle cross-filesystem moves reliably
        # (shutil.copy does not work with CIFS mounts, for instance).
        shutil.copyfile(str(temp_path), str(target_path))
        temp_path.unlink()
        target_locations.mark_completed(output_file)
    except FileVerificationError as e:
        log.warning(f"File verification failed for {output_file}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        raise
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


class UpnpMediaIterator:
    def __init__(
        self,
        content_directory: "upnp.ContentDirectory",
    ) -> None:
        self._content_directory = content_directory
        self._num_deleted_items = 0
        self._total_items: int | None = None

    def notify_produced_item_was_deleted(self) -> None:
        self._num_deleted_items += 1

    @property
    def total_items(self) -> int | None:
        return self._total_items

    def __iter__(self) -> Generator[Union[Movie, Photo], None, None]:
        last_index = 0
        request_at_once = 10
        while True:
            # If we delete items that were produced by this generator, subsequent items
            # are shifted left (10th item becomes 9th and so on), so we should adjust
            # the index to take this into account.
            starting_index = last_index - self._num_deleted_items
            try:
                upnp_response = self._content_directory.Browse(
                    ObjectID=0,
                    BrowseFlag="BrowseDirectChildren",
                    Filter="*",
                    StartingIndex=starting_index,
                    RequestedCount=request_at_once,
                    SortCriteria="",
                )
            except upnp.soap.SOAPError:
                # There was no content
                return
            if last_index == 0:
                total_matches: int = upnp_response["TotalMatches"]
                self._total_items = total_matches
                log.info(f"Found {total_matches} media files in total")
            returned: int = upnp_response["NumberReturned"]
            didl_lite_result: str = upnp_response["Result"]
            if not returned:
                break
            items = didl_lite.from_xml_string(didl_lite_result)
            for item in items:
                if isinstance(item, didl_lite.ImageItem):
                    yield Photo(item)
                elif isinstance(item, didl_lite.Movie):
                    yield Movie(item)
            last_index += returned


def main() -> None:
    config = Config(**vars(config_parser.parse_args()))
    run(config)


if __name__ == "__main__":
    main()

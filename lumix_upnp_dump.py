import dataclasses
import enum
import logging
import os
import pathlib
import re
from typing import Dict, Generator, Iterator, List, NoReturn, Union, NamedTuple

import configargparse
import requests
import upnpclient as upnp
from didl_lite import didl_lite

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

config_parser = configargparse.ArgParser()
config_parser.add_argument(
    "-c", "--config-file", is_config_file=True, help="config file path"
)
config_parser.add_argument(
    "-o",
    "--output-dir",
    required=True,
    help="directory where the photos should be saved",
    type=pathlib.Path,
)


class Config(NamedTuple):
    output_dir: pathlib.Path
    # we don't list config_file here, as that's the internals of configargparse


def main(config: Config) -> NoReturn:
    target_directory = config.output_dir
    target_directory.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading media to {target_directory}")
    log.info("Started cameras discovery")
    previously_discovered_cameras = CameraList.empty()
    while True:
        cameras = discover_cameras()
        for camera in cameras:
            if camera in previously_discovered_cameras:
                # we don't want to keep downloading photos from the same camera over and over again, so we only do this
                # once, after a camera connects to the network
                continue
            log.info(f"Detected a camera: {camera.friendly_name}. Downloading media.")
            download_media_from_camera(camera, target_directory)
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
            self._didl_image.res, key=lambda res: float(res.size or "0"), reverse=True
        )
        return (maybe_best_image or sorted_by_size)[0].uri or "TODO"

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
                os.remove(self._base_dir / p)


def download_media_from_camera(
    camera: upnp.Device, target_directory: pathlib.Path
) -> None:
    content_directory = camera["ContentDirectory"]
    media = iter_media(content_directory)
    target_locations = None
    try:
        for media_item in media:
            target_locations = DownloadTargetLocations(target_directory)
            log.info(f"Started downloading {media_item}")
            if isinstance(media_item, Photo):
                downloaded = download_photo(
                    media_item, target_locations, WhatToDownload.BOTH
                )
                if downloaded is not WhatWasDownloaded.NONE:
                    content_directory.DestroyObject(ObjectID=media_item.object_id)
                    log.info(f"Deleted {media_item} from camera")
                else:
                    log.info(f"Could not download {media_item}")
            elif isinstance(media_item, Movie):
                download_movie(media_item, target_locations)
                content_directory.DestroyObject(ObjectID=media_item.object_id)
                log.info(f"Downloaded and deleted {media_item} from camera")
        log.info(f"Download from {camera.friendly_name} finished")
    except requests.exceptions.ChunkedEncodingError:
        log.info("Media download was interrupted")
        # download was interrupted (e.g. camera button pressed)
        # delete incomplete files from disk
        if target_locations is not None:
            target_locations.delete_not_completed()


def download_movie(movie: Movie, target_locations: DownloadTargetLocations) -> None:
    download_file(movie.mp4_url, target_locations)


class WhatWasDownloaded(enum.Enum):
    NONE = enum.auto()
    JUST_JPEG = enum.auto()
    JUST_RAW = enum.auto()
    BOTH = enum.auto()


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
            download_file(photo.raw_url, target_locations)
            downloaded = WhatWasDownloaded.JUST_RAW
            log.info(f"Downloaded RAW: {photo.name}")
        except requests.HTTPError:
            # it's fine, raw is not always there
            pass

    if what_to_download in {WhatToDownload.JUST_JPEG, WhatToDownload.BOTH}:
        try:
            download_file(photo.best_jpeg_url, target_locations)
            downloaded = (
                WhatWasDownloaded.BOTH
                if downloaded == WhatWasDownloaded.JUST_RAW
                else WhatWasDownloaded.JUST_JPEG
            )
            log.info(f"Downloaded JPEG: {photo.name}")
        except requests.HTTPError:
            # it's fine, jpeg is also not always there
            pass
    return downloaded


def download_file(url: str, target_locations: DownloadTargetLocations) -> None:
    output_file = url.rsplit("/", maxsplit=1)[1]
    target_path = target_locations.register(output_file)
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    target_locations.mark_completed(output_file)


def iter_media(
    content_directory: "upnp.ContentDirectory",
) -> Generator[Union[Movie, Photo], None, None]:
    last_index = 0
    request_at_once = 10
    while True:
        try:
            upnp_response = content_directory.Browse(
                ObjectID=0,
                BrowseFlag="BrowseDirectChildren",
                Filter="*",
                StartingIndex=last_index,
                RequestedCount=request_at_once,
                SortCriteria="",
            )
        except upnp.soap.SOAPError:
            # There was no content
            return
        if last_index == 0:
            total_matches: int = upnp_response["TotalMatches"]
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


if __name__ == "__main__":
    config = config_parser.parse_args()
    main(config)

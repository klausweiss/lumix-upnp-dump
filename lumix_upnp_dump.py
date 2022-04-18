import dataclasses
import enum
import pathlib
import re
from typing import List, NoReturn, Generator
import logging
import requests
import upnpclient as upnp
from didl_lite import didl_lite

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main() -> NoReturn:
    target_directory = pathlib.Path("photos")
    target_directory.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading media to {target_directory}")
    log.info("Started cameras discovery")
    while True:
        cameras = discover_cameras()
        for camera in cameras:
            log.info(f"Detected a camera: {camera.friendly_name}. Downloading media.")
            download_media_from_camera(camera, target_directory)
            return


def is_lumix_camera(device: upnp.Device) -> bool:
    return (
        device.manufacturer == "Panasonic"
        and "MediaServer" in device.device_type
        and "lumix" in device.model_name.lower()
    )


def discover_cameras() -> List[upnp.Device]:
    devices: List[upnp.Device] = upnp.discover(timeout=1)
    return [d for d in devices if is_lumix_camera(d)]


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
        return self.best_jpeg_url.split("/")[-1].rsplit(".", maxsplit=1)[0]

    @property
    def object_id(self) -> str:
        return self._didl_image.id

    @property
    def raw_url(self) -> str:
        return Photo._JPEG_SUFFIX_RE.sub(".RW2", self.best_jpeg_url)

    @property
    def best_jpeg_url(self) -> str:
        maybe_best_image = [
            res for res in self._didl_image.res if Photo._BEST_JPEG_RE.search(res.uri)
        ]
        sorted_by_size = sorted(
            self._didl_image.res, key=lambda res: float(res.size or "0"), reverse=True
        )
        return (maybe_best_image or sorted_by_size)[0].uri

    def __str__(self) -> str:
        return f"<Photo: {self.name}>"


@dataclasses.dataclass
class Movie:
    _didl_movie: didl_lite.Movie
    _MP4_RE = re.compile(r"/do\w+\.mp4$", re.IGNORECASE)  # /DO1050345.MP4

    @property
    def name(self) -> str:
        return self.mp4_url.split("/")[-1].rsplit(".", maxsplit=1)[0]

    @property
    def object_id(self) -> str:
        return self._didl_movie.id

    @property
    def mp4_url(self) -> str:
        movies_res = [
            res for res in self._didl_movie.res if Movie._MP4_RE.search(res.uri)
        ]
        return movies_res[0].uri

    def __str__(self) -> str:
        return f"<Movie: {self.name}>"


def download_media_from_camera(
    camera: upnp.Device, target_directory: pathlib.Path
) -> None:
    content_directory = camera["ContentDirectory"]
    media = iter_media(content_directory)
    try:
        for media_item in media:
            log.info(f"Started downloading {media_item}")
            if isinstance(media_item, Photo):
                downloaded = download_photo(media_item, target_directory)
                if downloaded is not WhatWasDownloaded.NONE:
                    content_directory.DestroyObject(ObjectID=media_item.object_id)
                    log.info(
                        f"Downloaded {downloaded} and deleted {media_item} from camera"
                    )
            elif isinstance(media_item, Movie):
                download_movie(media_item, target_directory)
                content_directory.DestroyObject(ObjectID=media_item.object_id)
                log.info(f"Downloaded and deleted {media_item} from camera")
    except requests.exceptions.ChunkedEncodingError:
        pass  # download was interrupted (e.g. camera button pressed)
        # TODO: delete incomplete files from disk
    except upnp.soap.SOAPError:
        pass  # no content


def download_movie(movie: Movie, target_directory: pathlib.Path) -> None:
    download_file(movie.mp4_url, target_directory)


class WhatWasDownloaded(enum.Enum):
    NONE = enum.auto()
    JUST_JPEG = enum.auto()
    JUST_RAW = enum.auto()
    BOTH = enum.auto()


def download_photo(photo: Photo, target_directory: pathlib.Path) -> WhatWasDownloaded:
    downloaded = WhatWasDownloaded.NONE
    try:
        # TODO: add flag to skip RAWs (e.g. GX7 does not support this)
        download_file(photo.raw_url, target_directory)
        downloaded = WhatWasDownloaded.JUST_RAW
    except requests.HTTPError:
        # it's fine, raw is not always there
        pass
    try:
        download_file(photo.best_jpeg_url, target_directory)
        downloaded = (
            WhatWasDownloaded.BOTH
            if downloaded == WhatWasDownloaded.JUST_RAW
            else WhatWasDownloaded.JUST_JPEG
        )
    except requests.HTTPError:
        # it's fine, jpeg is also not always there
        pass
    return downloaded


def download_file(url: str, target_directory: pathlib.Path) -> None:
    local_filename = url.split("/")[-1]
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(target_directory / local_filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)


def iter_media(content_directory) -> Generator[Photo, None, None]:
    last_index = 0
    request_at_once = 10
    while True:
        upnp_response = content_directory.Browse(
            ObjectID=0,
            BrowseFlag="BrowseDirectChildren",
            Filter="*",
            StartingIndex=last_index,
            RequestedCount=request_at_once,
            SortCriteria="",
        )  # also has an int "TotalMatches" key
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
    main()

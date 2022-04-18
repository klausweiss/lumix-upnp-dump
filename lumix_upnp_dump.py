import dataclasses
import enum
import pathlib
import re
from typing import List, NoReturn, Generator

import requests
import upnpclient as upnp
from didl_lite import didl_lite


def main() -> NoReturn:
    target_directory = pathlib.Path("photos")
    target_directory.mkdir(parents=True, exist_ok=True)
    while True:
        cameras = discover_cameras()
        for camera in cameras:
            download_camera_photos(camera, target_directory)
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


def download_camera_photos(camera: upnp.Device, target_directory: pathlib.Path) -> None:
    content_directory = camera["ContentDirectory"]
    connection_manager = camera["ConnectionManager"]
    photos = list(list_photos(content_directory))
    try:
        for photo in photos:
            downloaded = download_photo(photo, target_directory)
            if downloaded is not WhatWasDownloaded.NONE:
                content_directory.DestroyObject(ObjectID=photo.object_id)
    except requests.exceptions.ChunkedEncodingError:
        pass  # download was interrupted (e.g. camera button pressed)
        # TODO: delete incomplete files from disk
    except upnp.soap.SOAPError:
        pass  # no content


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


def list_photos(content_directory) -> Generator[Photo, None, None]:
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
            if not isinstance(item, didl_lite.ImageItem):
                continue
            yield Photo(item)
        last_index += returned


if __name__ == "__main__":
    main()

from typing import List, Literal, Union, overload

from . import soap

class UpnpResponse:
    @overload
    def __getitem__(self, key: Literal["Result"]) -> str: ...
    @overload
    def __getitem__(self, key: Literal["TotalMatches"]) -> int: ...
    @overload
    def __getitem__(self, key: Literal["NumberReturned"]) -> int: ...

class ContentDirectory:
    def DestroyObject(self, ObjectID: str) -> None: ...
    def Browse(
        self,
        ObjectID: int,
        # TODO: more options for these two
        BrowseFlag: Union[Literal["BrowseDirectChildren"]],
        Filter: Union[Literal["*"]],
        StartingIndex: int,
        RequestedCount: int,
        SortCriteria: str,
    ) -> UpnpResponse: ...

class Device:
    friendly_name: str
    location: str
    manufacturer: str
    device_type: str
    model_name: str

    def __getitem__(self, key: Literal["ContentDirectory"]) -> ContentDirectory: ...

def discover(*, timeout: int) -> List[Device]: ...

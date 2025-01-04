import pytest

from lumix_upnp_dump.__main__ import WhatWasDownloaded


@pytest.mark.parametrize(
    "self, other, expected",
    [
        (WhatWasDownloaded.NONE, WhatWasDownloaded.NONE, WhatWasDownloaded.NONE),
        (WhatWasDownloaded.NONE, WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.JUST_JPEG),
        (WhatWasDownloaded.NONE, WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.JUST_RAW),
        (WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.NONE, WhatWasDownloaded.JUST_RAW),
        (WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.BOTH),
        (WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.JUST_RAW),
        (WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.NONE, WhatWasDownloaded.JUST_JPEG),
        (WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.JUST_JPEG),
        (WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.BOTH),
        (WhatWasDownloaded.BOTH, WhatWasDownloaded.NONE, WhatWasDownloaded.BOTH),
        (WhatWasDownloaded.BOTH, WhatWasDownloaded.JUST_JPEG, WhatWasDownloaded.BOTH),
        (WhatWasDownloaded.BOTH, WhatWasDownloaded.JUST_RAW, WhatWasDownloaded.BOTH),
    ],
)
def test_what_was_downloaded(self, other, expected):
    assert self | other == expected
    self |= other
    assert self == expected

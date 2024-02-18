import argparse
import textwrap as _textwrap
import re


class PreserveWhiteSpaceWrapRawTextHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """
    Adapted from https://stackoverflow.com/a/35925919 by Kordi
    Licensed under CC BY-SA 3.0, see https://creativecommons.org/licenses/by-sa/3.0/

    Changes:
    - renamed variables and methods
    - made more idiomatic
    - simplified regex
    - added type annotations
    """

    def _split_lines(self, text: str, width: int) -> list[str]:
        input_lines = text.splitlines()
        output_lines = list()
        for line in input_lines:
            search = re.search(r"\s*[0-9\-]*\.?\s*", line)
            if not line.strip():
                output_lines.append("")
            elif search:
                whitespace_width = search.end()
                wrapped_iter = iter(_textwrap.wrap(line, width))
                output_lines.append(next(wrapped_iter))
                output_lines.extend(
                    [
                        self._prefix_with_spaces(whitespace_width, wrapped_line)
                        for wrapped_line in wrapped_iter
                    ]
                )
        return output_lines

    @staticmethod
    def _prefix_with_spaces(whitespace_width: int, text: str) -> str:
        return (" " * whitespace_width) + text

"""Read the current native UUID only from the TUI's reserved footer row."""

import re
import uuid


UUID = re.compile(r"(?<![0-9a-f-])[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?![0-9a-f-])", re.I)


def footer_thread_id(screen) -> str | None:
    if screen.number_of_lines < 2:
        return None
    # Pinned CLI 0.163/0.164 reserves the last two rows for status and key hints.
    # Do not search message history or the composer for identity-shaped text.
    row = screen.line(screen.number_of_lines - 2).string.replace("\0", " ")
    if row.lstrip().startswith(("›", ">")):
        return None
    matches = UUID.findall(row)
    if len(matches) != 1:
        return None
    identity = uuid.UUID(matches[0])
    return str(identity) if identity.version == 7 else None

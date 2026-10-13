"""The Discord interface: everything that turns the core's plain data into
Discord, behind the door (core/surface.py).

- `surface.py`: the door's verbs, on the shared client
- `render.py`: a Card as Discord components, and a press as an answer

Moving here in later stages (docs/INTERFACE.md): the events of main.py, the
Context of a typed word, slash commands, the #bot-log embeds.
"""
from core import surface as door
from interfaces.discord import surface


def bind() -> None:
    """Say that Discord is the interface. Before anything is sent."""
    door.bind(surface)

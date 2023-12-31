from typing import Optional, Any
from typing_extensions import Annotated
import typer
from rp2040_flashtool.util import BlInfo

def _rename(name):
    def decorator(f):
        f.__name__ = name
        return f
    return decorator

@_rename("integer")
def parse_integer(value: str | int):
    if isinstance(value, int):
        return value
    try:
        return int(value, 10)
    except ValueError:
        pass
    try:
        return int(value, 16)
    except ValueError:
        pass
    try:
        return int(value, 2)
    except ValueError:
        pass
    raise ValueError(f"'{value}' is not a number")

port = Annotated[
    Optional[str], 
    typer.Option(
        "--port", "-p",
        help="Name of the serial port (i.e. 'COM3'), autodetect if not specified")]

out_file = Annotated[
    str, 
    typer.Option(
        "--out", "-o",
        help="Name of the output file")]

in_file = Annotated[
    str, 
    typer.Option(
        "--in", "-i",
        help="Name of the input file")]

addr = Annotated[
    int, 
    typer.Option(
        "--addr", "-a",
        parser=parse_integer,
        help="Starting address to read from")]

flash_addr = Annotated[
    Optional[int], 
    typer.Option(
        "--addr", "-a",
        parser=parse_integer,
        help="Starting address to write from")]

boot_addr = Annotated[
    Optional[int], 
    typer.Option(
        "--addr", "-a",
        parser=parse_integer,
        help="Address to jump to")]

boot = Annotated[
    bool, 
    typer.Option(
        "--boot", "-b",
        help="Boot into image after flashing")]

length = Annotated[
    Optional[int], 
    typer.Option(
        "--len", "-l",
        parser=parse_integer,
        help="Number of bytes to read, full flash range if not specified")]

bl_info = Annotated[
    Optional[BlInfo], 
    typer.Option(parser=lambda x: None, hidden=True)]
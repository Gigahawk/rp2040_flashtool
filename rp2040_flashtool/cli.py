from dataclasses import dataclass
from pathlib import Path
from time import sleep, time
import zlib
import rp2040_flashtool.type_hints as type_hints
from rp2040_flashtool.util import load_file, pad_len, BlInfo

from serial import Serial, SerialException
from serial.tools.list_ports import comports
import typer

app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]})

baudrate = 115200

def _serial(port: str):
    return Serial(port, baudrate=baudrate, timeout=1, write_timeout=1)

@app.command()
def sync(port: type_hints.port = None):
    print("Synchronizing with RP2040...")
    attempts = 5
    if port is not None:
        ports = [port]
    else:
        ports = [p.name for p in comports()]
    for p in ports:
        print(f"Trying to sync with port {p}")
        for idx in range(attempts):
            print(f"Attempt {idx + 1}")
            try:
                with _serial(p) as ser:
                    ser.write(b"SYNC")
                    sleep(0.1)
                    resp = ser.read_all()
                print(resp)
            except Exception as err:
                print(f"Failed to connect to {p}")
                print(err)
                continue
            if resp == b"SYNCPICO":
                print(f"Synchronized with port {p}")
                return p
    print("Could not find an RP2040 in bootloader mode")
    exit(1)

def send_cmd(
        port: str, 
        cmd: bytes, 
        args: bytes = b"", 
        timeout: float = 1,
        resp_size: int = 0):
    with _serial(port) as ser:
        ser.write(cmd)
        if args:
            ser.write(args)
        cmd_len = len(cmd) + len(args)
        total_len = cmd_len + 4 + resp_size
        resp = b""
        start = time()
        while time() - start < timeout:
            resp += ser.read_all()
            if resp[cmd_len:cmd_len + 4] == b"OKOK" and len(resp) >= total_len:
                break
        else:
            print("Error reading response from RP2040")
            print(resp)
            raise ValueError
        data = resp[cmd_len + 4:]
        return data

@app.command()
def info(port: type_hints.port = None):
    attempts = 3
    port = sync(port)
    print(f"Getting device info from port {port}")
    for _ in range(attempts):
        data = send_cmd(port, b"INFO", resp_size=24)
        bl_info = BlInfo.from_bytes(data)
        print(bl_info)
        break
    else:
        print(f"Failed to get info from port {port}")
        exit(1)
    return port, bl_info

def _read(port: str, addr: int, size: int):
    print(f"Reading {hex(size)} bytes from {hex(addr)}")
    args = (
        addr.to_bytes(length=4, byteorder="little") +
        size.to_bytes(length=4, byteorder="little")
    )
    data = send_cmd(port, b"READ", args, resp_size=size)
    if len(data) != size:
        print("RP2040 did not return correct number of bytes")
        print(data)
        raise ValueError
    expected_crc = zlib.crc32(data).to_bytes(length=4, byteorder="little")
    crc = send_cmd(port, b"CRCC", args, resp_size=4)
    if expected_crc != crc:
        print(f"Error: CRC mismatch, expected {expected_crc}, got {crc}")
        raise ValueError
    return data

@app.command()
def read(
        port: type_hints.port = None,
        out_file: type_hints.out_file = "out.bin",
        addr: type_hints.addr = None,
        length: type_hints.length = None):
    port, bl_info = info(port)
    if addr is None:
        addr = bl_info.flash_start
    if length is None:
        length = bl_info.flash_end - addr
    attempts = 3
    print(f"Downloading image from port {port} to {out_file}")
    print(
        f"Start address: {hex(addr)}\n"
        f"End address: {hex(addr + length)}\n"
        f"Length: {hex(length)}"
    )
    idx = 0
    with open(out_file, "wb") as f:
        while idx < length:
            read_size = min(bl_info.max_data_len, length - idx)
            for _ in range(attempts):
                try:
                    f.write(_read(port, addr + idx, read_size))
                    break
                except ValueError:
                    pass
            else:
                raise
            idx += read_size

def _erase(port: str, addr: int, size: int):
    print(f"Erasing {hex(size)} bytes from {hex(addr)}")
    args = (
        addr.to_bytes(length=4, byteorder="little") +
        size.to_bytes(length=4, byteorder="little")
    )
    send_cmd(port, b"ERAS", args, timeout=10)

@app.command()
def erase(
        port: type_hints.port = None,
        addr: type_hints.addr = None,
        length: type_hints.length = None,
        bl_info: type_hints.bl_info = None):
    if port is None or bl_info is None:
        port, bl_info = info(port)
    if addr is None:
        addr = bl_info.erase_start
    if length is None:
        length = bl_info.flash_end - addr
    attempts = 3
    print(f"Erasing data from port {port}")
    print(
        f"Start address: {hex(addr)}\n"
        f"End address: {hex(addr + length)}\n"
        f"Length: {hex(length)}"
    )
    if addr & (bl_info.sector_size - 1) or length & (bl_info.sector_size - 1):
        print(f"Address and length must be aligned to 4k")
        exit(1)
    idx = 0
    while idx < length:
        # TODO: This should work for all values?
        erase_size = min(0xfffff000, length - idx)
        for _ in range(attempts):
            try:
                _erase(port, addr + idx, erase_size)
                break
            except ValueError:
                pass
        else:
            raise
        idx += erase_size

def _write(port: str, addr: int, data: bytes):
    size = len(data)
    print(f"Writing {hex(size)} bytes to {hex(addr)}")
    args = (
        addr.to_bytes(length=4, byteorder="little") +
        size.to_bytes(length=4, byteorder="little") +
        data
    )
    crc = send_cmd(port, b"WRIT", args, timeout=10, resp_size=4)
    expected_crc = zlib.crc32(data).to_bytes(length=4, byteorder="little")
    if expected_crc != crc:
        print(f"Error: CRC mismatch, expected {expected_crc}, got {crc}")
        raise ValueError

@app.command()
def write(
        in_file: type_hints.in_file,
        port: type_hints.port = None,
        addr: type_hints.flash_addr = None,
        bl_info: type_hints.bl_info = None):
    if port is None or bl_info is None:
        port, bl_info = info(port)
    print(f"Uploading image {in_file} to port {port}")
    addr, data = load_file(in_file, bl_info, addr)
    length = len(data)
    print(
        f"Start address: {hex(addr)}\n"
        f"End address: {hex(addr + length)}\n"
        f"Length: {hex(length)}"
    )
    if addr < bl_info.flash_start:
        print(f"Error: start address {hex(addr)} is outside the writeable range")
        exit(1)
    if addr + length > bl_info.flash_end:
        print(f"Error: end address {hex(addr + length)} is outside the writeable range")
        exit(1)
    attempts = 3
    idx = 0
    while idx < length:
        write_size = min(bl_info.max_data_len, length - idx)
        for _ in range(attempts):
            try:
                _write(port, addr + idx, data[idx:idx + write_size])
                break
            except ValueError:
                pass
        else:
            raise
        idx += write_size

def _seal(port: str, addr: int, length: int, crc: bytes):
    args = (
        addr.to_bytes(length=4, byteorder="little") +
        length.to_bytes(length=4, byteorder="little") +
        crc
    )
    send_cmd(port, b"SEAL", args)

@app.command()
def flash(
        in_file: type_hints.in_file,
        port: type_hints.port = None,
        addr: type_hints.flash_addr = None,
        should_boot: type_hints.boot = False):
    port, bl_info = info(port)
    addr, data = load_file(in_file, bl_info, addr)
    erase_pad_length = pad_len(len(data), bl_info.erase_size)
    print(f"Need to pad erase by {hex(erase_pad_length)}")
    erase(port, addr, len(data) + erase_pad_length, bl_info)
    write(in_file, port, addr, bl_info)
    crc = zlib.crc32(data)
    print(f"Sealing RP2040 with CRC {hex(crc)}")
    crc = crc.to_bytes(length=4, byteorder="little")
    _seal(port, addr, len(data), crc)
    if should_boot:
        boot(port, addr, bl_info)

def _go(port: str, addr: int):
    args = addr.to_bytes(length=4, byteorder="little")
    try:
        send_cmd(port, b"GOGO", args)
    except SerialException:
        # USB serial will disconnect on jump
        print("RP2040 serial disconnected")

@app.command()
def boot(
        port: type_hints.port = None,
        addr: type_hints.boot_addr = None,
        bl_info: type_hints.bl_info = None):
    if port is None or bl_info is None:
        port, bl_info = info(port)
    print(f"Jumping to {hex(addr)}")
    _go(port, addr)
    

if __name__ == "__main__":
    app()
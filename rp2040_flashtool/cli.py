from time import sleep
import zlib
import rp2040_flashtool.type_hints as type_hints

from serial import Serial
from serial.tools.list_ports import comports
import typer

app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]})

baudrate = 115200
max_data_len = 1024
# TODO: figure this out later?
image_size = 1024*1024

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

def send_cmd(port: str, cmd: bytes, args: bytes):
    with _serial(port) as ser:
        ser.write(cmd)
        sleep(0.1)
        ser.read_all()
        ser.write(args)
        sleep(0.1)
        resp = ser.read_all()
        if resp[8:12] != b"OKOK":
            print("Error reading response from RP2040")
            print(resp)
            raise ValueError
        data = resp[12:]
        return data

def _read(port: str, addr: int, size: int):
    print(f"Reading {hex(size)} bytes from {hex(addr)}")
    args = (
        addr.to_bytes(length=4, byteorder="little") +
        size.to_bytes(length=4, byteorder="little")
    )
    data = send_cmd(port, b"READ", args)
    if len(data) != size:
        print("RP2040 did not return correct number of bytes")
        print(data)
        raise ValueError
    expected_crc = zlib.crc32(data).to_bytes(length=4, byteorder="little")
    crc = send_cmd(port, b"CRCC", args)
    if expected_crc != crc:
        print(f"Error: CRC mismatch, expected {expected_crc}, got {crc}")
        raise ValueError
    return data

@app.command()
def read(
        port: type_hints.port = None,
        out_file: type_hints.out_file = "out.bin",
        addr: type_hints.addr = 0x10000000,
        length: type_hints.length = None):
    if length is None:
        length = 0x20000000 - addr
    attempts = 3
    port = sync(port)
    print(f"Downloading image from port {port} to {out_file}")
    print(
        f"Start address: {hex(addr)}\n"
        f"End address: {hex(addr + length)}\n"
        f"Length: {hex(length)}"
    )
    idx = 0
    with open(out_file, "wb") as f:
        while idx < length:
            read_size = min(max_data_len, length - idx)
            for _ in range(attempts):
                try:
                    f.write(_read(port, addr + idx, read_size))
                    break
                except ValueError:
                    pass
            idx += read_size


if __name__ == "__main__":
    app()
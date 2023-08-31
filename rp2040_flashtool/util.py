from pathlib import Path
from dataclasses import dataclass
from elftools.elf.elffile import ELFFile

@dataclass
class BlInfo:
    flash_start: int
    flash_size: int
    erase_start: int
    erase_size: int
    write_size: int
    max_data_len: int

    @property
    def flash_end(self):
        return self.flash_start + self.flash_size
    
    @property
    def sector_size(self):
        return self.erase_size

    @classmethod
    def from_bytes(cls, data):
        data_len = 24   
        if len(data) != data_len:
            print(f"Error: info response must always be {data_len} bytes long")
            print(data)
            exit(1)
        flash_start = int.from_bytes(data[0:4], "little")
        flash_size = int.from_bytes(data[4:8], "little")
        erase_start = int.from_bytes(data[8:12], "little")
        erase_size = int.from_bytes(data[12:16], "little")
        write_size = int.from_bytes(data[16:20], "little")
        max_data_len = int.from_bytes(data[20:24], "little")
        return cls(
            flash_start, flash_size, erase_start, 
            erase_size, write_size, max_data_len)

    def __repr__(self):
        return (
            f"Flash start:     {hex(self.flash_start)}\n"
            f"Flash size:      {hex(self.flash_size)}\n"
            f"Erase start:     {hex(self.erase_start)}\n"
            f"Erase size:      {hex(self.erase_size)}\n"
            f"Write size:      {hex(self.write_size)}\n"
            f"Max data length: {hex(self.max_data_len)}\n"
        )

# Elf code based on 
# https://github.com/ConfedSolutions/pico-py-serial-flash/blob/main/flasher/elf.py

def _is_in_flash(addr, size: int, bl_info: BlInfo) -> bool:
    return (addr >= bl_info.flash_start) and (addr + size <= bl_info.flash_end)

def _is_in_header(vaddr, size, header):
    return (vaddr >= header['p_vaddr']) and (vaddr + size <= (header['p_vaddr'] + header['p_memsz']))

@dataclass
class Chunk:
    paddr: int
    data: bytes

def load_elf(file: str, bl_info: BlInfo):
    chunks = []
    with open(file, "rb") as stream:
        f = ELFFile(stream)
        count = 0
        for head_count in range(f.header["e_phnum"]):
            prog_head = f.get_segment(head_count).header
            p_paddr = prog_head["p_paddr"]
            p_memsz = prog_head["p_memsz"]
            if not _is_in_flash(p_paddr, p_memsz, bl_info):
                print(f"Warning: skipping program header {head_count}")
                print(f"Program header: {prog_head}")
                print(f"Start: {hex(p_paddr)}")
                print(f"End: {hex(p_paddr + p_memsz)}")
                print(f"Length: {hex(p_memsz)}")
                continue

            for sec_count in range(f.header["e_shnum"]):
                count += 1
                sec = f.get_section(sec_count)
                sec_size = sec.data_size
                sec_addr = sec.header["sh_addr"]
                in_header = _is_in_header(sec_addr, sec_size, prog_head)
                if sec_size > 0 and in_header:
                    prog_offset = sec_addr - prog_head["p_vaddr"]
                    data = sec.data()
                    chunk = Chunk(paddr=p_paddr + prog_offset, data=data)
                    chunks.append(chunk)
    
    chunks.sort(key=lambda x: x.paddr)

    min_addr = chunks[0].paddr
    max_addr = chunks[-1].paddr + len(chunks[-1].data)
    img_data = bytearray(max_addr - min_addr)
    for c in chunks:
        start = c.paddr - min_addr
        end = start + len(c.data)
        img_data[start:end] = c.data
    return min_addr, bytes(img_data)

def pad_len(length, align):
    next_aligned = ((length + align - 1) // align) * align
    return next_aligned - length

def load_file(file: str, bl_info: BlInfo, addr: int = None):
    file = Path(file)
    if file.suffix.lower() == ".elf":
        addr, data = load_elf(file, bl_info)
    elif file.suffix.lower() == ".bin":
        if addr is None:
            print("Error: base address must be provided for a .bin file")
            exit(1)
        with open(file, "rb") as f:
            data = f.read()
    else:
        print(f"Unsupported file type {file.suffix}")
        exit(1)
    length = len(data)
    pad_length = pad_len(length, bl_info.write_size)
    if pad_length:
        print(f"Need to pad image by {hex(pad_length)}")
        data += bytes(pad_length)
    return addr, data




        
    


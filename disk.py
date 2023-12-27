#!/usr/bin/env python3
# ========================================================================== #
#                                                                            #
#    disk - A parted/mkfs wrapper.                                           #
#                                                                            #
#    Copyright (C) 2022-2023  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #

import sys
import os
import re
import subprocess
import dataclasses
import shutil
import dask

@dataclasses.dataclass(frozen=True)
class _Mkfs:
    """
    Represents the parameters for creating a filesystem.
    """
    npart: int
    fs: str
    label: str
    reserved: str
    mount: str
    begin: int
    end: int

def _parse_script(script: str) -> tuple[list[list[str]], list[_Mkfs]]:
    """
    Parses the script and extracts the parted commands and filesystem parameters.

    Args:
        script: The script to parse.

    Returns:
        A tuple containing the parted commands and a list of _Mkfs objects representing the filesystem parameters.
    """
    parted: list[list[str]] = []
    filesystems: list[_Mkfs] = []
    npart = 1
    for line in filter(None, script.split("\n")):
        left: list[str]
        (left, right) = (line.split("#", 1) + [""])[:2]  # type: ignore
        left = left.split()  # type: ignore
        if "mkpart" in left and ("primary" in left or "logical" in left):
            assert len(left) >= 5, f"Too short mkpart command: {left}"
            params = dict(re.findall(r"(\w+)=([^\s]+)", right))
            filesystems.append(_Mkfs(
                npart=npart,
                fs=left[2],
                label=params.get("label", ""),
                reserved=params.get("reserved", ""),
                mount=params.get("mount", ""),
                begin=dask.utils.parse_bytes(left[3]),
                end=(0 if left[4] == "100%" else dask.utils.parse_bytes(left[4])),
            ))
            npart += 1
        parted.append(left)
    return (parted, filesystems)


def _make_partition(path: str, npart: int) -> str:
    """
    Creates the partition path based on the device path and partition number.

    Args:
        path: The device path.
        npart: The partition number.

    Returns:
        The partition path.
    """
    device = os.path.basename(path)
    return (f"{path}p{npart}" if device.startswith(("mmcblk", "loop")) else f"{path}{npart}")


def _run_commands(cmds: list[list[str]]) -> None:
    """
    Runs the specified commands.

    Args:
        cmds: A list of commands to run.
    """
    for cmd in cmds:
        print(f"CMD [ {sys.argv[0]} ] ==>", " ".join(cmd))
        sys.stdout.flush()
        try:
            executable = shutil.which(cmd[0])
            if executable is None:
                raise FileNotFoundError(f"Command not found: {cmd[0]}")
            subprocess.run([executable, *cmd[1:]], check=True)
        except subprocess.CalledProcessError:
            raise SystemExit(1)

def _format_disk(device_path: str) -> None:
    """
    Formats the disk using the parted commands.

    Args:
        device_path: The path of the disk device.
    """
    (parted, _) = _parse_script(sys.stdin.read())
    cmds: list[list[str]] = []
    for cmd in parted:
        cmds.append([shutil.which("parted"), device_path, "-a", "optimal", "-s", *cmd])
    cmds.append([shutil.which("partprobe"), device_path])
    cmds.append([shutil.which("partx"), "-vu", device_path])
    _run_commands(cmds)

def _mkfs_disk(device_path: str) -> None:
    """
    Creates filesystems on the disk partitions.

    Args:
        device_path: The path of the disk device.
    """
    (_, filesystems) = _parse_script(sys.stdin.read())
    cmds: list[list[str]] = []
    for mkfs in filesystems:
        cmd: list[str] = []
        if mkfs.fs == "fat32":
            cmd.append(shutil.which("mkfs.vfat"))
            if mkfs.label:
                cmd.extend(["-n", mkfs.label])
        elif mkfs.fs == "ext4":
            cmd.append(shutil.which("mkfs.ext4"))
            if mkfs.label:
                cmd.extend(["-L", mkfs.label])
            if mkfs.reserved:
                cmd.extend(["-m", mkfs.reserved])
        else:
            raise RuntimeError(f"Unsupported filesystem: {mkfs.fs}")
        cmd.append(_make_partition(device_path, mkfs.npart))
        cmds.append(cmd)
    cmds.append([shutil.which("partprobe"), device_path])
    cmds.append([shutil.which("partx"), "-vu", device_path])
    _run_commands(cmds)

def _mount_disk(device_path: str, prefix_path: str, mount: bool) -> None:
    """
    Mounts or unmounts the disk partitions.

    Args:
        device_path: The path of the disk device.
        prefix_path: The prefix path for mounting the partitions.
        mount: True to mount, False to unmount.
    """
    (_, filesystems) = _parse_script(sys.stdin.read())
    cmds: list[list[str]] = []
    filesystems = sorted(filesystems, key=(lambda mkfs: len(list(filter(None, mkfs.mount.split("/"))))))
    if not mount:
        filesystems.reverse()
    for mkfs in filesystems:
        if mkfs.mount:
            part_path = _make_partition(device_path, mkfs.npart)
            if mount:
                mount_path = prefix_path + "/" + mkfs.mount
                cmds.append([shutil.which("mkdir"), "-p", mount_path])
                cmds.append([shutil.which("mount"), part_path, mount_path])
            else:
                cmds.append([shutil.which("umount"), part_path])
    _run_commands(cmds)

def _print_size() -> None:
    """
    Prints the size of the disk.

    Note: The size is calculated based on the last partition's end position.

    Returns:
        None
    """
    (_, filesystems) = _parse_script(sys.stdin.read())
    size = 0
    for mkfs in filesystems:
        if mkfs.end > 0:
            size = mkfs.end
        else:
            size = mkfs.begin
    size += 2048 * 1024 * 1024  # + 2Gb
    size -= size % 4096  # Align
    print(size)

def main() -> None:
    """
    The main entry point of the script.
    """
    if len(sys.argv) < 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <format|mkfs|mount|umount|print-size> ...")
    if sys.argv[1] == "format":
        if len(sys.argv) != 3:
            raise SystemExit(f"Usage: cat disk.conf | {sys.argv[0]} format /dev/path")
        _format_disk(sys.argv[2])
    elif sys.argv[1] == "mkfs":
        if len(sys.argv) != 3:
            raise SystemExit(f"Usage: cat disk.conf | {sys.argv[0]} mkfs /dev/path")
        _mkfs_disk(sys.argv[2])
    elif sys.argv[1] == "mount":
        if len(sys.argv) != 4:
            raise SystemExit(f"Usage: cat disk.conf | {sys.argv[0]} mount /dev/path /prefix/path")
        _mount_disk(sys.argv[2], sys.argv[3], True)
    elif sys.argv[1] == "umount":
        if len(sys.argv) != 3:
            raise SystemExit(f"Usage: cat disk.conf | {sys.argv[0]} umount /dev/path")
        _mount_disk(sys.argv[2], "/dev/null", False)
    elif sys.argv[1] == "print-size":
        if len(sys.argv) != 2:
            raise SystemExit(f"Usage: cat disk.conf | {sys.argv[0]} print-size")
        _print_size()
    else:
        raise SystemExit(f"Usage: {sys.argv[0]} <format|mount|umount> ...")

if __name__ == "__main__":
    main()

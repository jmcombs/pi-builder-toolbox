#!/usr/bin/env python3
# ========================================================================== #
#                                                                            #
#    install-binfmt - mount binfmt_misc and register extra handlers.         #
#                                                                            #
#    Copyright (C) 2019-2023  Maxim Devaev <mdevaev@gmail.com>               #
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

import os
import subprocess
import dataclasses
import argparse
import logging
import shutil

@dataclasses.dataclass(frozen=True)
class _Binfmt:
    """
    Represents a binary format (binfmt) configuration.

    Attributes:
        name (str): The name of the binfmt.
        arch (str): The architecture of the binfmt.
        magic (str): The magic number pattern of the binfmt.
        mask (str): The mask pattern of the binfmt.
    """
    name: str
    arch: str
    magic: str
    mask: str

_BINFMT_DB = {
    binfmt.arch: binfmt
    for binfmt in [
        _Binfmt(
            name="ARM",
            arch="arm",
            magic=r"\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00",
            mask=r"\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff",
        ),
        _Binfmt(
            name="AArch64",
            arch="aarch64",
            magic=r"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00",
            mask=r"\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff",
        ),
    ]
}

_logger = logging.getLogger("install-binfmt")

def _mount_binfmt(mount_path: str) -> None:
    """
    Mounts binfmt_misc to the specified mount path.

    Args:
        mount_path (str): The path where binfmt_misc should be mounted.

    Raises:
        subprocess.CalledProcessError: If the mount command fails.
    """
    _logger.info(":: Mounting binfmt_misc to %r ...", mount_path)
    subprocess.check_output(["mount", "binfmt_misc", "-t", "binfmt_misc", mount_path])

def _check_binfmt(mount_path: str, binfmt: _Binfmt, interpreter_path: str) -> bool:
    """
    Checks if the specified binfmt configuration exists and matches the expected values.

    Args:
        mount_path (str): The path where binfmt_misc is mounted.
        binfmt (_Binfmt): The binfmt configuration to check.
        interpreter_path (str): The path to the interpreter associated with the binfmt.

    Returns:
        bool: True if the binfmt configuration exists and matches the expected values, False otherwise.

    Raises:
        RuntimeError: If an unknown binfmt configuration is found.
    """
    _logger.info(":: Checking %s binfmt configuration ...", binfmt.name)

    binfmt_path = os.path.join(mount_path, binfmt.arch)
    if os.path.exists(binfmt_path):
        _logger.info(":: Found existent %s binfmt handler", binfmt.name)

        with open(binfmt_path) as binfmt_file:
            current_params: dict[str, str] = dict(
                (row.split(" ", 1) + [""])[:2]
                for row in filter(None, binfmt_file.read().split("\n"))
            )
            _logger.debug(":: Current configuration: %s", current_params)

        mismatch = "\n".join(
            f"  - Current {name} {current!r} != expected {expected!r}"
            for (name, current, expected) in [
                ("magic", current_params.get("magic", "").replace("454c46", "ELF"), binfmt.magic.replace(r"\x", "")),
                ("mask", current_params.get("mask", ""), binfmt.mask.replace(r"\x", "")),
                ("interpreter", current_params.get("interpreter"), interpreter_path),
            ]
            if current != expected
        )
        if mismatch:
            raise RuntimeError(
                f"Found unknown {binfmt.name} binfmt configuration:\n"
                f"{mismatch}\n"
                f"  - Run 'echo -1 > {binfmt_path}' to disable this binfmt globally"
            )

        return True
    return False

def _execute_command(command: str, *args: str) -> None:
    """
    Executes the specified command with the given arguments.

    Args:
        command (str): The command to execute.
        args (str): The arguments to pass to the command.

    Raises:
        FileNotFoundError: If the executable for the command is not found.
        subprocess.CalledProcessError: If the command execution fails.
    """
    executable_path = shutil.which(command)
    if executable_path is None:
        raise FileNotFoundError(f"Executable '{command}' not found.")
    subprocess.check_call([executable_path, *args])

def _install_binfmt(mount_path: str, binfmt: _Binfmt, interpreter_path: str) -> None:
    """
    Installs the specified binfmt configuration.

    Args:
        mount_path (str): The path where binfmt_misc is mounted.
        binfmt (_Binfmt): The binfmt configuration to install.
        interpreter_path (str): The path to the interpreter associated with the binfmt.

    Raises:
        subprocess.CalledProcessError: If the register command fails.
    """
    _logger.info(":: Installing %s binfmt as %r ...", binfmt.name, interpreter_path)
    with open(os.path.join(mount_path, "register"), "w") as register_file:
        register_file.write(f":{binfmt.arch}:M::{binfmt.magic}:{binfmt.mask}:{interpreter_path}:")

def main() -> None:
    """
    The main entry point of the program.

    Parses command line arguments, mounts binfmt_misc if specified, checks and installs binfmt configurations.

    Raises:
        RuntimeError: If the user is not running the program as root.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--mount", action="store_true", help="Mount binfmt_misc")
    parser.add_argument("--binfmt-misc", default="/proc/sys/fs/binfmt_misc", help="Path to binfmt_misc")
    parser.add_argument("arch", choices=sorted(_BINFMT_DB))
    parser.add_argument("interpreter")
    parser.add_argument("-d", "--debug", action="store_const", const=logging.DEBUG, dest="log_level")
    parser.set_defaults(log_level=logging.INFO)

    options = parser.parse_args()
    logging.basicConfig(level=options.log_level, format="%(message)s")

    if os.getuid() != 0:
        raise RuntimeError("You must be a root")

    if options.mount:
        _mount_binfmt(options.binfmt_misc)

    binfmt = _BINFMT_DB[options.arch]
    if not _check_binfmt(options.binfmt_misc, binfmt, options.interpreter):
        _install_binfmt(options.binfmt_misc, binfmt, options.interpreter)

    _logger.info(":: %s binfmt handler %r is ready", binfmt.name, options.interpreter)

if __name__ == "__main__":
    main()

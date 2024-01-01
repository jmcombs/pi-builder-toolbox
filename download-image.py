#!/usr/bin/env python3
import argparse
from bs4 import BeautifulSoup
import logging
import os
import re
import requests
import subprocess
import sys
from urllib.parse import urljoin

def _run(cmd: list[str], input: (str | None) = None, read: bool = False) -> str:
    """
    Run a command and return the output.

    Args:
        cmd (list[str]): The command to run.
        input (str | None): The input to pass to the command (optional).
        read (bool): Whether to read and return the command output (default: False).

    Returns:
        str: The output of the command.

    Raises:
        SystemExit: If the command returns a non-zero exit code.
    """
    print(f"CMD [ {sys.argv[0]} ] ==>", " ".join(cmd))
    sys.stdout.flush()
    proc = subprocess.Popen(
        cmd,
        stdin=(None if input is None else subprocess.PIPE),
        stdout=(subprocess.PIPE if read else sys.stdout),
        stderr=sys.stderr,
        preexec_fn=os.setpgrp,
    )
    data = proc.communicate(None if input is None else input.encode())[0]
    retcode = proc.poll()
    sys.stdout.flush()
    sys.stderr.flush()
    if retcode != 0:
        raise SystemExit(1)
    return (data.decode().strip() if read else "")


def download_archlinuxarm(arch, board, dist_repo_url, output_dir, uid, gid):
    """
    Download the Arch Linux ARM image for the specified architecture and board.

    Args:
        arch (str): The architecture (arm or aarch64).
        board (str): The board name.
        dist_repo_url (str): The URL of the distribution repository.
    """
    if arch == 'arm':
        _arch = 'armv7'
    else:
        _arch = 'aarch64'
    filename = os.path.join(output_dir, f'archlinuxarm-{board}-{arch}.tgz')
    url = f'{dist_repo_url}/os/ArchLinuxARM-rpi-{_arch}-latest.tar.gz'
    response = requests.get(url)
    with open(f'{filename}.tmp', 'wb') as file:
        file.write(response.content)
    os.rename(f'{filename}.tmp', f'{filename}')
    _run(['chown', '--recursive', f'{uid}:{gid}', f'{output_dir}'])
    print(f'Downloaded: {filename}')

def get_latest_image_url(url):
    """
    Get the URL of the latest Raspberry Pi OS image.

    Args:
        url (str): The URL of the distribution repository.

    Returns:
        str: The URL of the latest image.
    """
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a')
    latest_link = max(links, key=lambda link: link.text)
    latest_image_url = urljoin(url, latest_link['href'])

    # Get the URL for the filename ending in .xz
    response = requests.get(latest_image_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a')
    xz_links = [link['href'] for link in links if link['href'].endswith('.xz')]
    if not xz_links:
        raise ValueError('No .xz file found in the latest image URL')
    xz_filename = xz_links[0]
    xz_url = urljoin(latest_image_url, xz_filename)

    image_name = xz_filename[:-7]  # Remove the last 7 characters (.img.xz)
    print(f'Latest Raspberry Pi OS image: {image_name}')
    return xz_url

def download_rpios(arch, board, dist_repo_url, output_dir, cache_dir, uid, gid):
    """
    Download the Raspberry Pi OS image for the specified architecture and board.

    Args:
        arch (str): The architecture (arm or arm64).
        board (str): The board name.
        dist_repo_url (str): The URL of the distribution repository.
        output_dir (str): The output directory for saving the image.
        cache_dir (str): The cache directory for saving temporary files.
    """
    if arch == 'arm':
        _arch = 'armhf'
    else:
        _arch = 'arm64'
    filename = f'rpios-{board}-{arch}'
    img_file = os.path.join(cache_dir, f'rpios-{board}-{arch}.img')
    xz_file = os.path.join(cache_dir, f'{filename}.xz.tmp')
    tmp_file = os.path.join(cache_dir, f'{filename}.tmp')
    
    try:
        url = urljoin(dist_repo_url, f'raspios_lite_{_arch}/images/')
        latest_image_url = get_latest_image_url(url)
        print(f'Downloading: {latest_image_url}')
        response = requests.get(latest_image_url)
        with open(xz_file, 'wb') as file:
            file.write(response.content)
        
        subprocess.run(['xzcat', xz_file], stdout=open(tmp_file, 'wb'))
        os.remove(xz_file)
        os.rename(tmp_file, img_file)
        
        build_rpios_tgz(filename, img_file, cache_dir, output_dir, uid, gid)  # Call build_rpios_tgz function with the filename
        print(f'Image built: {filename}')
        
    except Exception as e:
        print(f'Error building {filename}: {str(e)}')

def build_rpios_tgz(filename, img_file, cache_dir, output_dir, uid, gid):
    """
    Build a compressed tarball (.tgz) from the Raspberry Pi OS image.

    Args:
        filename (str): The filename of the Raspberry Pi OS image.
        img_file (str): The path to the Raspberry Pi OS image file.
        cache_dir (str): The cache directory for temporary files.
        output_dir (str): The output directory for saving the compressed tarball.
    """
    os.makedirs('/mnt/rpios', exist_ok=True)
    try:
        output = _run(['kpartx', '-av', img_file], read=True)
        lines = output.splitlines()
        partitions = [re.search(r'add map (\S+)', line).group(1) for line in lines]
        _run(['mount', f'/dev/mapper/{partitions[1]}', '/mnt/rpios'])
        _run(['mount', f'/dev/mapper/{partitions[0]}', '/mnt/rpios/boot/firmware'])
        _run(['tar', '-czf', f'{img_file}.tmp', '-C', '/mnt/rpios', '.'])
        _run(['chown', f'{os.getuid()}:{os.getgid()}', f'{img_file}.tmp'])
        _run(['mv', f'{img_file}.tmp', f'{output_dir}/{filename}.tgz'])
        _run(['chown', '--recursive', f'{uid}:{gid}', f'{output_dir}'])
        _run(['umount', '/mnt/rpios/boot/firmware'])
        _run(['umount', '/mnt/rpios'])
        _run(['kpartx', '-d', img_file])
        print(f'Compressed tarball created: {filename}')
    finally:
        _run(['rm', f'{img_file}'])
        _run(['rmdir', '/mnt/rpios'])

def main() -> None:
    """
    Main function for downloading OS images to a directory.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--os", type=str, help="Raspberry Pi OS (rpios) or Arch Linux ARM (archlinuxarm)")
    parser.add_argument('--os-repo-url', type=str, help='The URL of the distribution repository')
    parser.add_argument('--arch', type=str, help='CPU architecture (arm or aarch64)')
    parser.add_argument('--board', type=str, help='Raspberry Pi board type (rpi2, rpi3, rpi4, etc)')
    parser.add_argument('--output-dir', default='/root/base', help='Output directory for saving the image')
    parser.add_argument('--cache-dir', default='/root/.cache', help='Cache directory for saving temporary files')
    parser.add_argument('--uid', type=int, help='User ID for the output directory')
    parser.add_argument('--gid', type=int, help='Group ID for the output directory')
    parser.set_defaults(log_level=logging.INFO)

    options = parser.parse_args()
    logging.basicConfig(level=options.log_level, format="%(message)s")

    if options.os == 'rpios':
        download_rpios(options.arch, options.board, options.os_repo_url, options.output_dir, options.cache_dir, options.uid, options.gid)
    elif options.os == 'archlinuxarm':
        download_archlinuxarm(options.arch, options.board, options.os_repo_url, options.output_dir, options.uid, options.gid)

if __name__ == "__main__":
    main()

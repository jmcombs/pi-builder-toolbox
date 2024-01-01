FROM debian:stable-slim
RUN apt-get update && apt-get install -y \
    multipath-tools \
    net-tools \
    python3 \
    python3-bs4 \
    python3-dask \
    python3-requests \
    parted \
    dosfstools \
    rsync \
    udev \
    xz-utils \
    arp-scan \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir /tools
COPY *.py /tools/
RUN chmod +x /tools/*.py
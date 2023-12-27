FROM debian:stable-slim
RUN apt-get update && apt-get install -y \
    net-tools \
    python3 \
    python3-dask \
    parted \
    dosfstools \
    rsync \
    udev \
    xz-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir /tools
COPY *.py /tools/
RUN chmod +x /tools/*.py
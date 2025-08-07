# syntax=docker/dockerfile:1
FROM python:3.13-alpine3.22 AS base-image
# Starting with alpine3.14 features sqlite3.35 and "returning" clause

# Builds intended for deployment should specify the software
# version via "APPVERSION".
ARG APPVERSION
ARG APPNAME=dashboard

# Label "version" may be incremented upon changing this file.
LABEL version="5"                \
      appname="$APPNAME"         \
      appversion="$APPVERSION"

# Configure core app environment.
ENV APP_NAME="$APPNAME"                                    \
    APP_VERSION="$APPVERSION"                              \
    APP_DATABASE="file:auto:/var/lib/$APPNAME/data.sqlite" \
    PYTHONPATH=/usr/src/"$APPNAME"/srv                     \
    PYTHONUNBUFFERED=1

# Create core app user, group and directories.
RUN <<-EOF
	set -ex

	addgroup -S "$APPNAME"
	adduser --no-create-home --disabled-password "$APPNAME" --ingroup "$APPNAME"

	mkdir -p /usr/src/"$APPNAME"
	chown "$APPNAME" /usr/src/"$APPNAME"
	chmod ug+rwx /usr/src/"$APPNAME"

	mkdir -p /var/lib/"$APPNAME"
	chown "$APPNAME" /var/lib/"$APPNAME"
	chmod ug+rwx /var/lib/"$APPNAME"
EOF

# Copy in API source from host disk.
COPY --chown="$APPNAME":"$APPNAME" src/srv/ /usr/src/"$APPNAME"/srv/

# ...and requirement file(s)
COPY --chown="$APPNAME":"$APPNAME" requirement/ /usr/src/"$APPNAME"/requirement/

# Install core app (globally)
RUN python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/core.txt

WORKDIR /usr/src/"$APPNAME"/srv


FROM base-image AS cmd

ARG FATEVERSION=1.1.0

LABEL fateversion="$FATEVERSION" \
      buildflavor=cmd

# Install flavor requirements (globally)
RUN python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/cmd.txt

# Install Fate (isolated with global links)
#
# (fate installed into venv but override prefix inference to treat as system-global)
#
ENV FATE_PREFIX_PROFILE="system"

COPY etc/fate /etc/fate

RUN <<-INSTALL-FATE
	#
	# install fate-scheduler (within a virtual environment)
	#
	set -ex

	python -m venv /usr/local/lib/fate

	# fate requires lmdb
	# rather than attempt to compile the lmdb-python extension (under alpine),
	# or use its included lmdb, or patch lmdb ...
	# we'll just instruct it to use a system-installed lmdb via cffi.
	apk add --no-cache py3-cffi lmdb

	export LMDB_FORCE_SYSTEM=1 LMDB_FORCE_CFFI=1 LMDB_PURE=1

	/usr/local/lib/fate/bin/pip install --no-cache-dir fate-scheduler=="$FATEVERSION"

	# (note: busybox ln doesn't appear to support -t as expected)
	ln -s /usr/local/lib/fate/bin/fate* /usr/local/bin
INSTALL-FATE

# Create conventional interface convenience script
COPY --chmod=775 <<-"app-extract" /usr/local/bin/extract
	#!/bin/sh
	exec fated --foreground
app-extract

RUN ln -s /usr/local/bin/extract /usr/local/bin/"${APPNAME}"-extract

USER "$APPNAME"

CMD ["dashboard-extract"]


FROM base-image AS serve-base

# Extend core app user, group and directories.
RUN <<-EOF
	set -ex

	mkdir -p /var/cache/"$APPNAME"
	chown "$APPNAME" /var/cache/"$APPNAME"
	chmod ug+rwx /var/cache/"$APPNAME"
EOF


FROM python:3.13-alpine3.22 AS build-lambda

COPY requirement/serve-lambda.txt /

RUN <<-EOF
    mkdir /export/

    # required to build awslambdaric in alpine
    apk add --no-cache \
      autoconf \
      automake \
      cmake \
      g++ \
      gcc \
      libffi-dev \
      libtool \
      linux-headers \
      make \
      musl-dev \
      openssl-dev

    # libexecinfo-dev removed in alpine3.17
    apk add --no-cache --update --repository=https://dl-cdn.alpinelinux.org/alpine/v3.16/main/ libexecinfo-dev

    python -m pip install --no-cache-dir \
      --target /export/ \
      -r /serve-lambda.txt
EOF


FROM serve-base AS serve-lambda

ARG STAGE_ENV

LABEL buildflavor=serve-lambda \
      stage_env="$STAGE_ENV"

ENV APP_DATABASE="file:auto:/tmp/$APPNAME/var/lib/data.sqlite"         \
    APP_PREFIX=/<:deviceid>/                                           \
    DATAFILE_BACKEND=s3                                                \
    DATAFILE_S3_CACHE_PATH="/tmp/$APPNAME/var/cache/data/file/s3/get/"

# Install global environmental requirements
RUN <<-EOF
    set -ex

    apk add --no-cache \
        libstdc++ \
	nghttp2-libs \
	libidn2 \
	libpsl \
	zstd-libs \
	brotli-libs

    python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/backend-s3.txt
EOF

# Copy requirements built separately
COPY --from=build-lambda /export/ /usr/local/lib/python3.13/site-packages/

RUN --mount=type=bind,source=zappa_settings.toml,target=/mnt/zappa_settings.toml <<-EOF
    python -m zappa.cli save-python-settings-file \
        -s /mnt/zappa_settings.toml \
	-o /usr/src/"$APPNAME"/srv/zappa_settings.py \
	$STAGE_ENV
EOF

USER "$APPNAME"

ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]

CMD ["zappa.handler.lambda_handler"]


FROM serve-base AS serve-local-base

ENV APP_HOST="0.0.0.0"

# Create conventional interface convenience script
COPY --chmod=775 <<-"app-serve" /usr/local/bin/serve
	#!/bin/sh
	exec python -m app
app-serve

RUN ln -s /usr/local/bin/serve /usr/local/bin/"${APPNAME}"-serve

# Install flavor requirements (globally)
RUN python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/serve-builtin.txt

CMD ["dashboard-serve"]

EXPOSE 8080


FROM serve-local-base AS serve-local-s3

LABEL buildflavor=serve-local-s3

ENV DATAFILE_BACKEND=s3 \
    APP_PREFIX=/<:deviceid>/

# Install flavor requirements (globally)
RUN python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/backend-s3.txt

USER "$APPNAME"


FROM serve-local-base AS serve-local2

LABEL buildflavor=serve-local2

ENV DATAFILE_BACKEND=local \
    APP_REDIRECT=on        \
    APP_PREFIX=/dashboard/

# Install flavor requirements (globally)
RUN python -m pip install --no-cache-dir -r /usr/src/"$APPNAME"/requirement/backend-local.txt

USER "$APPNAME"

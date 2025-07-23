# syntax=docker/dockerfile:1
FROM python:3.13-alpine3.22
# Starting with alpine3.14 features sqlite3.35 and "returning" clause

# Builds intended for deployment should specify the software
# version via "APPVERSION".
ARG APPVERSION
ARG APPNAME=dashboard
ARG FATEVERSION=1.1.0

# Label "version" may be incremented upon changing this file.
LABEL version="4"                \
      appname="$APPNAME"         \
      appversion="$APPVERSION"   \
      fateversion="$FATEVERSION"

# Configure core app environment.
ENV APP_NAME="$APPNAME"                               \
    APP_VERSION="$APPVERSION"                         \
    APP_HOST="0.0.0.0"                                \
    APP_DATABASE="file:/var/lib/$APPNAME/data.sqlite" \
    PYTHONPATH=/usr/src/"$APPNAME"/srv                \
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

	mkdir -p /var/cache/"$APPNAME"
	chown "$APPNAME" /var/cache/"$APPNAME"
	chmod ug+rwx /var/cache/"$APPNAME"
EOF

WORKDIR /usr/src/"$APPNAME"

# Copy in API source from host disk.
COPY --chown="$APPNAME":"$APPNAME" src/srv/ srv/

# ...and requirement file(s)
COPY --chown="$APPNAME":"$APPNAME" requirement/ requirement/

# Install web app (globally)
RUN set -ex \
    ; python -m pip install --no-cache-dir -r requirement/main.txt

# ...and Fate (isolated with global links)
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

# Create conventional interface convenience scripts.
#
# These will additionally bootstrap (create) the environment-configured database directory
# if it doesn't already exist.
#
COPY --chmod=775 <<-"app-serve" /usr/local/bin/serve
	#!/bin/sh
	case "${APP_DATABASE}" in file:*) mkdir -p $(dirname "${APP_DATABASE#?????}") || exit 1; esac

	exec python -m app
app-serve

COPY --chmod=775 <<-"app-extract" /usr/local/bin/extract
	#!/bin/sh
	case "${APP_DATABASE}" in file:*) mkdir -p $(dirname "${APP_DATABASE#?????}") || exit 1; esac

	exec fated --foreground
app-extract

RUN <<-EOF
	set -ex

	ln -s /usr/local/bin/serve /usr/local/bin/"${APPNAME}"-serve

	ln -s /usr/local/bin/extract /usr/local/bin/"${APPNAME}"-extract
EOF

USER "$APPNAME"

WORKDIR /usr/src/"$APPNAME"/srv

CMD ["serve"]

EXPOSE 8080

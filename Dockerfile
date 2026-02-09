# Stage 1: Builder stage - Install build dependencies and Python packages
FROM python:3.11-alpine AS builder

ENV LANG C.UTF-8
ENV TZ 'Asia/Shanghai'

# Install build-time dependencies for apk packages and pip packages
RUN set -ex; \
    apk add --no-cache --update \
        python3-dev \
        py3-pillow \
        py3-ruamel.yaml \
        git \
        gcc \
        musl-dev \
        zlib-dev \
        jpeg-dev \
        libffi-dev \
        openssl-dev \
        libwebp-dev;
    # Install python packages using pip with --no-cache-dir
RUN pip3 install --no-cache-dir urllib3==1.26.15; \
    # Install/reinstall rich and Pillow from pip (as per original Dockerfile intent)
    # Note: Pillow might be installed via apk (py3-pillow) and pip, pip version will likely take precedence.
    pip3 install --no-cache-dir --no-deps --force-reinstall rich Pillow; \
    # Install TgCrypto, ignoring any pre-installed PyYAML
    pip3 install --no-cache-dir --ignore-installed PyYAML TgCrypto;

    # Install other Python dependencies from git and PyPI
    # Newer efb-telegram-master requires setuptools>=82; pin 80.9.0 in builder
    # (final stage force-reinstalls it) so pkg_resources stays available.
RUN pip3 install --no-cache-dir --upgrade "setuptools==80.9.0"; \
    pip3 install --no-cache-dir ehforwarderbot python-telegram-bot pyqrcode; \
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/efb-mp-instantview-middleware.git@ebd5acd9790a813fa68a5088ff3641b558d9ecf3; \
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/efb-map-middleware.git@51f360e95bd38db4bd65485f1bdb5a388e6f5be9; \
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/efb-keyword-replace.git@ede3f2ede8092017d7005f9b2150d6325076c852; \
    # Pin to 5e48545 (2026-04-25): the last commit before f241e84 added a hard
    # "setuptools>=82.0.1" dependency in pyproject.toml. setuptools>=81 drops
    # pkg_resources, which ehforwarderbot 2.1.1 needs at runtime -> deadlock.
    # 5e48545 still carries the file:// URI media fix and avoids that conflict.
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/efb-telegram-master.git@5e48545; \
    # Pinned to 3df22af: newer versions fetch messages via a separate "bridge"
    # service on :19088 (/v1/messages/pull) which the comwechat image does not
    # provide, breaking message delivery entirely. See README note.
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/python-comwechatrobot-http.git@3df22af9a6e77e8032681800af4ffb90a3981b4c; \
    # Pinned to bf54943 to stay compatible with the above http client version.
    pip3 install --no-cache-dir git+https://github.com/jiz4oh/efb-wechat-comwechat-slave.git@bf5494359ad910e6fb4d1f15e85e4c0ca948b394; \
    pip3 install --no-cache-dir git+https://github.com/QQ-War/efb-keyword-reply.git@c7dfef513e85d6647ad78c70b4e3353ab8804977; \
    pip3 install --no-cache-dir git+https://github.com/QQ-War/efb_message_merge.git@946837e5508bf9325060f15f2a725525baf368ff; \
    # Voice-to-text middleware (uses the Tencent Cloud ASR key already present in
    # profiles/comwechat/catbaron.voice_recog/config.yaml)
    pip3 install --no-cache-dir efb-voice_recog-middleware; \
    # Chat history search middleware (Chinese keyword search)
    pip3 install --no-cache-dir efb-search_msg-middleware; \
    # Its METADATA ships a malformed requirement "python-telegram-bot (>=10.0.0<12.0.0)"
    # (missing comma) which makes pkg_resources raise InvalidRequirement. The pin
    # would also conflict with the ptb 13.x we need, so drop the version specifier.
    sed -i -E 's/^Requires-Dist: python-telegram-bot.*/Requires-Dist: python-telegram-bot/' \
        /usr/local/lib/python3.11/site-packages/efb_search_msg_middleware-*.dist-info/METADATA || true;

# Patch the comwechat slave:
#   1) widen the hard-coded download wait 120s -> 300s
#   2) on image timeout, fall back to WeChat's already-downloaded thumbnail
COPY patches/patch_comwechat.py /tmp/patch_comwechat.py
RUN python3 /tmp/patch_comwechat.py && rm -f /tmp/patch_comwechat.py

# Stage 2: Final stage - Install only runtime dependencies and copy artifacts
FROM python:3.11-alpine

ENV LANG C.UTF-8
ENV TZ 'Asia/Shanghai'
ENV EFB_DATA_PATH /data/
ENV EFB_PARAMS ""
ENV EFB_PROFILE "default"
ENV HTTPS_PROXY ""

# Set timezone
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone;

# Install runtime C-library dependencies including cron and necessary libs for python packages
RUN set -ex; \
    apk add --no-cache --update \
        libmagic \
        ffmpeg \
        zlib \
        jpeg \
        libffi \
        py3-pillow \
        openssl \
        libwebp \
        cronie \
        py3-ruamel.yaml; \
    # Clean up apk cache
    rm -rf /var/cache/apk/*;

# Copy installed python packages from builder stage's site-packages
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
# Copy executables installed by pip packages
COPY --from=builder /usr/local/bin/ehforwarderbot /usr/local/bin/ehforwarderbot

# Force-reinstall setuptools in the final image so the stale 79.0.1 dist-info
# copied from base/builder is removed. Newer efb-telegram-master requires
# setuptools>=82, but setuptools>=81 no longer bundles pkg_resources (which
# ehforwarderbot 2.1.1 imports at runtime). setuptools 80.9.0 is the last
# version that still ships pkg_resources, so pin to it.
RUN pip3 install --no-cache-dir --upgrade --force-reinstall "setuptools==80.9.0"

# Copy entrypoint script and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

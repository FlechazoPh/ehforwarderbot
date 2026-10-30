#!/usr/bin/env python3
"""Custom patches for the self-built image (based on upstream efb:v3.1.0).

1. ETM sender prefix: use display_name instead of long_name.
   long_name renders as "alias (name)"; when the WeChat name contains Unicode
   characters that Telegram's font cannot render, the part in parentheses shows
   up as tofu boxes.
2. Raise MEDIA_WAIT_SECONDS from 5s to 60s.
   Group images are downloaded lazily by WeChat (cdnbigimgurl_pd_pri), so a
   5-second wait almost always fails and surfaces as "图片下载失败".
3. Fall back to WeChat's thumbnail when the original image never arrives.

Each patch is skipped with a warning if the target snippet is not found, so a
future upstream change degrades to "not patched" instead of breaking the build.
"""

import pathlib
import sys

SP = pathlib.Path("/usr/local/lib/python3.11/site-packages")
report = []


def patch_file(rel: str, old: str, new: str, label: str) -> None:
    path = SP / rel
    if not path.exists():
        report.append("SKIP  %s (file missing: %s)" % (label, rel))
        return
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        report.append("SKIP  %s (unreadable: %s)" % (label, exc))
        return
    if old not in text:
        report.append("WARN  %s (snippet not found, upstream may have changed)" % label)
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    report.append("OK    %s" % label)


# ---------------------------------------------------------------- 1. name --
patch_file(
    "efb_telegram_master/slave_message.py",
    "msg_prefix = msg.author.long_name",
    "msg_prefix = msg.author.display_name",
    "ETM sender prefix: long_name -> display_name",
)

# --------------------------------------------------------- 2. wait seconds --
patch_file(
    "efb_wechat_comwechat_slave/Utils.py",
    "MEDIA_WAIT_SECONDS = 5",
    "MEDIA_WAIT_SECONDS = 60",
    "media wait: 5s -> 60s",
)

# ------------------------------------------------------ 3. thumbnail -------
FALLBACK_METHOD = '''    def _thumbnail_fallback(self, msg):
        """Return a usable thumbnail path when the original media never arrived.

        WeChat downloads group images lazily, so the full-size file can be
        missing for minutes while the thumbnail is already on disk. The
        thumbnail is reported in msg["thumb_path"] as a Windows-style path
        relative to the WeChat files root.
        """
        thumb = (msg or {}).get("thumb_path")
        if not thumb:
            return None
        try:
            path = str(thumb).replace("\\\\", "/")
            root = getattr(self.channel, "dir", None) or "/data/comwechat/Files"
            candidate = path if path.startswith("/") else root.rstrip("/") + "/" + path
            if os.path.isfile(candidate):
                return candidate
            resolved = resolve_hooked_wechat_image_path(candidate)
            if resolved and os.path.isfile(resolved):
                return resolved
        except Exception:
            return None
        return None

'''

patch_file(
    "efb_wechat_comwechat_slave/media_retry.py",
    "    @staticmethod\n    def _existing_media_path(path, media_type):",
    FALLBACK_METHOD + "    @staticmethod\n    def _existing_media_path(path, media_type):",
    "media_retry: insert _thumbnail_fallback",
)

patch_file(
    "efb_wechat_comwechat_slave/media_retry.py",
    """                    media_path = self._wait_for_media(restored_path, media_type)
                    if media_path is None:
                        return self._temporary_failure(""",
    """                    media_path = self._wait_for_media(restored_path, media_type)
                    if media_path is None:
                        media_path = self._thumbnail_fallback(msg)
                    if media_path is None:
                        return self._temporary_failure(""",
    "media_retry: use thumbnail before declaring failure",
)

for line in report:
    print(line)
sys.exit(0)

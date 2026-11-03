#!/usr/bin/env python3
"""Custom patches for the self-built image (based on upstream efb:v3.1.0).

1. ETM sender prefix: keep "alias (name)" (needed to tell apart members with
   identical aliases) but strip characters that render as tofu boxes, and show
   a single name when alias == name. Upstream wraps the name in parentheses in
   <tg-spoiler>; it is rendered as plain text instead.
2. Raise MEDIA_WAIT_SECONDS from 5s to 60s.
   Group images are downloaded lazily by WeChat (cdnbigimgurl_pd_pri), so a
   5-second wait almost always fails and surfaces as "图片下载失败".
3. Fall back to WeChat's thumbnail when the original image never arrives.
4. Recover expired ETM "Retry" buttons from the slave's media_retry DB.
5. Proactively download media and clean up every on-disk copy after sending
   (see the section header below for details).

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
# Keep upstream's "alias (name)" so members who copy someone else's alias can
# still be told apart, but drop characters no font can render (private-use,
# unassigned, control, surrogates) which used to show up as tofu boxes, and
# avoid "x (x)" when alias and name are identical.
MEMBER_LABEL = '''

def _efb_member_label(member):
    """Sender prefix for group messages: "alias (name)" without unrenderable chars."""
    import unicodedata

    def clean(text):
        text = "".join(
            ch for ch in str(text or "")
            if unicodedata.category(ch) not in ("Co", "Cn", "Cc", "Cs")
        )
        return " ".join(text.split())

    alias = clean(getattr(member, "alias", None))
    name = clean(getattr(member, "name", None))
    if alias and name and alias != name:
        return f"{alias} ({name})"
    return alias or name or member.display_name
'''

patch_file(
    "efb_telegram_master/slave_message.py",
    "msg_prefix = msg.author.long_name",
    "msg_prefix = _efb_member_label(msg.author)",
    "ETM sender prefix: alias (name) without unrenderable chars",
)
patch_file(
    "efb_telegram_master/slave_message.py",
    'f"{html.escape(alias)} (<tg-spoiler>{html.escape(name)}</tg-spoiler>)"',
    'f"{html.escape(alias)} ({html.escape(name)})"',
    "ETM sender prefix: show name in parentheses as plain text (no spoiler)",
)
_sm = SP / "efb_telegram_master/slave_message.py"
if _sm.exists() and "def _efb_member_label" not in _sm.read_text(encoding="utf-8"):
    _sm.write_text(_sm.read_text(encoding="utf-8").rstrip("\n") + "\n" + MEMBER_LABEL, encoding="utf-8")
    report.append("OK    ETM sender prefix: add _efb_member_label helper")

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

# ------------------------------------------- 4. survive restarts (SE01) ----
# ETM keeps inline-button commands only in memory, so every EFB restart turns
# all existing "Retry" buttons into "Session expired (SE01)". The comwechat
# slave, however, persists its media retry records in its own database keyed by
# the placeholder message uid. When a callback is no longer known to ETM, map
# the clicked Telegram message back to that uid and run the retry directly.
RECOVER_METHOD = '''    def _recover_media_retry(self, update):
        query = update.callback_query
        if query is None or not query.data or not str(query.data).isdecimal():
            return False
        chat_id = update.effective_chat.id
        message_id = update.effective_message.message_id
        log = self.channel.db.get_msg_log(master_msg_id=f"{chat_id}.{message_id}")
        if log is None or not log.slave_origin_uid or not log.slave_message_id:
            return False
        from ehforwarderbot import coordinator
        slave = coordinator.slaves.get(str(log.slave_origin_uid).split(" ", 1)[0])
        lister = getattr(getattr(slave, "db", None), "list_media_retries", None)
        if slave is None or lister is None or not hasattr(slave, "retry_media"):
            return False
        target = str(log.slave_message_id)
        token = next(
            (t for t, media in lister()
             if isinstance(media, dict) and str(media.get("placeholder_uid")) == target),
            None,
        )
        if token is None:
            return False
        self.logger.info("Recovering expired retry button: msg=%s token=%s", target, token)
        try:
            query.edit_message_reply_markup(None)
        except Exception:
            pass
        result = slave.retry_media(token)
        try:
            query.answer(text=str(result)[:190] if result else None)
        except Exception:
            pass
        return True

    def session_expired(self, update: Update, context: CallbackContext):
        try:
            if self._recover_media_retry(update):
                return
        except Exception:
            self.logger.exception("Failed to recover expired retry button")
'''

patch_file(
    "efb_telegram_master/bot_manager.py",
    "    def session_expired(self, update: Update, context: CallbackContext):\n",
    RECOVER_METHOD,
    "ETM: recover expired Retry buttons from slave media_retry DB",
)

# ------------------------------- 5. proactive download + full cleanup ------
# Observed behaviour of this ComWeChat build (verified by calling GetCdn):
#   * PC WeChat does not download videos/large files by itself and downloads
#     group images lazily, so the slave used to sit out MEDIA_WAIT_SECONDS and
#     then post "[x 下载超时]" + automatic retries.
#   * GetCdn (type=47) starts the download immediately, but for videos it
#     reports WeChatRobot/Video/<msgid>.mp4 while the file actually lands next
#     to the thumbnail as "<md5>(1).mp4", "(1)(1).mp4"... - one more copy per
#     call. The slave never found it, retried 3 times and every retry left
#     another copy behind.
#   * Images fetched via GetCdn go to WeChatRobot/Image/<msgid>.png plus a copy
#     in FileStorage/Temp/<msgid minus last digit>; ImageHook also writes a
#     decoded "<wxid>/<md5>.png". Only one of those was being deleted.
# This patch:
#   a) calls GetCdn 2s after a media message arrives if the original is not on
#      disk yet, and accepts the GetCdn result or a "name(n).ext" sibling once
#      it is complete (size equals the XML totallen/length, or idle for a while);
#   b) waits longer for large videos/files (60s + size/256KiB/s, max 30 min);
#   c) after a successful send deletes the original, every duplicate, the
#      thumbnail, the hooked/decoded image and the Temp copy;
#   d) runs an hourly sweep that deletes media cache files of the logged-in
#      account older than `media_cleanup_days` (default 3, 0 = off) to catch
#      anything that was never sent (failed downloads, lazy re-downloads).
# Config (honus.comwechat/config.yaml): media_prefetch (default true),
# media_cleanup_days (default 3), delete_media_after_send (upstream, default true).
MEDIA_HELPERS = r'''    # ---- custom (patch_custom #5): proactive media download + cleanup ----
    _PREFETCH_TYPES = ("image", "video", "file", "share")
    _SIZED_TYPES = ("video", "file", "share")
    _DUP_SUFFIX = re.compile(r"(\(\d+\))+$")

    def _media_expected_size(self, msg):
        text = str(msg.get("message") or "")
        match = re.search(r"<totallen>\s*(\d+)\s*</totallen>", text)
        if match is None and msg.get("type") == "video":
            match = re.search(r"<videomsg\b[^>]*?\slength=\"(\d+)\"", text)
        try:
            return int(match.group(1)) or None if match else None
        except ValueError:
            return None

    def _media_wait_seconds(self, msg):
        wait = MEDIA_WAIT_SECONDS
        if msg.get("type") in self._SIZED_TYPES:
            size = self._media_expected_size(msg) or 0
            wait = max(wait, min(60 + size // (256 * 1024), 1800))
        return wait

    def _media_ready(self, path, msg):
        """True when `path` looks like a completely written copy."""
        try:
            stat = os.stat(path)
        except OSError:
            return False
        if stat.st_size <= 0:
            return False
        expected = (
            self._media_expected_size(msg)
            if msg.get("type") in self._SIZED_TYPES else None
        )
        if expected and stat.st_size == expected:
            return True
        idle = time.time() - stat.st_mtime
        if expected:
            arrived = float(msg.get("timestamp") or 0)
            if arrived and stat.st_mtime < arrived - 10:
                return False  # stale same-name file left by an older message
            return idle >= 30
        return idle >= 2

    def _media_siblings(self, path, msg, check_size=True):
        """WeChat's duplicate copies of `path`: name(1).ext, name(1)(1).ext ..."""
        folder, base = os.path.split(str(path or ""))
        stem, suffix = os.path.splitext(base)
        stem = self._DUP_SUFFIX.sub("", stem)
        if not stem or not os.path.isdir(folder):
            return []
        stamp = float(msg.get("timestamp") or 0)
        since = stamp - 10 if stamp else None
        expected = self._media_expected_size(msg) if check_size else None
        if since is None and not expected and msg.get("type") != "video":
            # Without an arrival time or a size, same-named files of other
            # messages could match (file names are not unique). Do nothing.
            return []
        pattern = re.compile(re.escape(stem) + r"(\(\d+\))+")
        found = []
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        for name in names:
            n_stem, n_ext = os.path.splitext(name)
            if n_ext.lower() != suffix.lower() or not pattern.fullmatch(n_stem):
                continue
            full = os.path.join(folder, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            if since is not None and stat.st_mtime < since:
                continue
            if since is None and expected and stat.st_size != expected:
                continue
            found.append((stat.st_mtime, full))
        return [full for _mtime, full in sorted(found)]

    def _locate_media(self, path, msg):
        """A finished copy produced by GetCdn or a WeChat name(n) duplicate."""
        media_type = msg.get("type")
        candidates = []
        cdn_path = msg.get("_cdn_path")
        if cdn_path:
            if media_type == "image":
                hooked = resolve_hooked_wechat_image_path(cdn_path)
                if hooked:
                    candidates.append(hooked)
            candidates.append(cdn_path)
        if media_type in self._SIZED_TYPES and path:
            candidates.extend(self._media_siblings(path, msg))
        for candidate in candidates:
            if candidate and os.path.isfile(candidate) and self._media_ready(candidate, msg):
                return candidate
        return None

    def _request_media_download(self, path, msg):
        if not getattr(self, "media_prefetch", True):
            return
        if msg.get("type") not in self._PREFETCH_TYPES or msg.get("_cdn_requested"):
            return
        arrived = float(msg.get("timestamp") or 0)
        if time.time() - arrived < 2:
            return
        try:
            if os.path.getmtime(path) >= arrived - 10:
                return  # WeChat is already writing the original itself
        except OSError:
            pass
        msgid = msg.get("msgid") or msg.get("svrid")
        if msgid is None:
            return
        msg["_cdn_requested"] = True

        def worker():
            try:
                msg["_cdn_path"] = self.GetMsgCdn(msgid)
                self.logger.debug(
                    "Requested media download: type=%s msgid=%s path=%s",
                    msg.get("type"), msgid, msg.get("_cdn_path"),
                )
            except Exception as exc:
                self.logger.info(
                    "Proactive media download failed: msgid=%s error=%r", msgid, exc,
                )

        threading.Thread(target=worker, name="media-prefetch", daemon=True).start()

    def _take_downloaded_media(self, path, msg):
        self._request_media_download(path, msg)
        found = self._locate_media(path, msg)
        if found:
            msg["filepath"] = found
            return True
        return False

    def _media_cleanup_paths(self, msg, *used):
        """Every on-disk copy WeChat/ComWeChat produced for this message."""
        paths = {p for p in used if p}
        try:
            media_type = msg.get("type")
            root = str(self.dir).rstrip("/")
            msgid = str(msg.get("msgid") or msg.get("svrid") or "")
            wxid = msg.get("self") or getattr(self, "wxid", None)
            if msg.get("_cdn_path"):
                paths.add(msg["_cdn_path"])
            if media_type in self._SIZED_TYPES:
                for p in [p for p in used if p]:
                    paths.update(self._media_siblings(p, msg))
            thumb = str(msg.get("thumb_path") or "").replace("\\", "/")
            if thumb and media_type in ("image", "video"):
                thumb = thumb if thumb.startswith("/") else f"{root}/{thumb}"
                paths.add(thumb)
                if media_type == "video":
                    paths.update(self._media_siblings(thumb, msg, check_size=False))
            if media_type == "image":
                for p in list(paths):
                    hooked = resolve_hooked_wechat_image_path(p)
                    if hooked:
                        paths.add(hooked)
                if wxid and msgid:
                    for ext in (".png", ".jpg", ".gif"):
                        paths.add(f"{root}/{wxid}/WeChatRobot/Image/{msgid}{ext}")
            if wxid:
                temp = f"{root}/{wxid}/FileStorage/Temp"
                if len(msgid) > 1:
                    paths.add(f"{temp}/{msgid[:-1]}")
                for p in list(paths):
                    stem = os.path.splitext(os.path.basename(p))[0]
                    stem = self._DUP_SUFFIX.sub("", stem)
                    if stem.endswith("_t"):
                        stem = stem[:-2]
                    if re.fullmatch(r"[0-9a-f]{32}", stem):
                        paths.add(f"{temp}/{stem[:-1]}")
        except Exception:
            self.logger.debug("Failed to collect media cleanup paths", exc_info=True)
        return [p for p in paths if p]

    def _media_sweep(self, dry_run=False):
        """Delete media cache files of the logged-in account older than N days."""
        days = float(getattr(self, "media_cleanup_days", 0) or 0)
        wxid = getattr(self, "wxid", None)
        if days <= 0 or not wxid:
            return []
        base = os.path.join(str(self.dir), wxid)
        cutoff = time.time() - days * 86400
        busy = set(self.file_msg.keys())
        storage = os.path.join(base, "FileStorage")
        roots = [os.path.join(storage, d) for d in ("MsgAttach", "Temp", "Image", "Video", "File")]
        roots += [os.path.join(base, "WeChatRobot", d) for d in ("Image", "Video", "Files")]
        targets = []
        for top in roots:
            for dirpath, _dirs, files in os.walk(top):
                targets.extend(os.path.join(dirpath, name) for name in files)
        try:
            targets.extend(
                os.path.join(base, name) for name in os.listdir(base)
                if os.path.splitext(name)[1].lower() in (".jpg", ".png", ".gif")
            )
        except OSError:
            pass
        removed, freed = [], 0
        for path in targets:
            if path in busy:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if stat.st_mtime >= cutoff:
                continue
            if not dry_run:
                try:
                    os.remove(path)
                except OSError:
                    continue
            removed.append(path)
            freed += stat.st_size
        if removed:
            self.logger.info(
                "Media cache sweep%s: %d files, %.1f MB older than %g days",
                " (dry run)" if dry_run else "", len(removed), freed / 1048576, days,
            )
        return removed

    def _media_sweeper(self):
        time.sleep(300)
        while True:
            try:
                self._media_sweep()
            except Exception:
                self.logger.exception("Media cache sweep failed")
            time.sleep(3600)

'''

CW = "efb_wechat_comwechat_slave/ComWechat.py"
MR = "efb_wechat_comwechat_slave/media_retry.py"

patch_file(
    CW,
    "    def _process_pending_file(self, path):\n",
    MEDIA_HELPERS + "    def _process_pending_file(self, path):\n",
    "media #5: helper methods",
)

patch_file(
    CW,
    """        elif os.path.isfile(path):
            flag = True
        elif (
            media_type in MEDIA_RETRY_TYPES
            and (int(time.time()) - msg["timestamp"]) >= MEDIA_WAIT_SECONDS
        ):
""",
    """        elif os.path.isfile(path) and (
            media_type not in self._SIZED_TYPES or self._media_ready(path, msg)
        ):
            flag = True
        elif self._take_downloaded_media(path, msg):
            flag = True
        elif (
            media_type in MEDIA_RETRY_TYPES
            and (int(time.time()) - msg["timestamp"]) >= self._media_wait_seconds(msg)
        ):
""",
    "media #5: prefetch + locate real file + size-based wait",
)

patch_file(
    CW,
    '                self.media_retries.delete_files(path, output_msg.get("filepath"))\n',
    '                self.media_retries.delete_files(\n'
    '                    *self._media_cleanup_paths(output_msg, path, output_msg.get("filepath"))\n'
    '                )\n',
    "media #5: full cleanup after pending send",
)

patch_file(
    CW,
    '                self.media_retries.delete_files(msg.get("filepath"), resolved_path)\n',
    '                self.media_retries.delete_files(\n'
    '                    *self._media_cleanup_paths(msg, msg.get("filepath"), resolved_path)\n'
    '                )\n',
    "media #5: full cleanup after direct send",
)

patch_file(
    CW,
    '        self.delete_media_after_send = self.config.get("delete_media_after_send", True) is True\n',
    '        self.delete_media_after_send = self.config.get("delete_media_after_send", True) is True\n'
    '        self.media_prefetch = self.config.get("media_prefetch", True) is True\n'
    '        try:\n'
    '            self.media_cleanup_days = float(self.config.get("media_cleanup_days", 3) or 0)\n'
    '        except (TypeError, ValueError):\n'
    '            self.media_cleanup_days = 3.0\n'
    '        if self.media_cleanup_days > 0:\n'
    '            threading.Thread(target=self._media_sweeper, name="media-sweeper", daemon=True).start()\n',
    "media #5: config + start sweeper",
)

RETRY_WAIT = '''    def _wait_for_media_or_sibling(self, path, media_type, source, msg):
        locate = getattr(self.channel, "_locate_media", None)
        deadline = time.monotonic() + MEDIA_WAIT_SECONDS
        while True:
            existing = self._existing_media_path(path, media_type) if path else None
            if existing is None and source and locate is not None:
                existing = locate(source, msg)
            if existing is not None:
                return existing
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

'''

patch_file(
    MR,
    "    @staticmethod\n    def _existing_media_path(path, media_type):\n",
    RETRY_WAIT + "    @staticmethod\n    def _existing_media_path(path, media_type):\n",
    "media #5: retry waits for name(n) siblings too",
)

patch_file(
    MR,
    "                media_path = self._existing_media_path(source, media_type)\n"
    "                if media_path is None:\n",
    "                media_path = self._existing_media_path(source, media_type)\n"
    "                locate = getattr(self.channel, \"_locate_media\", None)\n"
    "                if media_path is None and source and locate is not None:\n"
    "                    media_path = locate(source, msg)\n"
    "                if media_path is None:\n",
    "media #5: retry reuses an already downloaded copy",
)

patch_file(
    MR,
    "                    media_path = self._wait_for_media(restored_path, media_type)\n",
    "                    media_path = self._wait_for_media_or_sibling(restored_path, media_type, source, msg)\n",
    "media #5: retry locates the real GetCdn output",
)

patch_file(
    MR,
    "            self.delete_files(source, media_path)\n",
    "            cleanup = getattr(self.channel, \"_media_cleanup_paths\", None)\n"
    "            self.delete_files(*(cleanup(msg, source, media_path) if cleanup else (source, media_path)))\n",
    "media #5: full cleanup after retry send",
)

for line in report:
    print(line)
sys.exit(0)

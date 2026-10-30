#!/usr/bin/env python3
"""Patch efb-wechat-comwechat-slave's ComWechat.py.

1. Raise the hard-coded file-download wait (time_out) from 120s to 300s.
   For group chats WeChat defers downloading the original image
   (extrainfo: cdnbigimgurl_pd_pri="30"), so 120s often expires before the
   file lands, producing "[image 下载超时,请在手机端查看]".

2. When an image does time out, fall back to WeChat's thumbnail.

   Note: the thumbnail CANNOT be derived from the original image path -- the two
   have different file names, e.g.
       .../MsgAttach/<hash>/Image/2026-10/3e1bc58c....dat   (original)
       .../MsgAttach/<hash>/Thumb/2026-10/6d11b071...._t.dat (thumbnail)
   WeChat instead reports the thumbnail in msg["thumb_path"] (Windows-style,
   relative to self.dir), which image messages do carry. We use that and verify
   the file really exists before falling back, so a wrong image is never sent.
"""

import pathlib
import sys

TARGET = pathlib.Path(
    "/usr/local/lib/python3.11/site-packages/efb_wechat_comwechat_slave/ComWechat.py"
)

HELPER = '''    def get_thumb_path(self, msg):
        """Return an existing thumbnail file path for this message, or None.

        WeChat reports the thumbnail separately in msg["thumb_path"] as a
        Windows-style path relative to self.dir, e.g.
            wxid_x\\\\FileStorage\\\\MsgAttach\\\\<hash>\\\\Thumb\\\\2026-10\\\\<md5>_t.dat
        The thumbnail file name differs from the original image's, so it cannot
        be derived from msg["filepath"]. The path is only returned when the file
        really exists on disk.
        """
        try:
            raw = msg.get("thumb_path") or ""
            if not raw:
                return None
            p = raw.replace("\\\\", "/")
            if not p.startswith("/"):
                p = f"{self.dir}{p}"
            return p if os.path.exists(p) else None
        except Exception:
            return None

'''

OLD_TIMEOUT = '''                    elif (int(time.time()) - msg["timestamp"]) > self.time_out:
                        msg_type = msg["type"]
                        msg['message'] = f"[{msg_type} 下载超时,请在手机端查看]"
                        msg["type"] = "text"
                        flag = True'''

NEW_TIMEOUT = '''                    elif (int(time.time()) - msg["timestamp"]) > self.time_out:
                        # Original (full-size) file did not arrive in time. If
                        # WeChat already has the thumbnail on disk, send that
                        # instead of a "download timed out" text placeholder.
                        thumb = self.get_thumb_path(msg)
                        if thumb:
                            self.logger.debug(
                                "image timeout, fallback to thumbnail: %s", thumb
                            )
                            msg["filepath"] = thumb
                            flag = True
                        else:
                            msg_type = msg["type"]
                            msg['message'] = f"[{msg_type} 下载超时,请在手机端查看]"
                            msg["type"] = "text"
                            flag = True'''

ANCHOR = "    def handle_file_msg(self):"


def main() -> int:
    if not TARGET.exists():
        print("ERROR: target not found: %s" % TARGET)
        return 1

    src = TARGET.read_text(encoding="utf-8")
    warnings = []

    # 1) widen the download wait
    new = src.replace("    time_out : int = 120", "    time_out : int = 300", 1)
    if new == src:
        warnings.append("time_out pattern not found (already patched?)")
    src = new

    # 2) inject the thumbnail helper
    if "def get_thumb_path" in src:
        warnings.append("get_thumb_path already present, skipped")
    elif ANCHOR in src:
        src = src.replace(ANCHOR, HELPER + ANCHOR, 1)
    else:
        warnings.append("handle_file_msg anchor not found")

    # 3) fall back to the thumbnail on timeout
    if OLD_TIMEOUT in src:
        src = src.replace(OLD_TIMEOUT, NEW_TIMEOUT, 1)
    else:
        warnings.append("timeout branch not found (already patched?)")

    TARGET.write_text(src, encoding="utf-8")
    for w in warnings:
        print("WARN: %s" % w)
    print("patched %s" % TARGET)
    return 0


if __name__ == "__main__":
    sys.exit(main())

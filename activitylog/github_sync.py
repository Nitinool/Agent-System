"""Small GitHub Contents API transport. Network calls never touch Tk or SQLite."""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .sync import MAX_BYTES, REMOTE_PATH, REPOSITORY, RemoteChanged, SyncError, decode, encode


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward an authorization header to any redirected host.
        return None


class GitHubSync:
    def __init__(self, token, *, opener=None):
        if not token or any(c.isspace() for c in token):
            raise SyncError("请在同步设置中填写 GitHub Token。")
        self._token = token
        self._opener = opener if opener is not None else build_opener(NoRedirect())
        self._repo = f"https://api.github.com/repos/{REPOSITORY}"
        self._branch = None

    def _request(self, url, method="GET", payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agent-System-Desktop",
            "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=20) as response:
                content = response.read(MAX_BYTES * 2 + 1)
                if len(content) > MAX_BYTES * 2:
                    raise SyncError("GitHub 返回的数据过大，本次同步已停止。")
                return json.loads(content)
        except HTTPError as error:
            try:
                if error.code == 404:
                    raise SyncError("仓库或文件不可访问，请检查 Token 的仓库权限。") from None
                if error.code in (409, 422):
                    raise RemoteChanged("远端已更新或拒绝本次提交，请重新同步以获取最新内容。") from None
                if error.code in (401, 403):
                    raise SyncError("GitHub 拒绝访问，请检查 Token 是否过期、写入权限和 API 限额。") from None
                raise SyncError(f"GitHub 请求失败（HTTP {error.code}），请稍后重试。") from None
            finally:
                error.close()
        except (URLError, TimeoutError, OSError):
            raise SyncError("连接 GitHub 失败或超时，本地数据仍保留，请稍后重试。") from None
        except (ValueError, TypeError):
            raise SyncError("GitHub 响应格式异常，本次同步已停止。") from None

    def _check_private(self):
        info = self._request(self._repo)
        if not isinstance(info, dict) or info.get("private") is not True:
            raise SyncError("数据仓库必须为私有仓库；本次同步已停止。")
        self._branch = info.get("default_branch")
        if not isinstance(self._branch, str) or not self._branch:
            raise SyncError("无法确认数据仓库的默认分支。")

    def fetch(self):
        self._check_private()
        from urllib.parse import quote
        url = f"{self._repo}/contents/{REMOTE_PATH}?ref={quote(self._branch, safe='')}"
        try:
            info = self._request(url)
        except SyncError as error:
            # Missing files are accepted only after the repository is accessible.
            cause = error.__context__
            if isinstance(cause, HTTPError) and cause.code == 404:
                return {}, None
            raise
        try:
            if info["type"] != "file" or info["encoding"] != "base64" or info["size"] > MAX_BYTES:
                raise ValueError()
            content = base64.b64decode(info["content"]).decode("utf-8")
            sha = info["sha"]
            if not isinstance(sha, str) or len(sha) != 40:
                raise ValueError()
            return decode(content), sha
        except (KeyError, ValueError, TypeError, UnicodeError):
            raise SyncError("远端同步文件无法读取或过大，本地数据仍保留。") from None

    def publish(self, records, sha):
        # Re-check visibility immediately before uploading personal records.
        self._check_private()
        content = encode(records)
        payload = {"message": "Sync personal records", "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": self._branch}
        if sha is not None:
            payload["sha"] = sha
        self._request(f"{self._repo}/contents/{REMOTE_PATH}", "PUT", payload)

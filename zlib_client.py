"""
Z-Library client — vendored from bipinkrish/Zlibrary-API.

Uses the official /eapi/ endpoints (more stable than HTML scraping).
Original: https://github.com/bipinkrish/Zlibrary-API (MIT, Bipinkrish 2023-2024).

Modifications:
- Configurable domain (default: z-library.sk).
- Added getDownloadLink() for URL-only resolution.
"""

import requests


class Zlibrary:
    def __init__(
        self,
        email: str = None,
        password: str = None,
        remix_userid=None,
        remix_userkey: str = None,
        domain: str = "z-library.sk",
    ):
        self.__domain = domain
        self.__loggedin = False
        self.__headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        }
        self.__cookies = {"siteLanguageV2": "en"}

        if email is not None and password is not None:
            self.login(email, password)
        elif remix_userid is not None and remix_userkey is not None:
            self.loginWithToken(remix_userid, remix_userkey)

    def __setValues(self, response):
        if not response.get("success"):
            return response
        self.__remix_userid = str(response["user"]["id"])
        self.__remix_userkey = response["user"]["remix_userkey"]
        self.__cookies["remix_userid"] = self.__remix_userid
        self.__cookies["remix_userkey"] = self.__remix_userkey
        self.__loggedin = True
        return response

    def login(self, email, password):
        return self.__setValues(
            self.__makePostRequest(
                "/eapi/user/login",
                data={"email": email, "password": password},
                override=True,
            )
        )

    def loginWithToken(self, remix_userid, remix_userkey):
        return self.__setValues(
            self.__makeGetRequest(
                "/eapi/user/profile",
                cookies={
                    "siteLanguageV2": "en",
                    "remix_userid": str(remix_userid),
                    "remix_userkey": remix_userkey,
                },
            )
        )

    def __makePostRequest(self, url, data=None, override=False):
        if not self.isLoggedIn() and not override:
            return {"success": False, "error": "Not logged in"}
        return requests.post(
            "https://" + self.__domain + url,
            data=data or {},
            cookies=self.__cookies,
            headers=self.__headers,
            timeout=30,
        ).json()

    def __makeGetRequest(self, url, params=None, cookies=None):
        if not self.isLoggedIn() and cookies is None:
            return {"success": False, "error": "Not logged in"}
        return requests.get(
            "https://" + self.__domain + url,
            params=params or {},
            cookies=self.__cookies if cookies is None else cookies,
            headers=self.__headers,
            timeout=30,
        ).json()

    def isLoggedIn(self):
        return self.__loggedin

    def search(
        self,
        message=None,
        yearFrom=None,
        yearTo=None,
        languages=None,
        extensions=None,
        order=None,
        page=None,
        limit=None,
    ):
        return self.__makePostRequest(
            "/eapi/book/search",
            {
                k: v
                for k, v in {
                    "message": message,
                    "yearFrom": yearFrom,
                    "yearTo": yearTo,
                    "languages[]": languages,
                    "extensions[]": extensions,
                    "order": order,
                    "page": page,
                    "limit": limit,
                }.items()
                if v is not None
            },
        )

    def getBookInfo(self, bookid, hashid):
        return self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}")

    def getDownloadLink(self, book):
        """Return the direct download URL for a book dict from search()."""
        bookid, hashid = book["id"], book["hash"]
        response = self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}/file")
        if not response or not response.get("file"):
            return None
        return response["file"].get("downloadLink")

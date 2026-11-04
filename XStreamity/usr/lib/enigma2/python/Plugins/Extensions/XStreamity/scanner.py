#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function

# Standard library imports
import json
import os
import random

try:
    from urlparse import urlparse, parse_qsl  # Python 2
    from urllib import urlencode
except:
    from urllib.parse import urlparse, parse_qsl, urlencode  # Python 3

try:
    from http.client import HTTPConnection
    HTTPConnection.debuglevel = 0
except ImportError:
    from httplib import HTTPConnection
    HTTPConnection.debuglevel = 0

# Third-party imports. Some older Enigma2 images do not ship requests.
try:
    import requests
except ImportError:
    requests = None

# Enigma2 components
from Components.ActionMap import ActionMap
from Components.Pixmap import Pixmap
from Components.Sources.List import List
from datetime import datetime
from enigma import eTimer
from Screens.Screen import Screen
from Tools.LoadPixmap import LoadPixmap

# Local application/library-specific imports
from . import _
from . import xstreamity_globals as glob
from .plugin import skin_directory, cfg, common_path, version, hasConcurrent, hasMultiprocessing, dir_tmp
from .xStaticText import StaticText


hdr = {}

scans_dir = os.path.join(dir_tmp, "scans")
badurls_file = os.path.join(scans_dir, "badurls.txt")

scanner_playlist_file = os.path.join(scans_dir, "playlists.txt")
scanner_playlists_json = os.path.join(scans_dir, "x-playlists.json")

URLSCAN_API_URL = "https://urlscan.io/api/v1/search/"
URLSCAN_API_KEYS = ["01a19ddb-3052-715c-a635-d66c80169c2d", "01a1a6e9-b1ac-73a3-b618-2f8ff4afd046", "01a1a6fb-53c4-741d-83c9-1844cda24e47"]
URLSCAN_QUERY = 'files.mimeDescription:"M3U playlist" AND task.url:"get.php"'
URLSCAN_PAGE_SIZE = 100
URLSCAN_MAX_PAGES = 3


def sort_key(item):
    activenum = item[6]
    maxnum = item[8]
    exp_ts = item[9]

    try:
        maxnum = int(maxnum)
    except (TypeError, ValueError):
        maxnum = 0

    try:
        activenum = int(activenum)
    except (TypeError, ValueError):
        activenum = 0

    primary = -maxnum
    secondary = -(maxnum - activenum)

    if exp_ts is None:
        tertiary = float("-inf")
    else:
        tertiary = -exp_ts

    return (primary, secondary, tertiary)


class XStreamity_Scanner(Screen):
    ALLOW_SUSPEND = True

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.original_playlist_file = cfg.playlist_file.value
        self.original_playlists_json = cfg.playlists_json.value
        self.original_current_selection = getattr(glob, "current_selection", 0)
        self.original_active_playlist = getattr(glob, "active_playlist", {})
        self.scantimer = None
        self.timer = None
        self._scanner_restored = False
        self.onClose.append(self.restoreOriginalPlaylists)

        if cfg.interface.value == "xstreamity":
            skin_path = os.path.join(skin_directory, cfg.interface.value, cfg.xstreamity_skin.value)

        if cfg.interface.value == "xklass":
            skin_path = os.path.join(skin_directory, cfg.interface.value, cfg.xklass_skin.value)

        skin = os.path.join(skin_path, "playlists.xml")
        with open(skin, "r") as f:
            self.skin = f.read()

        self.setup_title = _("Select Playlist")

        self["key_red"] = StaticText(_("Back"))
        self["key_green"] = StaticText(_("OK"))
        self["key_yellow"] = StaticText()
        self["key_blue"] = StaticText(_("Info"))
        self["version"] = StaticText()
        self["key_menu"] = StaticText()

        self.list = []
        self.drawList = []
        self.playlists_all = []

        self["playlists"] = List(self.drawList, enableWrapAround=True)
        self["playlists"].onSelectionChanged.append(self.getCurrentEntry)
        self["splash"] = Pixmap()
        self["splash"].show()
        self["scroll_up"] = Pixmap()
        self["scroll_down"] = Pixmap()
        self["scroll_up"].hide()
        self["scroll_down"].hide()

        self["actions"] = ActionMap(["XStreamityActions"], {
            "red": self.quit,
            "green": self.getStreamTypes,
            "cancel": self.quit,
            "ok": self.getStreamTypes,
            "blue": self.openUserInfo,
            "info": self.openUserInfo,
        }, -2)

        self.onFirstExecBegin.append(self.safeStart)
        self.onLayoutFinish.append(self.__layoutFinished)

    def __layoutFinished(self):
        self.setTitle(self.setup_title)

    def safeStart(self):
        try:
            self.start()
        except Exception as e:
            print("*** Scanner start error ***", repr(e))
            self.quit()

    def safeMakeScanUrlData(self):
        try:
            self.makeScanUrlData()
        except Exception as e:
            print("*** Scanner search error ***", repr(e))
            self.quit()

    def safeMakeUrlList(self):
        try:
            self.makeUrlList()
        except Exception as e:
            print("*** Scanner playlist error ***", repr(e))
            self.quit()

    def start(self):
        glob.original_playlist_file = self.original_playlist_file
        glob.original_playlists_json = self.original_playlists_json

        if os.path.realpath(self.original_playlist_file) == os.path.realpath(scanner_playlist_file):
            raise RuntimeError("Original playlists.txt uses the scanner path")

        if os.path.realpath(self.original_playlists_json) == os.path.realpath(scanner_playlists_json):
            raise RuntimeError("Original x-playlists.json uses the scanner path")

        self["version"].setText(version)
        self.cleanupScannerFiles()

        self.scantimer = eTimer()
        try:
            self.scantimer_conn = self.scantimer.timeout.connect(self.safeMakeScanUrlData)
        except:
            try:
                self.scantimer.callback.append(self.safeMakeScanUrlData)
            except:
                self.safeMakeScanUrlData()
                return
        self.scantimer.start(10, True)

    def makeScanUrlData(self):
        search_after = None

        if not os.path.exists(scans_dir):
            os.makedirs(scans_dir)

        bad_urls = set()

        if os.path.exists(badurls_file):
            with open(badurls_file, "r") as f:
                bad_urls = set(line.strip() for line in f)

        final_urls_to_write_set = set()  # Use a set to store unique URLs

        if not URLSCAN_API_KEYS:
            self.quit()
            return

        api_key = random.choice(URLSCAN_API_KEYS)

        for i in range(URLSCAN_MAX_PAGES):
            headers = {
                "API-Key": api_key,
                "Accept": "application/json",
            }
            params = {
                "q": URLSCAN_QUERY,
                "size": URLSCAN_PAGE_SIZE,
            }
            if search_after:
                params["search_after"] = search_after

            response = self.download_url([URLSCAN_API_URL, i, headers, params])

            # print("*** response ***", json.dumps(response))

            if not response:
                break

            data = response[1]

            if not data or not data.get("results"):
                break

            for task in data["results"]:
                for scanned_file in task.get("files", []):
                    task_url = scanned_file.get("url", "")
                    if "get.php" not in task_url:
                        continue

                    parsed_url = urlparse(task_url)
                    if not parsed_url.scheme or not parsed_url.hostname:
                        continue

                    query_params = dict(parse_qsl(parsed_url.query))

                    query_params.pop("type", None)
                    query_params.pop("output", None)

                    query_params["type"] = "m3u"
                    query_params["output"] = "ts"

                    new_query = urlencode(query_params)
                    task_url = parsed_url._replace(query=new_query).geturl()

                    url_without_server = task_url.split(" ")[0]

                    if url_without_server.strip() in bad_urls:
                        continue

                    if "get.php" in parsed_url.path and parsed_url.query:
                        final_urls_to_write_set.add((task_url, parsed_url.hostname))

            last_task = data["results"][-1]
            if "sort" in last_task and len(last_task["sort"]) >= 2:
                search_after = "{},{}".format(last_task["sort"][0], last_task["sort"][1])
            else:
                break

        final_urls_to_write = list(final_urls_to_write_set)

        if not final_urls_to_write:
            self.quit()
            return

        with open(scanner_playlist_file, "a") as f:
            for url, domain in final_urls_to_write:
                f.write(url + " #" + str(domain) + "\n")

        cfg.playlist_file.setValue(scanner_playlist_file)
        cfg.playlists_json.setValue(scanner_playlists_json)

        from . import processscanfiles as loadfiles
        self.playlists_all = loadfiles.process_files()

        if self.playlists_all and os.path.isfile(scanner_playlist_file) and os.path.getsize(scanner_playlist_file) > 0:
            self.delayedDownload()
        else:
            self.quit()

    def delayedDownload(self):
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.safeMakeUrlList)
        except:
            try:
                self.timer.callback.append(self.safeMakeUrlList)
            except:
                self.safeMakeUrlList()
                return
        self.timer.start(10, True)

    def makeUrlList(self):
        self.url_list = []
        for index, playlists in enumerate(self.playlists_all):
            player_api = str(playlists["playlist_info"].get("player_api", ""))
            full_url = str(playlists["playlist_info"].get("full_url", ""))
            domain = str(playlists["playlist_info"].get("domain", ""))
            username = str(playlists["playlist_info"].get("username", ""))
            password = str(playlists["playlist_info"].get("password", ""))
            if "get.php" in full_url and domain and username and password:
                self.url_list.append([player_api, index])

        if self.url_list:
            self.process_downloads()
        else:
            self.quit()

    def download_url(self, url):
        index = url[1]
        extra_headers = url[2] if len(url) > 2 else {}
        params = url[3] if len(url) > 3 else None
        response = None

        request_headers = dict(hdr)
        request_headers.update(extra_headers)

        if requests is not None:
            try:
                with requests.Session() as http:
                    r = http.get(
                        url[0],
                        headers=request_headers,
                        params=params,
                        timeout=(5, 10),
                        verify=False
                    )

                    r.raise_for_status()
                    response = r.json()

            except requests.exceptions.HTTPError as e:
                # print("*** Requests HTTP error ***", repr(e))
                if url[0] == URLSCAN_API_URL and e.response is not None:
                    if e.response.status_code == 429:
                        return index, None

            except requests.exceptions.RequestException:
                # print("*** Requests error ***", repr(e))
                pass

            except ValueError:
                # print("*** JSON error ***", repr(e))
                pass

        return index, response

    def process_downloads(self):
        threads = len(self.url_list)
        results = []

        # Load existing bad URLs into a set for quick lookup
        if os.path.exists(badurls_file):
            with open(badurls_file, "r") as f:
                bad_urls = set(line.strip() for line in f)
        else:
            bad_urls = set()

        if hasConcurrent or hasMultiprocessing:
            if hasConcurrent:
                try:
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=threads) as executor:
                        results = list(executor.map(self.download_url, self.url_list))
                except Exception as e:
                    print("Concurrent execution error:", e)

            elif hasMultiprocessing:
                try:
                    from multiprocessing.pool import ThreadPool
                    pool = ThreadPool(threads)
                    results = list(pool.imap_unordered(self.download_url, self.url_list))
                    pool.close()
                    pool.join()
                except Exception as e:
                    print("Multiprocessing execution error:", e)

        else:
            for url in self.url_list:
                result = self.download_url(url)
                results.append(result)

        indices_to_remove = []

        for index, response in results:
            if response:
                self.playlists_all[index].update(response)
            else:
                indices_to_remove.append(index)
                bad_url = self.playlists_all[index]["playlist_info"]["full_url"]
                if bad_url not in bad_urls:
                    with open(badurls_file, "a") as f:
                        f.write(bad_url + "\n")
                    bad_urls.add(bad_url)

        # Remove invalid playlists after the loop
        self.playlists_all = [
            playlist for i, playlist in enumerate(self.playlists_all)
            if i not in indices_to_remove
        ]

        if not self.playlists_all:
            self.quit()
            return

        self.buildPlaylistList()

    def buildPlaylistList(self):
        for playlists in self.playlists_all:

            if "user_info" in playlists:
                user_info = playlists["user_info"]

                if "message" in user_info:
                    del user_info["message"]

                server_info = playlists.get("server_info", {})
                if "https_port" in server_info:
                    del server_info["https_port"]
                if "rtmp_port" in server_info:
                    del server_info["rtmp_port"]

                if "time_now" in server_info:
                    time_formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S", "%Y-%m-%d-%H:%M:%S", "%Y- %m-%d %H:%M:%S"]

                    for time_format in time_formats:
                        try:
                            time_now_datestamp = datetime.strptime(str(server_info["time_now"]), time_format)
                            offset = datetime.now().hour - time_now_datestamp.hour
                            playlists["player_info"]["serveroffset"] = offset
                            break
                        except ValueError:
                            pass

                if "timestamp_now" in server_info:
                    try:
                        timestamp = int(server_info["timestamp_now"])
                        timestamp_dt = datetime.utcfromtimestamp(timestamp)
                        current_dt = datetime.now()
                        time_difference = current_dt - timestamp_dt
                        hour_difference = int(time_difference.total_seconds() / 3600)
                        catchupoffset = hour_difference
                        playlists["player_info"]["catchupoffset"] = catchupoffset
                    except:
                        pass

                auth = user_info.get("auth", 1)
                if not isinstance(auth, int):
                    user_info["auth"] = 1

                if "status" in user_info:
                    valid_statuses = {"Active", "Banned", "Disabled", "Expired"}
                    if user_info["status"] not in valid_statuses:
                        user_info["status"] = "Active"

                if "active_cons" in user_info and not user_info["active_cons"]:
                    user_info["active_cons"] = 0

                if "max_connections" in user_info and not user_info["max_connections"]:
                    user_info["max_connections"] = 0

                if 'allowed_output_formats' in user_info:
                    allowed_formats = user_info['allowed_output_formats'] or []  # Ensure it's always a list
                    output_format = playlists["playlist_info"]["output"]

                    if output_format not in allowed_formats:
                        playlists["playlist_info"]["output"] = str(allowed_formats[0]) if allowed_formats else "ts"

            playlists.pop("available_channels", None)

        self.writeJsonFile()

    def writeJsonFile(self):
        with open(scanner_playlists_json, "w") as f:
            json.dump(self.playlists_all, f, indent=4)
        self.createSetup()

    def createSetup(self):
        self.list = []

        for playlist in self.playlists_all:
            name = playlist["playlist_info"].get("name", playlist["playlist_info"].get("domain", ""))
            url = playlist["playlist_info"].get("host", "")
            status = _("Server Not Responding")
            index = playlist["playlist_info"].get("index", 0)

            active = ""
            activenum = ""
            maxc = ""
            maxnum = ""
            expires = ""
            exp_ts = None

            user_info = playlist.get("user_info", {})

            if "auth" in user_info:

                if str(user_info["auth"]) == "0":
                    continue

                if "active_cons" in user_info and "max_connections" in user_info:
                    try:
                        if int(user_info["active_cons"]) >= int(user_info["max_connections"]):
                            continue
                    except:
                        pass

                if "status" in user_info:
                    if playlist["user_info"]["status"] != "Active":
                        continue

                status = _("Not Authorised")

                if str(user_info["auth"]) == "1":

                    user_status = user_info.get("status", "")
                    status_map = {
                        "Active": _("Active"),
                        "Banned": _("Banned"),
                        "Disabled": _("Disabled"),
                        "Expired": _("Expired")
                    }
                    status = status_map.get(user_status, status)

                    if user_status == "Active":
                        exp_date = user_info.get("exp_date")
                        if exp_date:
                            try:
                                exp_ts = int(exp_date)  # already in seconds
                                expires = _("Expires: ") + datetime.fromtimestamp(exp_ts).strftime("%d-%m-%Y")
                            except:
                                expires = _("Expires: ") + "Null"
                        else:
                            expires = _("Expires: ") + "Null"

                        active = str(_("Active Conn:"))
                        activenum = playlist["user_info"]["active_cons"]

                        try:
                            activenum = int(activenum)
                        except:
                            activenum = 0

                        maxc = str(_("Max Conn:"))
                        maxnum = playlist["user_info"]["max_connections"]

                        try:
                            maxnum = int(maxnum)
                        except:
                            maxnum = 0

            self.list.append([index, name, url, expires, status, active, activenum, maxc, maxnum, exp_ts])

        self.list.sort(key=sort_key)

        if not self.list:
            self.quit()
            return

        self["splash"].hide()

        self.drawList = [self.buildListEntry(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], x[8]) for x in self.list]
        self["playlists"].setList(self.drawList)

        if len(self.list) == 1 and cfg.skipplaylistsscreen.value and "user_info" in self.playlists_all[0] and "status" in self.playlists_all[0]["user_info"] and self.playlists_all[0]["user_info"]["status"] == "Active":
            self.getStreamTypes()

    def buildListEntry(self, index, name, url, expires, status, active, activenum, maxc, maxnum):
        if status == _("Active"):
            pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_green.png"))

            if int(activenum) >= int(maxnum) and int(maxnum) != 0:
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_yellow.png"))
        else:
            if status == _("Banned"):
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_red.png"))
            elif status == _("Expired"):
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_grey.png"))
            elif status == _("Disabled"):
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_grey.png"))
            elif status == _("Server Not Responding"):
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_red.png"))
            elif status == _("Not Authorised"):
                pixmap = LoadPixmap(cached=True, path=os.path.join(common_path, "led_red.png"))

        return (index, str(name), str(url), str(expires), str(status), pixmap, str(active), str(activenum), str(maxc), str(maxnum))

    def cleanupScannerFiles(self):
        original_paths = [
            os.path.realpath(self.original_playlist_file),
            os.path.realpath(self.original_playlists_json)
        ]

        for file_path in [scanner_playlist_file, scanner_playlists_json]:
            if os.path.realpath(file_path) in original_paths:
                # print("*** Skipping original playlist file ***", file_path)
                continue

            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    print("*** Scanner file cleanup error ***", repr(e))

    def restoreOriginalPlaylists(self):
        if self._scanner_restored:
            return

        self._scanner_restored = True

        for timer in [self.scantimer, self.timer]:
            if timer is not None:
                timer.stop()

        cfg.playlist_file.setValue(self.original_playlist_file)
        cfg.playlists_json.setValue(self.original_playlists_json)
        cfg.save()

        glob.current_selection = self.original_current_selection
        glob.active_playlist = self.original_active_playlist

        self.cleanupScannerFiles()

    def quit(self, answer=None):
        self.restoreOriginalPlaylists()
        self["splash"].hide()
        self.close()

    def getCurrentEntry(self):
        if self.list:
            index = self["playlists"].getCurrent()[0]
            for idx, playlists in enumerate(self.playlists_all):
                if playlists["playlist_info"]["index"] == index:
                    glob.current_selection = idx
                    break

            glob.active_playlist = self.playlists_all[glob.current_selection]

            num_playlists = self["playlists"].count()
            if num_playlists > 5:
                self["scroll_up"].show()
                self["scroll_down"].show()

                if glob.current_selection < 5:
                    self["scroll_up"].hide()

                elif glob.current_selection + 1 > ((self["playlists"].count() // 5) * 5):
                    self["scroll_down"].hide()
        else:
            glob.current_selection = 0
            glob.active_playlist = {}

    def openUserInfo(self):
        if self.list:
            current_playlist = glob.active_playlist

            if "user_info" in current_playlist and "auth" in current_playlist["user_info"] and str(current_playlist["user_info"]["auth"]) == "1":
                from . import serverinfo
                self.session.open(serverinfo.XStreamity_UserInfo)

    def getStreamTypes(self):
        from . import menu
        if "user_info" in glob.active_playlist:
            if "auth" in glob.active_playlist["user_info"]:
                if str(glob.active_playlist["user_info"]["auth"]) == "1" and glob.active_playlist["user_info"]["status"] == "Active":
                    self.session.open(menu.XStreamity_Menu)

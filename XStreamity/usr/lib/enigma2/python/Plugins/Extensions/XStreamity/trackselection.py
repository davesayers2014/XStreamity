#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Automatic audio / subtitle track selection for XStreamity players.

IPTV streams played through gstreamer (4097), gstplayer (5001), exteplayer3
(5002) or DreamOS (8193) normally start on whatever track the stream lists
first. Players inherit XStreamityTrackSelection, which attaches a TrackSelector
and is started from playStream() via startTrackSelection(). It picks the
audio and subtitle tracks matching the preferred languages in XStreamity's
settings, once each time a stream starts. Anything the user picks manually
afterwards is left alone.
"""

from __future__ import absolute_import, print_function

import re
import time

from Components.ServiceEventTracker import ServiceEventTracker
from enigma import eTimer, iPlayableService

from .plugin import cfg
from .tracklanguages import LANGS


# every code / name a stream might report -> the full set of equivalents
_ALIASES = {}
for _code, (_name, _others) in LANGS.items():
    _group = frozenset((_code,) + _others)
    for _t in _group:
        _ALIASES[_t] = _group

# Tokens that never identify a language on their own
_IGNORE = frozenset(("", "und", "unk", "unknown", "mis", "mul", "zxx", "---", "none", "audio", "track", "sub", "subs", "subtitle", "subtitles"))

_AC3_HINTS = ("ac3", "ac-3", "eac3", "e-ac3", "e-ac-3", "dolby", "dd+", "dd ", "atmos")


def _tokens(text):
    """Return the set of normalised language tokens contained in text."""
    out = set()
    if not text:
        return out
    try:
        text = str(text).lower()
    except Exception:
        return out
    for tok in re.split(r"[\s,;/|()\[\]_\-.:]+", text):
        if tok in _IGNORE:
            continue
        group = _ALIASES.get(tok)
        if group:
            out.update(group)
        elif len(tok) in (2, 3):
            out.add(tok)
    return out


def _settings():
    """Current preferences, or None when automatic selection is off.

    Returns dict with:
      audio / subtitle : list of token sets in priority order (index kept)
      ac3              : prefer Dolby tracks among matches
      equal_mask       : bit n set = show subtitle preference n+1 even when
                         it is the same language as the audio
    """
    try:
        if cfg.tracksource.value != "xstreamity":
            return None
        return {
            "audio": [_tokens(getattr(cfg, "audiolang%d" % i).value) for i in (1, 2, 3)],
            "subtitle": [_tokens(getattr(cfg, "sublang%d" % i).value) for i in (1, 2, 3)],
            "ac3": bool(cfg.audioac3.value),
            "equal_mask": 0xF if cfg.subsamelang.value else 0,
        }
    except Exception as e:
        print("[XStreamity] settings error:", e)
        return None


class TrackSelector(object):
    """Attached to one XStreamity player screen (needs InfoBarSubtitleSupport for subtitles)."""

    TRACK_RETRY_MS = 1000
    TRACK_MAX_TRIES = 20
    # a track list must be unchanged for this long before it is used -
    # gstreamer / serviceapp report tracks one by one while the stream loads
    STABLE_SECONDS = 0.9

    def __init__(self, player, subtitles=True):
        self.player = player
        self.allow_subs = subtitles
        self.reset()

        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.check)
        except Exception:
            self.timer.callback.append(self.check)

        # Events are only a hint: they are not sent when the stream was already
        # playing before the player opened (live preview), and some stream
        # types never send them. playStream() therefore also calls
        # startTrackSelection(); the retry timer then polls until the tracks
        # are known.
        self.tracker = ServiceEventTracker(screen=player, eventmap={
            iPlayableService.evStart: self.start,
            iPlayableService.evUpdatedInfo: self.updated,
        })

        player.onClose.append(self.stop)

    # ------------------------------------------------------------------

    def reset(self):
        self.audio_done = False
        self.subs_done = False
        self.tries = 0
        self.audio_lang = set()
        self.audio_sig = None
        self.audio_sig_time = 0
        self.sub_sig = None
        self.sub_sig_time = 0
        self.disabled_sub = None
        self.deadline = time.time() + self.TRACK_MAX_TRIES * self.TRACK_RETRY_MS / 1000.0

    @staticmethod
    def _stable(sig, last_sig, last_time):
        """Return (is_stable, new_last_sig, new_last_time)."""
        now = time.time()
        if sig != last_sig:
            return False, sig, now
        return (now - last_time) >= TrackSelector.STABLE_SECONDS, last_sig, last_time

    def stop(self):
        try:
            self.timer.stop()
        except Exception:
            pass

    def start(self):
        """(Re)start selection for the current stream - call after playService()."""
        self.stop()
        self.reset()
        if _settings() is not None:
            self.timer.start(self.TRACK_RETRY_MS, True)

    def updated(self):
        if self.audio_done and self.subs_done:
            self.keep_disabled()
            return
        if _settings() is None:
            return
        # tracks have probably just become available - check soon
        self.timer.start(300, True)

    def check(self):
        if self.audio_done and self.subs_done:
            return

        settings = _settings()
        if settings is None:
            return

        self.tries += 1
        service = self.player.session.nav.getCurrentService()

        if service is not None:
            if not self.audio_done:
                try:
                    self.select_audio(service, settings)
                except Exception as e:
                    print("[XStreamity] audio autoselect error:", e)
                    self.audio_done = True

            # subtitles wait for audio so "same language" can be honoured
            if self.audio_done and not self.subs_done:
                try:
                    self.select_subtitle(service, settings)
                except Exception as e:
                    print("[XStreamity] subtitle autoselect error:", e)
                    self.subs_done = True

        if self.tries >= self.TRACK_MAX_TRIES:
            self.audio_done = True
            self.subs_done = True

        if not (self.audio_done and self.subs_done):
            self.timer.start(self.TRACK_RETRY_MS, True)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def select_audio(self, service, settings):
        audio = service.audioTracks()
        count = audio.getNumberOfTracks() if audio else 0
        if count <= 0:
            return  # not known yet - retry

        tracks = []
        sig = []
        for i in range(count):
            info = audio.getTrackInfo(i)
            lang = info.getLanguage() if info else ""
            desc = info.getDescription() if info else ""
            sig.append((lang, desc))
            tracks.append((i, _tokens(lang) or _tokens(desc), (desc or "").lower()))

        stable, self.audio_sig, self.audio_sig_time = self._stable(tuple(sig), self.audio_sig, self.audio_sig_time)
        if not stable:
            return  # still loading - retry

        try:
            current = audio.getCurrentTrack()
        except Exception:
            current = -1

        target = None
        for pref in settings["audio"]:
            if not pref:
                continue
            matches = [t for t in tracks if t[1] & pref]
            if not matches:
                continue
            target = matches[0]
            if settings["ac3"]:
                for t in matches:
                    if any(h in t[2] for h in _AC3_HINTS):
                        target = t
                        break
            break

        if target is None:
            # nothing preferred - keep stream default, remember its language
            for t in tracks:
                if t[0] == current:
                    self.audio_lang = t[1]
        else:
            self.audio_lang = target[1]
            if target[0] != current:
                print("[XStreamity] auto-selecting audio track %d" % target[0])
                audio.selectTrack(target[0])

        self.audio_done = True

    # ------------------------------------------------------------------
    # Subtitles
    # ------------------------------------------------------------------

    def select_subtitle(self, service, settings):
        player = self.player

        if not self.allow_subs or not hasattr(player, "enableSubtitle"):
            self.subs_done = True
            return

        prefs = settings["subtitle"]
        if not any(prefs):
            # no subtitle preference - leave the image's own behaviour alone
            self.subs_done = True
            return

        subtitle = service.subtitle()
        sublist = subtitle.getSubtitleList() if subtitle else None
        if not sublist:
            return  # not known yet - retry

        stable, self.sub_sig, self.sub_sig_time = self._stable(tuple(tuple(x) for x in sublist), self.sub_sig, self.sub_sig_time)
        if not stable:
            return  # still loading - retry

        # Note: a subtitle may already be on - the image enables its "cached"
        # subtitle (often just the first track) as soon as the stream starts.
        # That is not a user choice, so it is replaced here.
        current = getattr(player, "selected_subtitle", None)
        equal_mask = settings["equal_mask"]

        for index, pref in enumerate(prefs):
            if not pref:
                continue
            # same language as the audio track: only show if allowed
            if self.audio_lang & pref and not (equal_mask & (1 << index)):
                continue
            for sub in sublist:
                try:
                    lang = sub[-1]  # (type, pid, page, magazine, language)
                except Exception:
                    continue
                if _tokens(lang) & pref:
                    if current is None or tuple(current) != tuple(sub):
                        print("[XStreamity] auto-enabling subtitle:", sub)
                        player.enableSubtitle(sub)
                    self.subs_done = True
                    return

        # preferences set but none wanted for this stream: switch off what
        # the image turned on by itself
        if current:
            print("[XStreamity] no preferred subtitle - disabling", current)
            self.disabled_sub = tuple(current)
            player.enableSubtitle(None)

        self.subs_done = True

    def keep_disabled(self):
        """The image re-enables its cached subtitle on later info updates;
        undo that for the start-up window only."""
        if not self.disabled_sub or time.time() > self.deadline:
            return
        current = getattr(self.player, "selected_subtitle", None)
        if current and tuple(current) == self.disabled_sub:
            try:
                self.player.enableSubtitle(None)
            except Exception as e:
                print("[XStreamity] disable error:", e)


class XStreamityTrackSelection(object):
    """Mixin for XStreamity player screens.

    Call XStreamityTrackSelection.__init__(self, subtitles=...) from the
    player's __init__ and self.startTrackSelection() after playService().
    """

    def __init__(self, subtitles=True):
        self._xst_tracks = TrackSelector(self, subtitles=subtitles)

    def startTrackSelection(self):
        selector = getattr(self, "_xst_tracks", None)
        if selector is not None:
            try:
                selector.start()
            except Exception as e:
                print("[XStreamity] track selection start error:", e)

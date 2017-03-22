#!/usr/bin/env python
# encoding:utf-8
# author:dbr/Ben
# project:tvdb_api
# repository:http://github.com/dbr/tvdb_api
# license:unlicense (http://unlicense.org/)
import sys
import os
import time
import requests
import requests_cache
import getpass
import tempfile
import warnings
import logging
import datetime

from tvdb_ui import BaseUI, ConsoleUI
from tvdb_exceptions import (
    tvdb_error, tvdb_shownotfound,
    tvdb_seasonnotfound, tvdb_episodenotfound, tvdb_attributenotfound
)

"""Simple-to-use Python interface to The TVDB's API (thetvdb.com)

Example usage:

>>> from tvdb_api import Tvdb
>>> t = Tvdb()
>>> t['Lost'][4][11]['episodeName']
u'Cabin Fever'
"""
__author__ = "dbr/Ben"
__version__ = "1.10"


IS_PY2 = sys.version_info[0] == 2

if IS_PY2:
    from urllib import quote as url_quote
else:
    from urllib.parse import quote as url_quote


if IS_PY2:
    int_types = (int, long)
    text_type = unicode
else:
    int_types = int
    text_type = str

lastTimeout = None


def log():
    return logging.getLogger("tvdb_api")


class ShowContainer(dict):
    """Simple dict that holds a series of Show instances
    """

    def __init__(self):
        self._stack = []
        self._lastgc = time.time()

    def __setitem__(self, key, value):
        self._stack.append(key)

        # keep only the 100th latest results
        if time.time() - self._lastgc > 20:
            for o in self._stack[:-100]:
                del self[o]
            self._stack = self._stack[-100:]

            self._lastgc = time.time()

        super(ShowContainer, self).__setitem__(key, value)


class Show(dict):
    """Holds a dict of seasons, and show data.
    """
    def __init__(self):
        dict.__init__(self)
        self.data = {}

    def __repr__(self):
        return "<Show %r (containing %s seasons)>" % (
            self.data.get(u'seriesName', 'instance'),
            len(self)
        )

    def __getitem__(self, key):
        if key in self:
            # Key is an episode, return it
            return dict.__getitem__(self, key)

        if key in self.data:
            # Non-numeric request is for show-data
            return dict.__getitem__(self.data, key)

        # Data wasn't found, raise appropriate error
        if isinstance(key, int) or key.isdigit():
            # Episode number x was not found
            raise tvdb_seasonnotfound(
                "Could not find season %s" % (repr(key))
            )
        else:
            # If it's not numeric, it must be an attribute name, which
            # doesn't exist, so attribute error.
            raise tvdb_attributenotfound(
                "Cannot find attribute %s" % (repr(key))
            )

    def airedOn(self, date):
        ret = self.search(str(date), 'firstAired')
        if len(ret) == 0:
            raise tvdb_episodenotfound(
                "Could not find any episodes that aired on %s" % date
            )
        return ret

    def search(self, term=None, key=None):
        """
        Search all episodes in show. Can search all data, or a specific key
        (for example, episodename)

        Always returns an array (can be empty). First index contains the first
        match, and so on.

        Each array index is an Episode() instance, so doing
        search_results[0]['episodename'] will retrieve the episode name of the
        first match.

        Search terms are converted to lower case (unicode) strings.

        # Examples

        These examples assume t is an instance of Tvdb():

        >>> t = Tvdb()
        >>>

        To search for all episodes of Scrubs with a bit of data
        containing "my first day":

        >>> t['Scrubs'].search("my first day")
        [<Episode 01x01 - u'My First Day'>]
        >>>

        Search for "My Name Is Earl" episode named "Faked His Own Death":

        >>> t['My Name Is Earl'].search('Faked My Own Death', key='episodeName')
        [<Episode 01x04 - u'Faked My Own Death'>]
        >>>

        To search Scrubs for all episodes with "mentor" in the episode name:

        >>> t['scrubs'].search('mentor', key='episodeName')
        [<Episode 01x02 - u'My Mentor'>, <Episode 03x15 - u'My Tormented Mentor'>]
        >>>

        # Using search results

        >>> results = t['Scrubs'].search("my first")
        >>> print results[0]['episodeName']
        My First Day
        >>> for x in results: print x['episodeName']
        My First Day
        My First Step
        My First Kill
        >>>
        """
        results = []
        for cur_season in self.values():
            searchresult = cur_season.search(term=term, key=key)
            if len(searchresult) != 0:
                results.extend(searchresult)

        return results


class Season(dict):
    def __init__(self, show=None):
        """The show attribute points to the parent show
        """
        self.show = show

    def __repr__(self):
        return "<Season instance (containing %s episodes)>" % (
            len(self.keys())
        )

    def __getitem__(self, episode_number):
        if episode_number not in self:
            raise tvdb_episodenotfound("Could not find episode %s" % (repr(episode_number)))
        else:
            return dict.__getitem__(self, episode_number)

    def search(self, term=None, key=None):
        """Search all episodes in season, returns a list of matching Episode
        instances.

        >>> t = Tvdb()
        >>> t['scrubs'][1].search('first day')
        [<Episode 01x01 - u'My First Day'>]
        >>>

        See Show.search documentation for further information on search
        """
        results = []
        for ep in self.values():
            searchresult = ep.search(term=term, key=key)
            if searchresult is not None:
                results.append(
                    searchresult
                )
        return results


class Episode(dict):
    def __init__(self, season=None):
        """The season attribute points to the parent season
        """
        self.season = season

    def __repr__(self):
        seasno = self.get(u'airedSeason', 0)
        epno = self.get(u'airedEpisodeNumber', 0)
        epname = self.get(u'episodeName')
        if epname is not None:
            return "<Episode %02dx%02d - %r>" % (seasno, epno, epname)
        else:
            return "<Episode %02dx%02d>" % (seasno, epno)

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            raise tvdb_attributenotfound("Cannot find attribute %s" % (repr(key)))

    def search(self, term=None, key=None):
        """Search episode data for term, if it matches, return the Episode (self).
        The key parameter can be used to limit the search to a specific element,
        for example, episodename.

        This primarily for use use by Show.search and Season.search. See
        Show.search for further information on search

        Simple example:

        >>> e = Episode()
        >>> e['episodeName'] = "An Example"
        >>> e.search("examp")
        <Episode 00x00 - 'An Example'>
        >>>

        Limiting by key:

        >>> e.search("examp", key = "episodeName")
        <Episode 00x00 - 'An Example'>
        >>>
        """
        if term is None:
            raise TypeError("must supply string to search for (contents)")

        term = text_type(term).lower()
        for cur_key, cur_value in self.items():
            cur_key = text_type(cur_key)
            cur_value = text_type(cur_value).lower()
            if key is not None and cur_key != key:
                # Do not search this key
                continue
            if cur_value.find(text_type(term)) > -1:
                return self


class Actors(list):
    """Holds all Actor instances for a show
    """
    pass


class Actor(dict):
    """Represents a single actor. Should contain..

    id,
    image,
    name,
    role,
    sortorder
    """
    def __repr__(self):
        return "<Actor %r>" % self.get("name")


class Tvdb:
    """Create easy-to-use interface to name of season/episode name
    >>> t = Tvdb()
    >>> t['Scrubs'][1][24]['episodeName']
    u'My Last Day'
    """
    def __init__(self,
                 interactive=False,
                 select_first=False,
                 debug=False,
                 cache=True,
                 banners=False,
                 actors=False,
                 custom_ui=None,
                 language=None,
                 search_all_languages=False,
                 apikey=None,
                 username=None,
                 userkey=None,
                 forceConnect=False,
                 dvdorder=False):

        """interactive (True/False):
            When True, uses built-in console UI is used to select the correct show.
            When False, the first search result is used.

        select_first (True/False):
            Automatically selects the first series search result (rather
            than showing the user a list of more than one series).
            Is overridden by interactive = False, or specifying a custom_ui

        debug (True/False) DEPRECATED:
             Replaced with proper use of logging module. To show debug messages:

                 >>> import logging
                 >>> logging.basicConfig(level = logging.DEBUG)

        cache (True/False/str/unicode/urllib2 opener):
            Retrieved XML are persisted to to disc. If true, stores in
            tvdb_api folder under your systems TEMP_DIR, if set to
            str/unicode instance it will use this as the cache
            location. If False, disables caching.  Can also be passed
            an arbitrary Python object, which is used as a urllib2
            opener, which should be created by urllib2.build_opener

            In Python 3, True/False enable or disable default
            caching. Passing string specified directory where to store
            the "tvdb.sqlite3" cache file. Also a custom
            requests.Session instance can be passed (e.g maybe a
            customised instance of requests_cache.CachedSession)

        banners (True/False):
            Retrieves the banners for a show. These are accessed
            via the _banners key of a Show(), for example:

            >>> Tvdb(banners=True)['scrubs']['_banners'].keys()
            [u'fanart', u'poster', u'seasonwide', u'season', u'series']

        actors (True/False):
            Retrieves a list of the actors for a show. These are accessed
            via the _actors key of a Show(), for example:

            >>> t = Tvdb(actors=True)
            >>> t['scrubs']['_actors'][0]['name']
            u'John C. McGinley'

        custom_ui (tvdb_ui.BaseUI subclass):
            A callable subclass of tvdb_ui.BaseUI (overrides interactive option)

        language (2 character language abbreviation):
            The language of the returned data. Is also the language search
            uses. Default is "en" (English). For full list, run..

            >>> Tvdb().config['valid_languages'] #doctest: +ELLIPSIS
            ['da', 'fi', 'nl', ...]

        search_all_languages (True/False):
            By default, Tvdb will only search in the language specified using
            the language option. When this is True, it will search for the
            show in and language

        apikey (str/unicode):
            Override the default thetvdb.com API key. By default it will use
            tvdb_api's own key (fine for small scripts), but you can use your
            own key if desired - this is recommended if you are embedding
            tvdb_api in a larger application)
            See http://thetvdb.com/?tab=apiregister to get your own key

        forceConnect (bool):
            If true it will always try to connect to theTVDB.com even if we
            recently timed out. By default it will wait one minute before
            trying again, and any requests within that one minute window will
            return an exception immediately.
        """

        global lastTimeout

        # if we're given a lastTimeout that is less than 1 min just give up
        if not forceConnect and lastTimeout is not None and datetime.datetime.now() - lastTimeout < datetime.timedelta(minutes=1):
            raise tvdb_error("We recently timed out, so giving up early this time")

        self.shows = ShowContainer()  # Holds all Show classes
        self.corrections = {}  # Holds show-name to show_id mapping

        self.config = {}

        if apikey and username and userkey:
            self.config['auth_payload'] = {
                "apikey": apikey,
                "userkey": username,
                "username": userkey
            }
        else:
            self.config['auth_payload'] = {
                "apikey": "199FD9384384C73A",
                "userkey": "9BBA332F483717C1",
                "username": "pelmen"
            }

        self.config['debug_enabled'] = debug  # show debugging messages

        self.config['custom_ui'] = custom_ui

        self.config['interactive'] = interactive  # prompt for correct series?

        self.config['select_first'] = select_first

        self.config['search_all_languages'] = search_all_languages

        self.config['dvdorder'] = dvdorder

        if cache is True:
            self.session = requests_cache.CachedSession(
                expire_after=21600,  # 6 hours
                backend='sqlite',
                cache_name=self._getTempDir(),
                include_get_headers=True
                )
            self.config['cache_enabled'] = True
        elif cache is False:
            self.session = requests.Session()
            self.config['cache_enabled'] = False
        elif isinstance(cache, str):
            # Specified cache path
            self.session = requests_cache.CachedSession(
                expire_after=21600,  # 6 hours
                backend='sqlite',
                cache_name=os.path.join(cache, "tvdb_api"),
                include_get_headers=True
                )
        else:
            self.session = cache
            try:
                self.session.get
            except AttributeError:
                raise ValueError("cache argument must be True/False, string as cache path or requests.Session-type object (e.g from requests_cache.CachedSession)")

        self.config['banners_enabled'] = banners
        self.config['actors_enabled'] = actors

        if self.config['debug_enabled']:
            warnings.warn(
                "The debug argument to tvdb_api.__init__ will be removed in the next version. "
                "To enable debug messages, use the following code before importing: "
                "import logging; logging.basicConfig(level=logging.DEBUG)"
            )
            logging.basicConfig(level=logging.DEBUG)

        # List of language from http://thetvdb.com/api/0629B785CE550C8D/languages.xml
        # Hard-coded here as it is realtively static, and saves another HTTP request, as
        # recommended on http://thetvdb.com/wiki/index.php/API:languages.xml
        self.config['valid_languages'] = [
            "da", "fi", "nl", "de", "it", "es", "fr", "pl", "hu", "el", "tr",
            "ru", "he", "ja", "pt", "zh", "cs", "sl", "hr", "ko", "en", "sv",
            "no"
        ]

        # thetvdb.com should be based around numeric language codes,
        # but to link to a series like http://thetvdb.com/?tab=series&id=79349&lid=16
        # requires the language ID, thus this mapping is required (mainly
        # for usage in tvdb_ui - internally tvdb_api will use the language abbreviations)
        self.config['langabbv_to_id'] = {
            'el': 20, 'en': 7, 'zh': 27, 'it': 15, 'cs': 28, 'es': 16,
            'ru': 22, 'nl': 13, 'pt': 26, 'no': 9, 'tr': 21, 'pl': 18,
            'fr': 17, 'hr': 31, 'de': 14, 'da': 10, 'fi': 11, 'hu': 19,
            'ja': 25, 'he': 24, 'ko': 32, 'sv': 8, 'sl': 30
        }

        if language is None:
            self.config['language'] = 'en'
        else:
            if language not in self.config['valid_languages']:
                raise ValueError("Invalid language %s, options are: %s" % (
                    language, self.config['valid_languages']
                ))
            else:
                self.config['language'] = language

        # The following url_ configs are based of the
        # http://thetvdb.com/wiki/index.php/Programmers_API
        self.config['base_url'] = "http://thetvdb.com"
        self.config['api_url'] = "https://api.thetvdb.com"

        self.config['url_getSeries'] = u"%(api_url)s/search/series?name=%%s" % self.config

        self.config['url_epInfo'] = u"%(api_url)s/series/%%s/episodes" % self.config

        self.config['url_seriesInfo'] = u"%(api_url)s/series/%%s" % self.config
        self.config['url_actorsInfo'] = u"%(api_url)s/series/%%s/actors" % self.config

        self.config['url_seriesBanner'] = u"%(api_url)s/series/%%s/images" % self.config
        self.config['url_seriesBannerInfo'] = u"%(api_url)s/series/%%s/images/query?keyType=%%s" % self.config
        self.config['url_artworkPrefix'] = u"%(base_url)s/banners/%%s" % self.config

        self.__authorized = False
        self.headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Accept-Language': self.config['language']}

    def _getTempDir(self):
        """Returns the [system temp dir]/tvdb_api-u501 (or
        tvdb_api-myuser)
        """
        if hasattr(os, 'getuid'):
            uid = "u%d" % (os.getuid())
        else:
            # For Windows
            try:
                uid = getpass.getuser()
            except ImportError:
                return os.path.join(tempfile.gettempdir(), "tvdb_api")

        return os.path.join(tempfile.gettempdir(), "tvdb_api-%s" % (uid))

    def _loadUrl(self, url, data=None, recache=False, language=None):
        """Return response from The TVDB API"""
        # TODO: обрабатывать исключения
        # TODO: обновлять токен
        if not self.__authorized:
            self.authorize()

        r = self.session.get(url, headers=self.headers).json()
        r_data = r.get('data')
        links = r.get('links')

        if data and isinstance(data, list):
            data.extend(r_data)
        else:
            data = r_data

        if links and links['next']:
            url = url.split('?')[0]
            _url = url + "?page=%s" % links['next']
            self._loadUrl(_url, data)

        return data

    def authorize(self):
        r = self.session.post('https://api.thetvdb.com/login', json=self.config['auth_payload'], headers=self.headers)
        token = r.json().get('token')
        self.headers['Authorization'] = "Bearer %s" % text_type(token)
        self.__authorized = True

    def _getetsrc(self, url, language=None):
        """Loads a URL using caching, returns an ElementTree of the source
        """
        src = self._loadUrl(url, language=language)

        return src

    def _setItem(self, sid, seas, ep, attrib, value):
        """Creates a new episode, creating Show(), Season() and
        Episode()s as required. Called by _getShowData to populate show

        Since the nice-to-use tvdb[1][24]['name] interface
        makes it impossible to do tvdb[1][24]['name] = "name"
        and still be capable of checking if an episode exists
        so we can raise tvdb_shownotfound, we have a slightly
        less pretty method of setting items.. but since the API
        is supposed to be read-only, this is the best way to
        do it!
        The problem is that calling tvdb[1][24]['episodename'] = "name"
        calls __getitem__ on tvdb[1], there is no way to check if
        tvdb.__dict__ should have a key "1" before we auto-create it
        """
        if sid not in self.shows:
            self.shows[sid] = Show()
        if seas not in self.shows[sid]:
            self.shows[sid][seas] = Season(show=self.shows[sid])
        if ep not in self.shows[sid][seas]:
            self.shows[sid][seas][ep] = Episode(season=self.shows[sid][seas])
        self.shows[sid][seas][ep][attrib] = value

    def _setShowData(self, sid, key, value):
        """Sets self.shows[sid] to a new Show instance, or sets the data
        """
        if sid not in self.shows:
            self.shows[sid] = Show()
        self.shows[sid].data[key] = value

    def search(self, series):
        """This searches TheTVDB.com for the series name
        and returns the result list
        """
        series = url_quote(series.encode("utf-8"))
        log().debug("Searching for show %s" % series)
        seriesEt = self._getetsrc(self.config['url_getSeries'] % (series))
        if not seriesEt:
            log().debug('Series result returned zero')
            raise tvdb_shownotfound("Show-name search returned zero results (cannot find show on TVDB)")

        allSeries = []
        for series in seriesEt:
            series['lid'] = self.config['langabbv_to_id'][self.config['language']]
            log().debug('Found series %(seriesName)s' % series)
            allSeries.append(series)

        return allSeries

    def _getSeries(self, series):
        """This searches TheTVDB.com for the series name,
        If a custom_ui UI is configured, it uses this to select the correct
        series. If not, and interactive == True, ConsoleUI is used, if not
        BaseUI is used to select the first result.
        """
        allSeries = self.search(series)

        if self.config['custom_ui'] is not None:
            log().debug("Using custom UI %s" % (repr(self.config['custom_ui'])))
            ui = self.config['custom_ui'](config=self.config)
        else:
            if not self.config['interactive']:
                log().debug('Auto-selecting first search result using BaseUI')
                ui = BaseUI(config=self.config)
            else:
                log().debug('Interactively selecting show using ConsoleUI')
                ui = ConsoleUI(config=self.config)

        return ui.selectSeries(allSeries)

    def _parseBanners(self, sid):
        """Parses banners XML, from
        http://thetvdb.com/api/[APIKEY]/series/[SERIES ID]/banners.xml

        Banners are retrieved using t['show name]['_banners'], for example:

        >>> t = Tvdb(banners = True)
        >>> t['scrubs']['_banners'].keys()
        [u'fanart', u'poster', u'seasonwide', u'season', u'series']
        >>> t['scrubs']['_banners']['poster']['680x1000'][35308]['_bannerpath']
        u'http://thetvdb.com/banners/posters/76156-2.jpg'
        >>>

        Any key starting with an underscore has been processed (not the raw
        data from the XML)

        This interface will be improved in future versions.
        """
        log().debug('Getting season banners for %s' % (sid))
        bannersEt = self._getetsrc(self.config['url_seriesBanner'] % sid)
        banners = {}
        for cur_banner in bannersEt.keys():
            banners_info = self._getetsrc(self.config['url_seriesBannerInfo'] % (sid, cur_banner))
            for banner_info in banners_info:
                bid = banner_info.get('id')
                btype = banner_info.get('keyType')
                btype2 = banner_info.get('resolution')
                if btype is None or btype2 is None:
                    continue

                if btype not in banners:
                    banners[btype] = {}
                if btype2 not in banners[btype]:
                    banners[btype][btype2] = {}
                if bid not in banners[btype][btype2]:
                    banners[btype][btype2][bid] = {}

                banners[btype][btype2][bid]['bannerpath'] = banner_info['fileName']

                for k, v in list(banners[btype][btype2][bid].items()):
                    if k.endswith("path"):
                        new_key = "_%s" % k
                        log().debug("Transforming %s to %s" % (k, new_key))
                        new_url = self.config['url_artworkPrefix'] % v
                        banners[btype][btype2][bid][new_key] = new_url

            self._setShowData(sid, "_banners", banners)

    def _parseActors(self, sid):
        """Parsers actors XML, from
        http://thetvdb.com/api/[APIKEY]/series/[SERIES ID]/actors.xml

        Actors are retrieved using t['show name]['_actors'], for example:

        >>> t = Tvdb(actors = True)
        >>> actors = t['scrubs']['_actors']
        >>> type(actors)
        <class 'tvdb_api.Actors'>
        >>> type(actors[0])
        <class 'tvdb_api.Actor'>
        >>> actors[0]
        <Actor u'John C. McGinley'>
        >>> sorted(actors[0].keys())
        [u'id', u'image', u'imageAdded', u'imageAuthor', u'lastUpdated', u'name', u'role', u'seriesId', u'sortOrder']
        >>> actors[0]['name']
        u'John C. McGinley'
        >>> actors[0]['image']
        u'http://thetvdb.com/banners/actors/43638.jpg'

        Any key starting with an underscore has been processed (not the raw
        data from the XML)
        """
        log().debug("Getting actors for %s" % (sid))
        actorsEt = self._getetsrc(self.config['url_actorsInfo'] % (sid))

        cur_actors = Actors()
        for curActorItem in actorsEt:
            curActor = Actor()
            for curInfo in curActorItem.keys():
                tag = curInfo
                value = curActorItem[curInfo]
                if value is not None:
                    if tag == "image":
                        value = self.config['url_artworkPrefix'] % (value)
                curActor[tag] = value
            cur_actors.append(curActor)
        self._setShowData(sid, '_actors', cur_actors)

    def _getShowData(self, sid, language):
        """Takes a series ID, gets the epInfo URL and parses the TVDB
        XML file into the shows dict in layout:
        shows[series_id][season_number][episode_number]
        """

        if self.config['language'] is None:
            log().debug('Config language is none, using show language')
            if language is None:
                raise tvdb_error("config['language'] was None, this should not happen")
        else:
            log().debug(
                'Configured language %s override show language of %s' % (
                    self.config['language'],
                    language
                )
            )

        # Parse show information
        log().debug('Getting all series data for %s' % (sid))
        seriesInfoEt = self._getetsrc(
            self.config['url_seriesInfo'] % sid
        )
        for curInfo in seriesInfoEt.keys():
            tag = curInfo
            value = seriesInfoEt[curInfo]

            if value is not None:
                if tag in ['banner', 'fanart', 'poster']:
                    value = self.config['url_artworkPrefix'] % (value)

            self._setShowData(sid, tag, value)

        # Parse banners
        if self.config['banners_enabled']:
            self._parseBanners(sid)

        # Parse actors
        if self.config['actors_enabled']:
            self._parseActors(sid)

        # Parse episode data
        log().debug('Getting all episodes of %s' % (sid))

        url = self.config['url_epInfo'] % sid

        epsEt = self._getetsrc(url, language=language)

        for cur_ep in epsEt:

            if self.config['dvdorder']:
                log().debug('Using DVD ordering.')
                use_dvd = cur_ep.get('dvdSeason') is not None and cur_ep.get('dvdEpisodeNumber') is not None
            else:
                use_dvd = False

            if use_dvd:
                elem_seasnum, elem_epno = cur_ep.get('dvdSeason'), cur_ep.get('dvdEpisodeNumber')
            else:
                elem_seasnum, elem_epno = cur_ep['airedSeason'], cur_ep['airedEpisodeNumber']

            if elem_seasnum is None or elem_epno is None:
                log().warning("An episode has incomplete season/episode number (season: %r, episode: %r)" % (
                    elem_seasnum, elem_epno))
                log().debug(
                    " ".join(
                        "%r is %r" % (child.tag, child.text) for child in cur_ep.getchildren()))
                # TODO: Should this happen?
                continue  # Skip to next episode

            # float() is because https://github.com/dbr/tvnamer/issues/95 - should probably be fixed in TVDB data
            seas_no = elem_seasnum
            ep_no = elem_epno

            for cur_item in cur_ep.keys():
                tag = cur_item
                value = cur_ep[cur_item]
                if value is not None:
                    if tag == 'filename':
                        value = self.config['url_artworkPrefix'] % (value)
                self._setItem(sid, seas_no, ep_no, tag, value)

    def _nameToSid(self, name):
        """Takes show name, returns the correct series ID (if the show has
        already been grabbed), or grabs all episodes and returns
        the correct SID.
        """
        if name in self.corrections:
            log().debug('Correcting %s to %s' % (name, self.corrections[name]))
            sid = self.corrections[name]
        else:
            log().debug('Getting show %s' % name)
            selected_series = self._getSeries(name)
            sid = selected_series['id']
            log().debug('Got %(seriesName)s, id %(id)s' % selected_series)

            self.corrections[name] = sid
            self._getShowData(selected_series['id'], self.config['language'])

        return sid

    def __getitem__(self, key):
        """Handles tvdb_instance['seriesname'] calls.
        The dict index should be the show id
        """
        if isinstance(key, int_types):
            # Item is integer, treat as show id
            if key not in self.shows:
                self._getShowData(key, self.config['language'])
            return self.shows[key]

        sid = self._nameToSid(key)
        log().debug('Got series id %s' % sid)
        return self.shows[sid]

    def __repr__(self):
        return repr(self.shows)


def main():
    """Simple example of using tvdb_api - it just
    grabs an episode name interactively.
    """
    import logging
    logging.basicConfig(level=logging.DEBUG)

    tvdb_instance = Tvdb(interactive=False, cache=False)
    print(tvdb_instance['Lost']['seriesname'])
    print(tvdb_instance['Lost'][1][4]['episodename'])


if __name__ == '__main__':
    main()
